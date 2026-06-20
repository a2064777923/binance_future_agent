import unittest

from bfa.ops.operator_resume_decision import build_operator_resume_decision_packet_from_readiness


class OperatorResumeDecisionTests(unittest.TestCase):
    def test_resolve_exposure_takes_priority_over_paper_blockers(self):
        packet = build_operator_resume_decision_packet_from_readiness(
            readiness_payload(
                reasons={
                    "matrix": ["suite_variant_not_promoted"],
                    "strategy_evidence": ["paper_signals_missing"],
                    "server_state": [],
                    "exchange_state": ["manual_or_unattributed_exchange_exposure_present"],
                    "risk_profile": ["active_position_present"],
                    "confirmation": ["operator_confirmation_required"],
                },
                exchange_review={
                    "manual_or_unattributed_symbols": ["ETHUSDT", "BTWUSDT"],
                    "agent_managed_symbols": [],
                    "manual_exposure_is_agent_evidence": False,
                    "position_count": 2,
                    "open_order_count": 0,
                    "open_algo_order_count": 0,
                },
            )
        )

        payload = packet.to_dict()
        self.assertEqual(packet.status, "resolve_exposure")
        self.assertFalse(packet.eligible_for_operator_resume)
        self.assertEqual(payload["exposure"]["manual_or_unattributed_symbols"], ["ETHUSDT", "BTWUSDT"])
        self.assertFalse(payload["exposure"]["manual_exposure_is_agent_evidence"])
        self.assertIn("paper", payload["recommendation"]["blocking_categories"])
        self.assertIn("risk_profile", payload["recommendation"]["blocking_categories"])
        self.assertFalse(payload["read_only"]["restores_live_timer"])
        self.assertFalse(payload["read_only"]["places_orders"])

    def test_collect_more_paper_when_strategy_and_paper_are_only_non_confirmation_blockers(self):
        packet = build_operator_resume_decision_packet_from_readiness(
            readiness_payload(
                reasons={
                    "matrix": ["suite_variant_not_promoted"],
                    "strategy_evidence": ["paper_outcome_count_below_min"],
                    "server_state": [],
                    "exchange_state": [],
                    "risk_profile": [],
                    "confirmation": ["operator_confirmation_required"],
                }
            )
        )

        payload = packet.to_dict()
        self.assertEqual(packet.status, "collect_more_paper")
        self.assertEqual(
            payload["recommendation"]["next_action"],
            "collect_more_guarded_paper_or_recalibrate_before_live_resume",
        )
        self.assertEqual(payload["blocker_groups"]["strategy"], ["suite_variant_not_promoted"])
        self.assertEqual(payload["blocker_groups"]["paper"], ["paper_outcome_count_below_min"])

    def test_confirmation_only_is_eligible_for_separate_operator_resume_flow(self):
        packet = build_operator_resume_decision_packet_from_readiness(
            readiness_payload(
                readiness_status="live_resume_blocked",
                readiness_live_resume_allowed=False,
                reasons={
                    "matrix": [],
                    "strategy_evidence": [],
                    "server_state": [],
                    "exchange_state": [],
                    "risk_profile": [],
                    "confirmation": ["operator_confirmation_required"],
                },
            )
        )

        payload = packet.to_dict()
        self.assertEqual(packet.status, "eligible_for_operator_resume")
        self.assertTrue(packet.eligible_for_operator_resume)
        self.assertTrue(payload["confirmation_flow"]["separate_explicit_flow_required"])
        self.assertFalse(payload["confirmation_flow"]["this_packet_performs_resume"])
        self.assertFalse(payload["read_only"]["applies_risk_profiles"])


def readiness_payload(
    *,
    reasons,
    exchange_review=None,
    readiness_status="keep_live_paused",
    readiness_live_resume_allowed=False,
):
    return {
        "schema": "bfa_live_resume_readiness_v1",
        "status": readiness_status,
        "live_resume_allowed": readiness_live_resume_allowed,
        "reasons": reasons,
        "exchange_review": exchange_review
        or {
            "manual_or_unattributed_symbols": [],
            "agent_managed_symbols": [],
            "manual_exposure_is_agent_evidence": False,
            "position_count": 0,
            "open_order_count": 0,
            "open_algo_order_count": 0,
        },
        "read_only": {
            "places_orders": False,
            "applies_risk_profiles": False,
            "writes_env_files": False,
            "changes_systemd_state": False,
            "mutates_exchange_state": False,
            "creates_order_intents": False,
            "restores_live_timer": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
