import unittest

from bfa.config import load_config
from bfa.ops.live_resume_plan import apply_live_resume_plan, build_live_resume_plan


class LiveResumePlanTests(unittest.TestCase):
    def test_preview_blocks_collect_more_paper_without_mutation(self):
        report = build_live_resume_plan(
            _config(),
            operator_decision=_packet(status="collect_more_paper", eligible=False),
            current_systemd_states={
                "live.timer": "inactive",
                "live.service": "inactive",
                "paper.timer": "active",
                "paper.service": "inactive",
            },
        )

        payload = report.to_dict()
        self.assertEqual(payload["schema"], "bfa_live_resume_plan_v1")
        self.assertEqual(payload["status"], "resume_apply_blocked")
        self.assertFalse(payload["resume_allowed"])
        self.assertFalse(payload["applies_changes"])
        self.assertIn("operator_decision_collect_more_paper", payload["reasons"])
        self.assertFalse(payload["read_only"]["writes_env_files"])
        self.assertFalse(payload["read_only"]["changes_systemd_state"])
        self.assertFalse(payload["read_only"]["mutates_exchange_state"])
        self.assertEqual(payload["risk_boundaries"]["max_leverage"], 10.0)
        self.assertEqual(payload["risk_boundaries"]["max_open_positions"], 5)
        self.assertEqual(payload["risk_boundaries"]["max_position_notional_usdt"], 50.0)
        self.assertEqual(payload["risk_boundaries"]["max_portfolio_notional_usdt"], 300.0)

    def test_eligible_preview_builds_confirmation_token_and_systemd_plan(self):
        report = build_live_resume_plan(
            _config(),
            operator_decision=_packet(),
            readiness_artifact_path="runtime/readiness.json",
            current_systemd_states={
                "live.timer": "inactive",
                "live.service": "inactive",
                "paper.timer": "active",
                "paper.service": "inactive",
            },
        )

        payload = report.to_dict()
        live_timer = _action(payload, "live.timer")
        live_service = _action(payload, "live.service")
        self.assertEqual(payload["status"], "resume_apply_ready")
        self.assertTrue(payload["resume_allowed"])
        self.assertTrue(payload["confirmation_token"].startswith("LIVE-RESUME-30U_10X_MULTI_DYNAMIC-"))
        self.assertEqual(payload["reasons"], ["operator_packet_eligible_confirmation_required"])
        self.assertEqual(live_timer["action"], "start")
        self.assertTrue(live_timer["needed"])
        self.assertEqual(live_service["action"], "none")
        self.assertFalse(live_service["needed"])

    def test_apply_blocks_non_eligible_packet_before_risk_or_systemd(self):
        calls = []

        report = apply_live_resume_plan(
            _config(),
            env_path="unused",
            operator_decision=_packet(status="collect_more_paper", eligible=False),
            confirm_token="anything",
            risk_profile_apply_fn=lambda *args, **kwargs: calls.append("risk"),
            systemd_apply_fn=lambda actions: calls.append("systemd"),
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "apply_blocked")
        self.assertFalse(payload["applied"])
        self.assertIn("operator_decision_not_eligible", payload["reasons"])
        self.assertEqual(calls, [])

    def test_apply_requires_matching_live_resume_token(self):
        report = apply_live_resume_plan(
            _config(),
            env_path="unused",
            operator_decision=_packet(),
            confirm_token="wrong",
            risk_profile_apply_fn=lambda *args, **kwargs: {"applied": True},
            systemd_apply_fn=lambda actions: [],
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "confirmation_required")
        self.assertFalse(payload["applied"])
        self.assertIn("confirmation_token_missing_or_mismatch", payload["reasons"])

    def test_apply_blocks_when_live_service_active(self):
        plan = build_live_resume_plan(_config(), operator_decision=_packet())

        report = apply_live_resume_plan(
            _config(),
            env_path="unused",
            operator_decision=_packet(),
            confirm_token=plan.confirmation_token,
            current_systemd_states={
                "live.timer": "active",
                "live.service": "active",
                "paper.timer": "active",
                "paper.service": "inactive",
            },
            risk_profile_apply_fn=lambda *args, **kwargs: {"applied": True},
            systemd_apply_fn=lambda actions: [],
        )

        self.assertEqual(report.status, "apply_blocked")
        self.assertFalse(report.applied)
        self.assertIn("live_service_active", report.reasons)

    def test_apply_blocks_when_live_service_state_is_unknown(self):
        plan = build_live_resume_plan(_config(), operator_decision=_packet())

        report = apply_live_resume_plan(
            _config(),
            env_path="unused",
            operator_decision=_packet(),
            confirm_token=plan.confirmation_token,
            risk_profile_apply_fn=lambda *args, **kwargs: {"applied": True},
            systemd_apply_fn=lambda actions: [],
        )

        self.assertEqual(report.status, "apply_blocked")
        self.assertFalse(report.applied)
        self.assertIn("live_service_state_not_confirmed_inactive", report.reasons)

    def test_eligible_confirmed_apply_uses_profile_token_and_systemd_actions(self):
        risk_calls = []
        systemd_calls = []
        plan = build_live_resume_plan(
            _config(),
            operator_decision=_packet(),
            current_systemd_states={
                "live.timer": "inactive",
                "live.service": "inactive",
                "paper.timer": "active",
                "paper.service": "inactive",
            },
        )

        def fake_risk_apply(*args, **kwargs):
            risk_calls.append(kwargs)
            return {
                "status": "applied",
                "applied": True,
                "reasons": ["profile_applied"],
                "written_keys": ["BFA_MAX_LEVERAGE"],
            }

        def fake_systemd(actions):
            systemd_calls.extend(actions)
            return [{**action.to_dict(), "applied": True, "return_code": 0} for action in actions]

        report = apply_live_resume_plan(
            _config(),
            env_path="/tmp/env",
            db_path="/tmp/agent.sqlite",
            operator_decision=_packet(),
            confirm_token=plan.confirmation_token,
            current_systemd_states={
                "live.timer": "inactive",
                "live.service": "inactive",
                "paper.timer": "active",
                "paper.service": "inactive",
            },
            risk_profile_apply_fn=fake_risk_apply,
            systemd_apply_fn=fake_systemd,
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "applied")
        self.assertTrue(payload["applied"])
        self.assertEqual(risk_calls[0]["confirm_token"], payload["plan"]["target_profile"]["confirmation_token"])
        self.assertEqual(risk_calls[0]["profile"], "30u_10x_multi_dynamic")
        self.assertEqual([action.name for action in systemd_calls], ["live.timer"])
        self.assertFalse(payload["read_only"]["mutates_exchange_state"])
        self.assertFalse(payload["read_only"]["places_orders"])


def _config():
    return load_config(
        {
            "BFA_MODE": "live",
            "BFA_ACCOUNT_CAPITAL_USDT": "30",
            "BFA_MAX_LEVERAGE": "10",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "50",
            "BFA_MAX_RISK_PER_TRADE_USDT": "0.4",
            "BFA_MAX_DAILY_LOSS_USDT": "1",
            "BFA_MAX_OPEN_POSITIONS": "5",
            "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
            "BFA_MAX_MARGIN_PER_POSITION_USDT": "5",
            "BFA_MAX_MARGIN_FRACTION": "0.18",
            "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "50",
            "BFA_MAX_PORTFOLIO_MARGIN_USDT": "25",
            "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "0.85",
            "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "300",
            "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "250",
            "BFA_MULTI_POSITION_ENABLED": "true",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
    )


def _packet(*, status="eligible_for_operator_resume", eligible=True):
    return {
        "schema": "bfa_operator_resume_decision_v1",
        "status": status,
        "eligible_for_operator_resume": eligible,
        "readiness_status": "live_resume_blocked",
        "readiness_live_resume_allowed": False,
        "recommendation": {
            "next_action": "prepare_separate_operator_confirmation_flow",
            "blocking_categories": [],
        },
    }


def _action(payload, name):
    for action in payload["systemd_plan"]["actions"]:
        if action["name"] == name:
            return action
    raise AssertionError(f"missing action {name}")


if __name__ == "__main__":
    unittest.main()
