import unittest

from bfa.ai.schema import RiskLimits
from bfa.config import load_config
from bfa.strategy.candidates import CandidateSignal
from bfa.strategy.micro_grid_live import MicroGridLiveConfig, micro_grid_setup_from_candidate


class MicroGridLiveAdapterTests(unittest.TestCase):
    def risk_limits(self) -> RiskLimits:
        return RiskLimits(
            account_capital_usdt=100.0,
            max_leverage=30.0,
            max_position_notional_usdt=600.0,
            max_risk_per_trade_usdt=4.0,
            max_daily_loss_usdt=10.0,
            max_open_positions=8,
        )

    def candidate(self, *, max_hold_seconds: int, order_wait_seconds: int) -> CandidateSignal:
        return CandidateSignal(
            symbol="BTCUSDT",
            score=3.0,
            narrative_score=0.0,
            market_score=3.0,
            reason_codes=["strategy_leg:micro_grid"],
            data_quality_notes=[],
            source_event_ids=[],
            market_event_ids=[],
            generated_at="2026-06-24T00:00:00Z",
            features={
                "strategy_leg": "micro_grid",
                "micro_grid_side": "long",
                "micro_grid_entry_price": 100.0,
                "micro_grid_stop_price": 99.0,
                "micro_grid_target_price": 102.0,
                "micro_grid_max_hold_seconds": max_hold_seconds,
                "micro_grid_order_wait_seconds": order_wait_seconds,
                "micro_grid_quality_scale": 1.0,
                "micro_grid_latency": {
                    "source": "micro_grid_live",
                    "signal_time_ms": 1_700_000_000_000,
                    "candidate_generated_at_ms": 1_700_000_001_250,
                    "signal_to_candidate_ms": 1250,
                    "ai_expected": False,
                },
                "min_executable_notional": 5.0,
                "reference_price": 100.1,
            },
        )

    def test_zero_max_hold_disables_micro_grid_time_exit_but_keeps_limit_wait(self):
        setup = micro_grid_setup_from_candidate(
            self.candidate(max_hold_seconds=0, order_wait_seconds=30),
            risk_limits=self.risk_limits(),
            notional_fraction=1.0,
            order_type="LIMIT",
        )

        self.assertEqual(setup.decision, "trade")
        self.assertIsNone(setup.hold_time_minutes)
        self.assertIn("micro_grid_time_exit_disabled", setup.reasons)
        self.assertIn("limit_entry_max_wait_seconds:30", setup.reasons)
        self.assertEqual(setup.price_basis["entry_basis"]["limit_entry_max_wait_seconds"], 30)
        self.assertEqual(setup.price_basis["latency"]["signal_to_candidate_ms"], 1250)

    def test_positive_max_hold_still_generates_hold_time_without_clipping_limit_wait(self):
        setup = micro_grid_setup_from_candidate(
            self.candidate(max_hold_seconds=75, order_wait_seconds=90),
            risk_limits=self.risk_limits(),
            notional_fraction=1.0,
            order_type="LIMIT",
        )

        self.assertEqual(setup.hold_time_minutes, 2)
        self.assertIn("micro_grid_time_exit_enabled", setup.reasons)
        self.assertIn("limit_entry_max_wait_seconds:90", setup.reasons)

    def test_config_zero_max_hold_uses_separate_model_horizon(self):
        config = load_config(
            {
                "BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS": "0",
                "BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS": "180",
                "BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS": "30",
            }
        )

        live_config = MicroGridLiveConfig.from_app(config)

        self.assertIsNone(live_config.max_hold_seconds)
        self.assertEqual(live_config.model_horizon_seconds, 180)
        self.assertEqual(live_config.order_wait_seconds, 30)

    def test_default_order_wait_is_twenty_seconds_for_fast_lane_scalps(self):
        live_config = MicroGridLiveConfig.from_app(load_config(env={}))

        self.assertEqual(live_config.order_wait_seconds, 20)


if __name__ == "__main__":
    unittest.main()
