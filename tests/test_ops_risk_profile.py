import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.ops.risk_change_check import RiskChangeCheckReport
from bfa.ops.risk_profile import apply_risk_profile, build_risk_profile_plan


class RiskProfileTests(unittest.TestCase):
    def config(self, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_ACCOUNT_CAPITAL_USDT": "30",
            "BFA_MAX_LEVERAGE": "5",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
            "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
            "BFA_MAX_DAILY_LOSS_USDT": "1",
            "BFA_MAX_OPEN_POSITIONS": "1",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_plan_outputs_expected_8x_dynamic_diff_and_token(self):
        plan = build_risk_profile_plan(self.config(), profile="30u_8x_dynamic")

        changed = {item.key: item.target for item in plan.diff if item.changed}
        self.assertEqual(plan.target_leverage, 8)
        self.assertEqual(changed["BFA_MAX_LEVERAGE"], "8")
        self.assertEqual(changed["BFA_MAX_POSITION_NOTIONAL_USDT"], "20")
        self.assertEqual(changed["BFA_DYNAMIC_POSITION_SIZING_ENABLED"], "true")
        self.assertEqual(plan.target_values["BFA_ADAPTIVE_SIZING_GOVERNOR_ENABLED"], "true")
        self.assertEqual(changed["BFA_ADAPTIVE_SIZING_MAX_MULTIPLIER"], "0.90")
        self.assertTrue(plan.confirmation_token.startswith("RISK-PROFILE-30U_8X_DYNAMIC-"))

    def test_two_position_preview_sets_multi_position_keys(self):
        plan = build_risk_profile_plan(
            self.config(),
            profile="30u_8x_dynamic",
            allow_two_positions=True,
        )

        self.assertEqual(plan.target_values["BFA_MAX_OPEN_POSITIONS"], "2")
        self.assertEqual(plan.target_values["BFA_MULTI_POSITION_ENABLED"], "true")

    def test_10x_multi_dynamic_profile_sets_portfolio_caps(self):
        plan = build_risk_profile_plan(
            self.config(),
            profile="30u_10x_multi_dynamic",
        )

        self.assertEqual(plan.target_leverage, 10)
        self.assertEqual(plan.target_values["BFA_ACCOUNT_CAPITAL_USDT"], "45")
        self.assertEqual(plan.target_values["BFA_MULTI_POSITION_ENABLED"], "true")
        self.assertEqual(plan.target_values["BFA_MAX_OPEN_POSITIONS"], "45")
        self.assertEqual(plan.target_values["BFA_MAX_POSITION_NOTIONAL_USDT"], "400")
        self.assertEqual(plan.target_values["BFA_MAX_RISK_PER_TRADE_USDT"], "0.7")
        self.assertEqual(plan.target_values["BFA_MAX_DAILY_LOSS_USDT"], "2")
        self.assertEqual(plan.target_values["BFA_MAX_MARGIN_PER_POSITION_USDT"], "40")
        self.assertEqual(plan.target_values["BFA_MAX_MARGIN_FRACTION"], "0.90")
        self.assertEqual(plan.target_values["BFA_MAX_EFFECTIVE_NOTIONAL_USDT"], "400")
        self.assertEqual(plan.target_values["BFA_MAX_PORTFOLIO_MARGIN_USDT"], "120")
        self.assertEqual(plan.target_values["BFA_MAX_PORTFOLIO_MARGIN_FRACTION"], "2.50")
        self.assertEqual(plan.target_values["BFA_MAX_PORTFOLIO_NOTIONAL_USDT"], "3600")
        self.assertEqual(plan.target_values["BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT"], "2700")
        self.assertEqual(plan.target_values["BFA_ADAPTIVE_SIZING_GOVERNOR_ENABLED"], "true")
        self.assertEqual(plan.target_values["BFA_ADAPTIVE_SIZING_MAX_MULTIPLIER"], "1.15")
        self.assertEqual(plan.target_values["BFA_HIGH_LEVERAGE_MAX_STOP_TO_LIQUIDATION_RATIO"], "0.45")

    def test_apply_requires_matching_confirmation_token(self):
        report = apply_risk_profile(
            self.config(),
            env_path="unused",
            profile="30u_8x_dynamic",
            confirm_token=None,
            risk_change_report=RiskChangeCheckReport(
                status="risk_change_allowed",
                risk_change_allowed=True,
            ),
        )

        self.assertFalse(report.applied)
        self.assertEqual(report.status, "confirmation_required")

    def test_apply_blocks_when_risk_change_is_not_allowed(self):
        plan = build_risk_profile_plan(self.config(), profile="30u_8x_dynamic")
        report = apply_risk_profile(
            self.config(),
            env_path="unused",
            profile="30u_8x_dynamic",
            confirm_token=plan.confirmation_token,
            risk_change_report=RiskChangeCheckReport(
                status="keep_current_profile",
                risk_change_allowed=False,
                reasons=["active_position_present"],
            ),
        )

        self.assertFalse(report.applied)
        self.assertEqual(report.status, "apply_blocked")
        self.assertIn("risk_change_not_allowed", report.reasons)

    def test_apply_writes_only_profile_keys_and_preserves_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            env_path.write_text(
                "\n".join(
                    [
                        "BFA_MODE=live",
                        "BFA_MAX_LEVERAGE=5",
                        "BFA_MAX_POSITION_NOTIONAL_USDT=12",
                        "BINANCE_API_KEY=keep-key",
                        "BINANCE_API_SECRET=keep-secret",
                        "DEEPSEEK_API_KEY=keep-deepseek",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config = load_config(env_file=env_path)
            plan = build_risk_profile_plan(config, profile="30u_8x_dynamic")

            report = apply_risk_profile(
                config,
                env_path=str(env_path),
                profile="30u_8x_dynamic",
                confirm_token=plan.confirmation_token,
                risk_change_report=RiskChangeCheckReport(
                    status="risk_change_allowed",
                    risk_change_allowed=True,
                ),
            )

            text = env_path.read_text(encoding="utf-8")
            backup = Path(report.backup_path)
            backup_exists = backup.exists()

        self.assertTrue(report.applied)
        self.assertTrue(backup_exists)
        self.assertIn("BFA_MAX_LEVERAGE=8", text)
        self.assertIn("BFA_DYNAMIC_POSITION_SIZING_ENABLED=true", text)
        self.assertIn("BINANCE_API_KEY=keep-key", text)
        self.assertIn("BINANCE_API_SECRET=keep-secret", text)
        self.assertIn("DEEPSEEK_API_KEY=keep-deepseek", text)


if __name__ == "__main__":
    unittest.main()
