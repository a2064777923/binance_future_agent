import unittest

from bfa.config import load_config
from bfa.execution.sizing import compute_position_sizing, dynamic_sizing_enabled, sizing_input_from_config


class ExecutionSizingTests(unittest.TestCase):
    def test_disabled_dynamic_sizing_uses_fixed_notional_cap(self):
        config = load_config(
            {
                "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
                "BFA_MAX_LEVERAGE": "5",
            }
        )

        result = compute_position_sizing(
            sizing_input_from_config(config),
            enabled=dynamic_sizing_enabled(config),
        )

        self.assertFalse(result.enabled)
        self.assertEqual(result.max_position_notional_usdt, 12)
        self.assertAlmostEqual(result.max_position_margin_usdt, 12 / 5)

    def test_30u_5x_dynamic_sizing_keeps_conservative_margin_cap(self):
        config = load_config(
            {
                "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
                "BFA_ACCOUNT_CAPITAL_USDT": "30",
                "BFA_MAX_LEVERAGE": "5",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
                "BFA_MAX_MARGIN_PER_POSITION_USDT": "3",
                "BFA_MAX_MARGIN_FRACTION": "0.08",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
                "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
            }
        )

        result = compute_position_sizing(
            sizing_input_from_config(config, available_balance_usdt=28),
            enabled=True,
        )

        self.assertTrue(result.enabled)
        self.assertAlmostEqual(result.max_position_notional_usdt, 11.2)
        self.assertAlmostEqual(result.max_position_margin_usdt, 2.24)

    def test_30u_8x_dynamic_sizing_can_scale_notional_under_same_margin_fraction(self):
        config = load_config(
            {
                "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
                "BFA_ACCOUNT_CAPITAL_USDT": "30",
                "BFA_MAX_LEVERAGE": "8",
                "BFA_MAX_MARGIN_PER_POSITION_USDT": "3",
                "BFA_MAX_MARGIN_FRACTION": "0.08",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
                "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
            }
        )

        result = compute_position_sizing(
            sizing_input_from_config(config, available_balance_usdt=30),
            enabled=True,
        )

        self.assertAlmostEqual(result.max_position_notional_usdt, 19.2)
        self.assertAlmostEqual(result.max_position_margin_usdt, 2.4)

    def test_stop_distance_can_reduce_dynamic_notional(self):
        config = load_config(
            {
                "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
                "BFA_ACCOUNT_CAPITAL_USDT": "30",
                "BFA_MAX_LEVERAGE": "8",
                "BFA_MAX_MARGIN_PER_POSITION_USDT": "3",
                "BFA_MAX_MARGIN_FRACTION": "0.08",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
                "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
            }
        )

        result = compute_position_sizing(
            sizing_input_from_config(config, entry_price=100, stop_price=97),
            enabled=True,
        )

        self.assertAlmostEqual(result.max_position_notional_usdt, 10)
        self.assertIn("stop_risk_cap", result.reasons)

    def test_warns_when_dynamic_cap_is_below_min_executable_notional(self):
        config = load_config(
            {
                "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
                "BFA_ACCOUNT_CAPITAL_USDT": "30",
                "BFA_MAX_LEVERAGE": "5",
                "BFA_MAX_MARGIN_PER_POSITION_USDT": "1",
                "BFA_MAX_MARGIN_FRACTION": "0.02",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
            }
        )

        result = compute_position_sizing(
            sizing_input_from_config(
                config,
                candidate={"features": {"min_executable_notional": 5.1}},
            ),
            enabled=True,
        )

        self.assertLess(result.max_position_notional_usdt, 5.1)
        self.assertIn("below_min_executable_notional", result.warnings)


if __name__ == "__main__":
    unittest.main()
