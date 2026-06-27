import unittest
from dataclasses import replace

from bfa.ai.schema import RiskLimits
from bfa.config import load_config
from bfa.strategy.candidates import CandidateSignal
from bfa.strategy.micro_grid_live import (
    MicroGridLiveConfig,
    _candidate_from_order,
    _live_profile,
    _market_context_rejections,
    _order_score,
    micro_grid_setup_from_candidate,
)

from scripts import run_micro_grid_research as research


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
                "quote_volume": 25_000_000.0,
                "min_executable_notional": 5.0,
                "micro_grid_latency": {
                    "source": "micro_grid_live",
                    "signal_time_ms": 1_700_000_000_000,
                    "candidate_generated_at_ms": 1_700_000_001_250,
                    "signal_to_candidate_ms": 1250,
                    "ai_expected": False,
                },
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
        self.assertEqual(live_config.max_signal_age_seconds, 12.0)

    def test_live_profile_is_sensitive_to_wick_scalp_signals(self):
        live_config = MicroGridLiveConfig.from_app(
            load_config(
                env={
                    "BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS": "20",
                    "BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS": "180",
                }
            )
        )

        profile = _live_profile(research, live_config)

        self.assertEqual(profile.order_wait_seconds, 20)
        self.assertEqual(profile.min_turn_count, 3)
        self.assertEqual(profile.min_edge_alternations, 2)
        self.assertAlmostEqual(profile.min_reversal_response_rate, 0.38)
        self.assertAlmostEqual(profile.max_drift_to_width, 1.15)
        self.assertAlmostEqual(profile.min_width_cost_ratio, 1.55)
        self.assertAlmostEqual(profile.min_wick_opportunity_percent, 0.55)

    def test_config_reads_micro_grid_max_signal_age(self):
        live_config = MicroGridLiveConfig.from_app(
            load_config(env={"BFA_LIVE_MICRO_GRID_MAX_SIGNAL_AGE_SECONDS": "9"})
        )

        self.assertEqual(live_config.max_signal_age_seconds, 9.0)

    def micro_state(self, *, close_position_percent: float, long_ready: bool, short_ready: bool):
        return research.MicroGridState(
            signal_index=100,
            signal_time="2026-06-24T00:00:00Z",
            center_price=100.0,
            projected_center_price=100.0,
            lower_price=99.0,
            upper_price=101.0,
            width_percent=2.0,
            close_position_percent=close_position_percent,
            center_cross_count=4,
            turn_count=5,
            lower_touch_count=2,
            upper_touch_count=2,
            edge_alternation_count=3,
            reversal_response_rate=0.6,
            path_efficiency=0.25,
            drift_percent=0.0,
            drift_to_width=0.0,
            recent_path_efficiency=0.2,
            recent_drift_percent=0.0,
            recent_drift_to_width=0.0,
            amplitude_percent=1.0,
            score=1.0,
            trend_pause=False,
            trend_direction=None,
            current_price=99.2 if close_position_percent <= 30 else 100.8 if close_position_percent >= 70 else 100.0,
            instantaneous_vol_percent=0.08,
            long_reversal_ready=long_ready,
            short_reversal_ready=short_ready,
            long_reversal_reason="ok" if long_ready else "not_edge",
            short_reversal_reason="ok" if short_ready else "not_edge",
            long_entry_reversal_fraction=0.42 if long_ready else 0.05,
            short_entry_reversal_fraction=0.42 if short_ready else 0.05,
            long_entry_continuation_fraction=0.02 if long_ready else 0.28,
            short_entry_continuation_fraction=0.02 if short_ready else 0.28,
            triple_ema_mid=100.0,
            triple_ema_slow=100.0,
            long_pullback_quality=0.85 if long_ready else 0.1,
            short_pullback_quality=0.85 if short_ready else 0.1,
        )

    def grid_order(self, *, side: str, state):
        entry = 99.1 if side == "long" else 100.9
        return research.GridOrder(
            symbol="TESTUSDT",
            side=side,
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=entry,
            stop_price=98.7 if side == "long" else 101.3,
            target_price=100.0 if side == "long" else 100.0,
            state=state,
            reason_codes=[
                "signal_mode:micro_smart_grid",
                f"edge_reversal_ready:{state.long_reversal_ready if side == 'long' else state.short_reversal_ready}",
                f"entry_reversal_fraction:{state.long_entry_reversal_fraction if side == 'long' else state.short_entry_reversal_fraction}",
                f"entry_continuation_fraction:{state.long_entry_continuation_fraction if side == 'long' else state.short_entry_continuation_fraction}",
                f"long_pullback_quality:{state.long_pullback_quality}",
                f"short_pullback_quality:{state.short_pullback_quality}",
                "wick_success_rate:0.45",
                "wick_score:0.4",
                "net_notional_reward_percent:0.12",
                "basket_size_weight:0.75",
                "entry_edge_fraction:-0.08",
                "stop_span_fraction:0.24",
            ],
            max_hold_seconds=180,
            size_weight=1.0,
        )

    def test_live_score_prefers_short_at_upper_edge_wick_reversal(self):
        state = self.micro_state(close_position_percent=94.0, long_ready=False, short_ready=True)

        long_score = _order_score(self.grid_order(side="long", state=state), research)
        short_score = _order_score(self.grid_order(side="short", state=state), research)

        self.assertGreater(short_score, long_score + 3.0)

    def test_live_score_prefers_long_at_lower_edge_wick_reversal(self):
        state = self.micro_state(close_position_percent=6.0, long_ready=True, short_ready=False)

        long_score = _order_score(self.grid_order(side="long", state=state), research)
        short_score = _order_score(self.grid_order(side="short", state=state), research)

        self.assertGreater(long_score, short_score + 3.0)

    def test_live_score_penalizes_opposite_ready_side_even_when_raw_reward_matches(self):
        state = self.micro_state(close_position_percent=24.0, long_ready=True, short_ready=False)
        short_order = replace(
            self.grid_order(side="short", state=state),
            reason_codes=[
                code
                if not code.startswith("net_notional_reward_percent:")
                else "net_notional_reward_percent:2.0"
                for code in self.grid_order(side="short", state=state).reason_codes
            ],
        )

        long_score = _order_score(self.grid_order(side="long", state=state), research)
        short_score = _order_score(short_order, research)

        self.assertGreater(long_score, short_score)

    def test_micro_grid_market_context_missing_rejects_instead_of_faking_liquidity(self):
        self.assertEqual(_market_context_rejections({}), ["micro_grid_missing_market_context"])
        self.assertEqual(
            _market_context_rejections({"quote_volume": 25_000_000.0}),
            ["micro_grid_missing_min_executable_notional"],
        )

    def test_candidate_from_order_uses_real_market_context_without_score_offset(self):
        state = self.micro_state(close_position_percent=6.0, long_ready=True, short_ready=False)
        order = self.grid_order(side="long", state=state)

        candidate = _candidate_from_order(
            order,
            generated_at="2026-06-24T00:00:01Z",
            score=4.2,
            quality_scale=0.91,
            quality_reasons=["quality_ok"],
            max_position_notional_usdt=200.0,
            live_config=MicroGridLiveConfig.from_app(load_config(env={"BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS": "0"})),
            cache_updated_at_ms=1_700_000_000_000,
            market_context={
                "quote_volume": 12_345_678.0,
                "min_executable_notional": 6.25,
                "min_executable_notional_source": "exchange_symbol",
                "funding_rate": "0.0001",
                "taker_buy_sell_ratio": "1.23",
                "open_interest_value": "9000000",
            },
        )

        self.assertEqual(candidate.score, 4.2)
        self.assertEqual(candidate.market_score, 4.2)
        self.assertEqual(candidate.features["quote_volume"], 12_345_678.0)
        self.assertEqual(candidate.features["min_executable_notional"], 6.25)
        self.assertEqual(candidate.features["min_executable_notional_source"], "exchange_symbol")
        self.assertNotIn("missing_quote_volume", candidate.data_quality_notes)
        self.assertNotIn("missing_min_executable_notional", candidate.data_quality_notes)


if __name__ == "__main__":
    unittest.main()
