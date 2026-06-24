import unittest

from bfa.config import load_config
from bfa.execution.models import RiskState
from bfa.execution.sizing import (
    apply_adaptive_sizing_governor,
    compute_position_sizing,
    dynamic_sizing_enabled,
    sizing_input_from_config,
)


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

    def test_adaptive_governor_can_scale_strong_setup_inside_hard_caps(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
                "BFA_STRONG_LIQUIDITY_QUOTE_VOLUME_USDT": "50000000",
            }
        )

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(notional=120, edge=55, confidence=0.84, stop_distance=1.0),
            candidate=_candidate(quote_volume=120_000_000, volatility=1.2),
            risk_state=RiskState(account_available_balance_usdt=80),
        )

        self.assertTrue(result.accepted)
        self.assertGreater(result.final_notional_usdt, 120)
        self.assertLessEqual(result.final_notional_usdt, 500)
        self.assertIn("adaptive_scaled_up_within_caps", result.reason_codes)
        self.assertEqual(result.diagnostics["hard_cap_candidates"]["max_position_notional"], 500)

    def test_adaptive_governor_downsizes_weak_or_manual_pressure_setup(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
            }
        )

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(notional=220, edge=12, confidence=0.58, stop_distance=1.0),
            candidate=_candidate(quote_volume=8_000_000, volatility=4.0),
            risk_state=RiskState(
                account_available_balance_usdt=80,
                manual_exposures=[{"symbol": "BTWUSDT", "initial_margin_usdt": 55}],
            ),
        )

        self.assertTrue(result.accepted)
        self.assertLess(result.final_notional_usdt, 220)
        self.assertIn("adaptive_downsized", result.reason_codes)
        self.assertIn("adaptive_manual_margin_pressure_downsize", result.warnings)

    def test_adaptive_governor_does_not_upsize_weak_signal_just_because_cap_is_wide(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
            }
        )

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(notional=120, edge=14, confidence=0.58, stop_distance=1.0),
            candidate=_candidate(quote_volume=18_000_000, volatility=2.0),
            risk_state=RiskState(account_available_balance_usdt=80),
        )

        self.assertTrue(result.accepted)
        self.assertLessEqual(result.final_notional_usdt, 120)
        self.assertFalse(result.diagnostics["expansion_allowed"])

    def test_high_leverage_governor_blocks_stop_too_close_to_liquidation(self):
        config = load_config(
            {
                "BFA_MAX_LEVERAGE": "20",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_HIGH_LEVERAGE_THRESHOLD": "8",
                "BFA_HIGH_LEVERAGE_MAX_STOP_TO_LIQUIDATION_RATIO": "0.15",
            }
        )

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(notional=120, edge=50, confidence=0.82, stop_distance=2.0),
            candidate=_candidate(quote_volume=80_000_000, volatility=1.0),
            risk_state=RiskState(account_available_balance_usdt=80),
        )

        self.assertFalse(result.accepted)
        self.assertIsNone(result.final_notional_usdt)
        self.assertIn("stop_too_close_to_liquidation_for_high_leverage", result.reason_codes)

    def test_forward_paper_factor_downsize_mode_reduces_notional_without_blocking(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
            }
        )
        paper_guard = type(
            "PaperGuard",
            (),
            {
                "active": True,
                "symbol_blocks": {},
                "side_blocks": {},
                "factor_blocks": {"24h_momentum": object()},
                "factor_mode": "downsize",
                "factor_downsize_multiplier": 0.5,
            },
        )()

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(
                notional=120,
                edge=50,
                confidence=0.82,
                stop_distance=1.0,
                reasons=["quant_long_setup", "24h_momentum"],
            ),
            candidate=_candidate(quote_volume=80_000_000, volatility=1.0),
            risk_state=RiskState(account_available_balance_usdt=80),
            paper_guard=paper_guard,
        )

        self.assertTrue(result.accepted)
        self.assertLess(result.final_notional_usdt, 120)
        self.assertIn("adaptive_downsized", result.reason_codes)
        self.assertIn("forward_paper_factor_downsize:24h_momentum", result.warnings)

    def test_forward_paper_side_downsize_mode_reduces_notional_without_blocking(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
            }
        )
        paper_guard = type(
            "PaperGuard",
            (),
            {
                "active": True,
                "symbol_blocks": {},
                "side_blocks": {"long": object()},
                "factor_blocks": {},
                "side_mode": "downsize",
                "side_downsize_multiplier": 0.4,
            },
        )()

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(notional=120, edge=50, confidence=0.82, stop_distance=1.0),
            candidate=_candidate(quote_volume=80_000_000, volatility=1.0),
            risk_state=RiskState(account_available_balance_usdt=80),
            paper_guard=paper_guard,
        )

        self.assertTrue(result.accepted)
        self.assertLess(result.final_notional_usdt, 120)
        self.assertIn("adaptive_downsized", result.reason_codes)
        self.assertIn("forward_paper_side_downsize:long", result.warnings)

    def test_forward_paper_factor_observe_mode_records_warning_without_downsizing(self):
        config = load_config(
            {
                "BFA_ACCOUNT_CAPITAL_USDT": "100",
                "BFA_MAX_LEVERAGE": "10",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "500",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "500",
                "BFA_MAX_RISK_PER_TRADE_USDT": "5",
                "BFA_MAX_PORTFOLIO_MARGIN_USDT": "100",
                "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "1",
            }
        )
        paper_guard = type(
            "PaperGuard",
            (),
            {
                "active": True,
                "symbol_blocks": {},
                "side_blocks": {},
                "factor_blocks": {"24h_momentum": object()},
                "factor_mode": "observe",
                "factor_downsize_multiplier": 0.5,
            },
        )()

        result = apply_adaptive_sizing_governor(
            config,
            setup=_setup(
                notional=120,
                edge=50,
                confidence=0.82,
                stop_distance=1.0,
                reasons=["quant_long_setup", "24h_momentum"],
            ),
            candidate=_candidate(quote_volume=80_000_000, volatility=1.0),
            risk_state=RiskState(account_available_balance_usdt=80),
            paper_guard=paper_guard,
        )

        self.assertTrue(result.accepted)
        self.assertGreaterEqual(result.final_notional_usdt, 120)
        self.assertIn("forward_paper_factor_observed:24h_momentum", result.warnings)


def _setup(
    *,
    notional: float,
    edge: float,
    confidence: float,
    stop_distance: float,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "symbol": "SOLUSDT",
        "decision": "trade",
        "side": "long",
        "confidence": confidence,
        "entry_price": 100.0,
        "stop_price": 100.0 * (1 - stop_distance / 100),
        "target_price": 103.0,
        "notional_usdt": notional,
        "hold_time_minutes": 15,
        "factor_summary": {
            "edge_score": edge,
            "confidence": confidence,
            "coverage_ratio": 0.92,
        },
        "price_basis": {
            "stop_distance_percent": stop_distance,
            "risk_reward_ratio": 2.0,
            "sizing_diagnostics": {"stop_distance_percent": stop_distance},
            "liquidation_diagnostics": {
                "approx_liquidation_distance_percent": 10.0,
                "stop_before_liquidation": True,
            },
        },
        "reasons": reasons or ["quant_long_setup"],
        "warnings": [],
    }


def _candidate(*, quote_volume: float, volatility: float) -> dict:
    return {
        "symbol": "SOLUSDT",
        "features": {
            "quote_volume": quote_volume,
            "atr_percent": volatility,
            "min_executable_notional": 5.0,
        },
    }


if __name__ == "__main__":
    unittest.main()
