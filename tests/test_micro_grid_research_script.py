import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from bfa.backtest.models import BacktestBar


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_micro_grid_research.py"
SPEC = importlib.util.spec_from_file_location("micro_grid_research", SCRIPT_PATH)
research = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)


BASE_MS = 1_700_000_000_000


def bar(symbol, index, *, open_price, high, low, close, quote_volume=100_000):
    open_time = BASE_MS + index * 1_000
    return BacktestBar(
        symbol=symbol,
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1_000,
        close_time=open_time + 999,
        quote_volume=quote_volume,
        taker_buy_quote_volume=quote_volume / 2,
    )


def oscillating_seconds(symbol="TESTUSDT", count=120):
    closes = [1.11, 1.145, 1.03, 1.16, 0.999, 1.12, 1.15, 1.02, 1.155, 1.00, 1.13, 1.16, 1.01, 1.145, 1.00, 1.12]
    bars = []
    for index in range(count):
        close = closes[index % len(closes)]
        open_price = closes[(index - 1) % len(closes)] if index else close
        bars.append(
            bar(
                symbol,
                index,
                open_price=open_price,
                high=max(open_price, close) * 1.004,
                low=min(open_price, close) * 0.996,
                close=close,
            )
        )
    return bars


def trend_seconds(symbol="TESTUSDT", count=120):
    return [
        bar(
            symbol,
            index,
            open_price=1.0 + index * 0.002,
            high=(1.0 + index * 0.002) * 1.001,
            low=(1.0 + index * 0.002) * 0.999,
            close=1.0 + index * 0.002,
        )
        for index in range(count)
    ]


def wick_training_seconds(symbol="TESTUSDT", count=120):
    bars = []
    for index in range(count):
        if index % 12 in {2, 8}:
            bars.append(bar(symbol, index, open_price=100.6, high=101.2, low=98.6, close=100.4))
        elif index % 12 in {5, 11}:
            bars.append(bar(symbol, index, open_price=99.4, high=101.4, low=98.9, close=99.7))
        else:
            close = 100.0 + (0.18 if index % 2 else -0.18)
            bars.append(bar(symbol, index, open_price=100.0, high=100.8, low=99.2, close=close))
    return bars


def pullback_low_recovery_seconds(symbol="TESTUSDT", count=120):
    bars = []
    for index in range(count):
        cycle = index % 20
        if cycle < 10:
            close = 101.0 - cycle * 0.22
        elif cycle < 15:
            close = 98.8 + (cycle - 10) * 0.08
        else:
            close = 99.2 + (cycle - 15) * 0.25
        open_price = bars[-1].close if bars else close
        bars.append(bar(symbol, index, open_price=open_price, high=max(open_price, close) + 0.12, low=min(open_price, close) - 0.28, close=close))
    return bars


def pullback_high_rejection_seconds(symbol="TESTUSDT", count=120):
    bars = []
    for index in range(count):
        cycle = index % 20
        if cycle < 10:
            close = 99.0 + cycle * 0.22
        elif cycle < 15:
            close = 101.2 - (cycle - 10) * 0.08
        else:
            close = 100.8 - (cycle - 15) * 0.25
        open_price = bars[-1].close if bars else close
        bars.append(bar(symbol, index, open_price=open_price, high=max(open_price, close) + 0.28, low=min(open_price, close) - 0.12, close=close))
    return bars


def tick_stream(symbol, pairs):
    ticks = [
        research.AggTradeTick(
            symbol=symbol,
            time_ms=BASE_MS + item[0],
            price=item[1],
            quantity=1.0,
            buyer_maker=item[2] if len(item) > 2 else True,
        )
        for item in pairs
    ]
    return research.TickStream(ticks=ticks, time_ms=[tick.time_ms for tick in ticks])


class MicroGridResearchScriptTests(unittest.TestCase):
    def test_tick_iso_round_trip_preserves_millisecond_ordering(self):
        value = BASE_MS + 5_123

        self.assertEqual(research.parse_iso_ms(research.ms_to_iso(value)), value)

    def test_intraday_signal_bounds_keep_history_but_limit_candidate_scan(self):
        seconds = oscillating_seconds(count=200)
        profile = self.profile(
            structure_lookback_seconds=80,
            band_lookback_seconds=80,
            entry_lookback_seconds=30,
            order_wait_seconds=10,
            max_hold_seconds=20,
        )

        start, end = research.signal_scan_bounds(
            seconds,
            profile,
            signal_start_ms=BASE_MS + 120_000,
            signal_end_ms=BASE_MS + 150_000,
        )

        self.assertEqual(start, 120)
        self.assertEqual(end, 151)
        self.assertGreaterEqual(start, profile.required_history_seconds)

    def test_scalp_confirmation_requires_stoch_extreme_and_non_adverse_flow(self):
        profile = self.profile(
            scalp_confirmation_enabled=True,
            scalp_confirmation_min_stoch_distance=30.0,
            scalp_confirmation_dynamic_buffer=0.0,
            scalp_confirmation_max_adverse_flow=0.18,
        )
        long_ok = research.scalp_confirmation_diagnostics(
            "long",
            replace(
                self.state(),
                stochastic_k=18.0,
                stochastic_d=19.0,
                entry_taker_buy_ratio=0.40,
            ),
            profile,
        )
        long_bad_d = research.scalp_confirmation_diagnostics(
            "long",
            replace(
                self.state(),
                stochastic_k=18.0,
                stochastic_d=24.0,
                entry_taker_buy_ratio=0.40,
            ),
            profile,
        )
        long_bad_flow = research.scalp_confirmation_diagnostics(
            "long",
            replace(
                self.state(),
                stochastic_k=18.0,
                stochastic_d=19.0,
                entry_taker_buy_ratio=0.20,
            ),
            profile,
        )
        short_ok = research.scalp_confirmation_diagnostics(
            "short",
            replace(
                self.state(),
                stochastic_k=82.0,
                stochastic_d=81.0,
                entry_taker_buy_ratio=0.60,
            ),
            profile,
        )

        self.assertTrue(long_ok["passed"])
        self.assertFalse(long_bad_d["passed"])
        self.assertIn("stoch_not_extreme", long_bad_d["reasons"])
        self.assertFalse(long_bad_flow["passed"])
        self.assertIn("adverse_flow_extreme", long_bad_flow["reasons"])
        self.assertTrue(short_ok["passed"])

    def test_scalp_confirmation_dynamically_requires_more_extreme_signal_in_adverse_trend(self):
        profile = self.profile(
            scalp_confirmation_enabled=True,
            scalp_confirmation_min_stoch_distance=30.0,
            scalp_confirmation_dynamic_buffer=6.0,
        )
        neutral = research.scalp_confirmation_diagnostics(
            "long",
            replace(self.state(), triple_ema_bias=0.0, instantaneous_vol_percent=0.05),
            profile,
        )
        adverse = research.scalp_confirmation_diagnostics(
            "long",
            replace(self.state(), triple_ema_bias=-0.7, instantaneous_vol_percent=0.25),
            profile,
        )

        self.assertGreater(adverse["required_stoch_distance"], neutral["required_stoch_distance"])
        self.assertLess(adverse["max_adverse_flow"], neutral["max_adverse_flow"])

    def test_scalp_confirmation_rejects_mature_wick_model_with_high_stop_rate(self):
        profile = self.profile(
            scalp_confirmation_enabled=True,
            scalp_confirmation_min_stoch_distance=0.0,
            scalp_confirmation_dynamic_buffer=0.0,
            scalp_confirmation_max_adverse_flow=0.5,
            scalp_confirmation_max_wick_stop_rate=0.30,
            wick_ev_min_fills=12,
        )
        rejected = research.scalp_confirmation_diagnostics(
            "long",
            replace(
                self.state(),
                long_wick_fill_count=20,
                long_wick_stop_rate=0.35,
            ),
            profile,
        )
        warming_up = research.scalp_confirmation_diagnostics(
            "long",
            replace(
                self.state(),
                long_wick_fill_count=8,
                long_wick_stop_rate=0.50,
            ),
            profile,
        )

        self.assertFalse(rejected["passed"])
        self.assertIn("historical_wick_stop_rate_high", rejected["reasons"])
        self.assertTrue(warming_up["passed"])

    def test_maker_accurate_cost_includes_entry_exit_slippage_and_taker_risk(self):
        profile = self.profile(
            maker_fee_bps=2.0,
            taker_fee_bps=4.0,
            exit_slippage_bps=1.0,
            entry_maker_cost=True,
            entry_taker_risk_bps=0.5,
        )

        self.assertAlmostEqual(profile.round_trip_cost_percent, 0.075)

    def test_estimated_target_reward_uses_same_maker_accurate_cost_model(self):
        profile = self.profile(
            maker_fee_bps=2.0,
            taker_fee_bps=4.0,
            exit_slippage_bps=1.0,
            entry_maker_cost=True,
            entry_taker_risk_bps=0.5,
            target_net_filter_notional_usdt=120.0,
        )

        self.assertAlmostEqual(research.estimated_target_net_reward_usdt(0.10, profile), 0.03)

    def test_confirmation_prefilter_skips_wick_fit_when_both_sides_fail(self):
        seconds = oscillating_seconds(count=140)
        profile = self.profile(
            scalp_confirmation_enabled=True,
            scalp_confirmation_min_stoch_distance=49.0,
            scalp_confirmation_dynamic_buffer=0.0,
        )

        with mock.patch.object(research, "fit_dynamic_wick_model", wraps=research.fit_dynamic_wick_model) as fit:
            state, reasons = research.build_micro_grid_state(seconds, 100, profile)

        self.assertIsNone(state)
        self.assertTrue(any("scalp_confirmation" in reason for reason in reasons))
        fit.assert_not_called()

    def test_order_builder_evaluates_confirmation_once_per_side(self):
        seconds = oscillating_seconds(count=140)
        profile = self.profile(grid_layer_count=3)
        state, reasons = research.build_micro_grid_state(seconds, 100, profile)
        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)

        with mock.patch.object(
            research,
            "scalp_confirmation_diagnostics",
            wraps=research.scalp_confirmation_diagnostics,
        ) as confirmation:
            orders = research.build_grid_orders("TESTUSDT", state, profile)

        self.assertTrue(orders)
        self.assertEqual(confirmation.call_count, 2)

    def test_passive_limit_requires_matching_aggressor_direction(self):
        state = self.state()
        long_order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=99.0,
            target_price=101.0,
            state=state,
            reason_codes=[],
        )
        short_order = research.GridOrder(
            symbol="TESTUSDT",
            side="short",
            signal_index=0,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=101.0,
            target_price=99.0,
            state=state,
            reason_codes=[],
        )
        ticks = tick_stream(
            "TESTUSDT",
            [
                (100, 99.9, False),
                (200, 100.1, True),
                (300, 99.8, True),
                (400, 100.2, False),
            ],
        )

        long_fill = research.find_fill_tick_position(ticks, long_order, start_ms=BASE_MS, end_ms=BASE_MS + 1_000)
        short_fill = research.find_fill_tick_position(ticks, short_order, start_ms=BASE_MS, end_ms=BASE_MS + 1_000)

        self.assertEqual(long_fill, 2)
        self.assertEqual(short_fill, 3)

    def test_pending_quality_cancels_before_fill_on_adverse_flow_volume_and_acceptance(self):
        seconds = self.pending_quality_seconds(expanding_volume=True)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream("TESTUSDT", [(45_000, 98.5, True), (46_000, 101.1, False)])

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                pending_quality_enabled=True,
                pending_quality_min_age_seconds=5,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertIsNone(trade)
        self.assertEqual(status, "quality_canceled")

    def test_pending_quality_keeps_order_without_volume_expansion(self):
        seconds = self.pending_quality_seconds(expanding_volume=False)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream("TESTUSDT", [(45_000, 98.5, True), (46_000, 101.1, False)])

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                pending_quality_enabled=True,
                pending_quality_min_age_seconds=5,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")

    def test_micro_absorption_mode_keeps_aligned_capitulation_flow(self):
        seconds = self.pending_quality_seconds(expanding_volume=True, post_signal_taker_buy_fraction=0.2)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream("TESTUSDT", [(45_000, 98.5, True), (46_000, 101.1, False)])

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                pending_quality_enabled=True,
                pending_quality_micro_absorption_mode=True,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "take_profit")

    def test_micro_absorption_mode_cancels_price_flow_divergence(self):
        seconds = self.pending_quality_seconds(expanding_volume=True, post_signal_taker_buy_fraction=0.8)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream("TESTUSDT", [(45_000, 98.5, True), (46_000, 101.1, False)])

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                pending_quality_enabled=True,
                pending_quality_micro_absorption_mode=True,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertIsNone(trade)
        self.assertEqual(status, "quality_canceled")

    def test_two_stage_scout_ignores_early_touch_then_activates_valid_order(self):
        seconds = self.pending_quality_seconds(expanding_volume=True, post_signal_taker_buy_fraction=0.2)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream(
            "TESTUSDT",
            [(40_000, 98.4, True), (45_000, 98.5, True), (46_000, 101.1, False)],
        )

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                entry_scout_enabled=True,
                entry_scout_seconds=15,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertGreaterEqual(research.parse_iso_ms(trade.entry_time), BASE_MS + 45_000)
        self.assertEqual(trade.exit_reason, "take_profit")

    def test_two_stage_scout_rejects_absorption_before_order_activation(self):
        seconds = self.pending_quality_seconds(expanding_volume=True, post_signal_taker_buy_fraction=0.8)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=98.5,
            stop_price=97.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream(
            "TESTUSDT",
            [(40_000, 98.4, True), (45_000, 98.5, True), (46_000, 101.1, False)],
        )

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                entry_scout_enabled=True,
                entry_scout_seconds=15,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertIsNone(trade)
        self.assertEqual(status, "scout_rejected")

    def test_reversal_scout_activates_only_after_favorable_five_second_return(self):
        seconds = self.reversal_scout_seconds(reverses=True)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=99.3,
            stop_price=98.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream(
            "TESTUSDT",
            [
                (34_000, 99.2, True),
                (35_000, 99.5, False),
                (36_000, 99.7, False),
                (37_000, 99.9, False),
                (40_000, 99.3, True),
                (41_000, 101.1, False),
            ],
        )

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                entry_scout_enabled=True,
                entry_scout_mode="reversal",
                entry_scout_seconds=5,
                entry_scout_reversal_return_percent=0.02,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertGreaterEqual(research.parse_iso_ms(trade.entry_time), BASE_MS + 40_000)
        self.assertEqual(trade.exit_reason, "take_profit")

    def test_reversal_scout_never_activates_without_price_reversal(self):
        seconds = self.reversal_scout_seconds(reverses=False)
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=30,
            signal_time=seconds[30].open_time_iso,
            entry_price=99.3,
            stop_price=98.0,
            target_price=101.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=20,
        )
        ticks = tick_stream(
            "TESTUSDT",
            [(34_000, 99.2, True), (40_000, 99.0, True), (49_000, 98.8, True)],
        )

        trade, status, _ = research.simulate_grid_basket(
            seconds,
            [order],
            self.profile(
                order_wait_seconds=20,
                entry_scout_enabled=True,
                entry_scout_mode="reversal",
                entry_scout_seconds=5,
                entry_scout_reversal_return_percent=0.02,
            ),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertIsNone(trade)
        self.assertEqual(status, "scout_not_activated")

    def test_wick_path_cannot_profit_before_entry_is_touched(self):
        path = [
            bar("TESTUSDT", 0, open_price=105, high=106, low=104, close=105),
            bar("TESTUSDT", 1, open_price=105, high=111, low=104, close=110),
        ]

        net = research._wick_path_net_percent("long", 100, 95, 110, path, 0.1)

        self.assertEqual(net, 0.0)

    def test_wick_path_evaluates_target_only_after_entry_fill(self):
        path = [
            bar("TESTUSDT", 0, open_price=105, high=106, low=104, close=105),
            bar("TESTUSDT", 1, open_price=101, high=102, low=99, close=100),
            bar("TESTUSDT", 2, open_price=100, high=111, low=99, close=110),
        ]

        net = research._wick_path_net_percent("long", 100, 95, 110, path, 0.1)

        self.assertAlmostEqual(net, 9.9)

    def test_wick_path_same_bar_fill_and_stop_is_stop_first(self):
        path = [
            bar("TESTUSDT", 0, open_price=105, high=106, low=104, close=105),
            bar("TESTUSDT", 1, open_price=101, high=111, low=94, close=100),
        ]

        net = research._wick_path_net_percent("long", 100, 95, 110, path, 0.1)

        self.assertAlmostEqual(net, -5.1)
    def profile(self, **overrides):
        values = {
            "structure_lookback_seconds": 80,
            "band_lookback_seconds": 80,
            "entry_lookback_seconds": 30,
            "signal_stride_seconds": 3,
            "order_wait_seconds": 18,
            "max_hold_seconds": 80,
            "maker_fee_bps": 0.0,
            "taker_fee_bps": 0.0,
            "exit_slippage_bps": 0.0,
        }
        values.update(overrides)
        return research.MicroGridProfile(**values)

    def state(self):
        return research.MicroGridState(
            signal_index=0,
            signal_time=bar("TESTUSDT", 0, open_price=100, high=100, low=100, close=100).open_time_iso,
            center_price=100,
            projected_center_price=100,
            lower_price=98,
            upper_price=102,
            width_percent=4,
            close_position_percent=50,
            center_cross_count=6,
            turn_count=8,
            lower_touch_count=3,
            upper_touch_count=3,
            edge_alternation_count=5,
            reversal_response_rate=1.0,
            path_efficiency=0.1,
            drift_percent=0.0,
            drift_to_width=0.0,
            recent_path_efficiency=0.1,
            recent_drift_percent=0.0,
            recent_drift_to_width=0.0,
            amplitude_percent=2.0,
            score=10.0,
            trend_pause=False,
            trend_direction=None,
        )

    def test_state_rejection_can_block_overheated_edge_response(self):
        state = self.state()

        relaxed = research.state_rejection_reasons(state, self.profile())
        strict = research.state_rejection_reasons(state, self.profile(max_reversal_response_rate=0.70))

        self.assertNotIn("overheated_edge_reversal_response", relaxed)
        self.assertIn("overheated_edge_reversal_response", strict)

    def test_target_progress_trailing_only_locks_after_mean_reversion_progress(self):
        state = self.state()
        long_order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            state=state,
            reason_codes=[],
            max_hold_seconds=120,
            size_weight=1.0,
        )

        disabled_stop = research.update_trailing_stop(
            long_order,
            self.profile(target_progress_trailing_enabled=False),
            best_price=103.0,
            current_stop=98.0,
        )
        enabled_stop = research.update_trailing_stop(
            long_order,
            self.profile(
                target_progress_trailing_enabled=True,
                target_progress_activate_fraction=0.65,
                target_progress_lock_fraction=0.22,
                target_progress_giveback_fraction=0.45,
            ),
            best_price=103.0,
            current_stop=98.0,
        )

        self.assertEqual(disabled_stop, 98.0)
        self.assertAlmostEqual(enabled_stop, 101.2)

    def test_target_progress_trailing_handles_short_side_symmetrically(self):
        state = self.state()
        short_order = research.GridOrder(
            symbol="TESTUSDT",
            side="short",
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=102.0,
            target_price=96.0,
            state=state,
            reason_codes=[],
            max_hold_seconds=120,
            size_weight=1.0,
        )

        stop = research.update_trailing_stop(
            short_order,
            self.profile(
                target_progress_trailing_enabled=True,
                target_progress_activate_fraction=0.65,
                target_progress_lock_fraction=0.22,
                target_progress_giveback_fraction=0.45,
            ),
            best_price=97.0,
            current_stop=102.0,
        )

        self.assertAlmostEqual(stop, 98.8)

    def test_adaptive_profit_lock_waits_longer_when_continuation_confidence_is_high(self):
        state = self.state()
        base = dict(
            symbol="TESTUSDT",
            side="long",
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            state=state,
            max_hold_seconds=120,
            size_weight=1.0,
        )
        low_confidence = research.GridOrder(
            **base,
            reason_codes=[
                "edge_reversal_ready:False",
                "entry_reversal_fraction:0.05",
                "entry_continuation_fraction:0.18",
                "wick_success_rate:0.2",
                "wick_score:0.2",
                "net_notional_reward_percent:0.2",
                "long_pullback_quality:0.1",
            ],
        )
        high_confidence = research.GridOrder(
            **base,
            reason_codes=[
                "edge_reversal_ready:True",
                "entry_reversal_fraction:0.35",
                "entry_continuation_fraction:0.0",
                "wick_success_rate:0.9",
                "wick_score:0.9",
                "net_notional_reward_percent:1.0",
                "long_pullback_quality:0.9",
            ],
        )
        profile = self.profile(adaptive_profit_lock_enabled=True)

        low_stop = research.update_trailing_stop(low_confidence, profile, best_price=103.0, current_stop=98.0)
        high_stop = research.update_trailing_stop(high_confidence, profile, best_price=103.0, current_stop=98.0)

        self.assertGreater(low_stop, 100.0)
        self.assertEqual(high_stop, 98.0)

    def test_adaptive_profit_lock_handles_short_side(self):
        state = self.state()
        short_order = research.GridOrder(
            symbol="TESTUSDT",
            side="short",
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=100.0,
            stop_price=102.0,
            target_price=96.0,
            state=state,
            reason_codes=[
                "edge_reversal_ready:False",
                "entry_reversal_fraction:0.05",
                "entry_continuation_fraction:0.18",
                "wick_success_rate:0.2",
                "wick_score:0.2",
                "net_notional_reward_percent:0.2",
                "short_pullback_quality:0.1",
            ],
            max_hold_seconds=120,
            size_weight=1.0,
        )

        stop = research.update_trailing_stop(
            short_order,
            self.profile(adaptive_profit_lock_enabled=True),
            best_price=97.0,
            current_stop=102.0,
        )

        self.assertLess(stop, 100.0)

    def test_micro_oscillation_state_creates_low_buy_and_high_short_orders(self):
        seconds = oscillating_seconds(count=120)
        profile = self.profile(wick_require_positive_ev=False)

        state, reasons = research.build_micro_grid_state(seconds, 80, profile)
        orders = research.build_grid_orders("TESTUSDT", state, profile) if state else []

        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)
        self.assertGreaterEqual(state.edge_alternation_count, 2)
        self.assertGreaterEqual(state.reversal_response_rate, 0.35)
        self.assertEqual({order.side for order in orders}, {"long", "short"})
        long_order = next(order for order in orders if order.side == "long")
        short_order = next(order for order in orders if order.side == "short")
        self.assertLess(long_order.entry_price, state.projected_center_price)
        self.assertGreater(short_order.entry_price, state.projected_center_price)
        self.assertLessEqual(research.edge_fraction_for_order("long", long_order.entry_price, state), profile.wick_max_entry_fraction)
        self.assertLessEqual(research.edge_fraction_for_order("short", short_order.entry_price, state), profile.wick_max_entry_fraction)

    def test_structure_window_does_not_pollute_current_band(self):
        old_wide = [
            bar(
                "TESTUSDT",
                index,
                open_price=100.0,
                high=130.0 if index % 2 else 101.0,
                low=70.0 if index % 2 else 99.0,
                close=100.0,
            )
            for index in range(40)
        ]
        recent_band = []
        pattern = [100.0, 101.8, 100.2, 101.6, 100.1, 101.7, 100.3, 101.5]
        for offset in range(80):
            index = 40 + offset
            close = pattern[offset % len(pattern)]
            open_price = pattern[(offset - 1) % len(pattern)]
            recent_band.append(
                bar(
                    "TESTUSDT",
                    index,
                    open_price=open_price,
                    high=max(open_price, close) + 0.05,
                    low=min(open_price, close) - 0.05,
                    close=close,
                )
            )
        seconds = old_wide + recent_band + [
            bar("TESTUSDT", 120, open_price=101.5, high=101.6, low=101.4, close=101.5)
        ]

        state, reasons = research.build_micro_grid_state(
            seconds,
            120,
            self.profile(
                structure_lookback_seconds=120,
                band_lookback_seconds=80,
                entry_lookback_seconds=30,
                min_width_percent=0.1,
                min_edge_alternations=0,
                min_reversal_response_rate=0.1,
                max_drift_to_width=2.0,
                wick_require_positive_ev=False,
            ),
        )
        recent_band_snapshot = research.build_band_snapshot(recent_band, self.profile(band_lookback_seconds=80))

        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)
        self.assertIsNotNone(recent_band_snapshot)
        self.assertAlmostEqual(state.lower_price, recent_band_snapshot.lower, places=9)
        self.assertAlmostEqual(state.upper_price, recent_band_snapshot.upper, places=9)
        self.assertLess(state.upper_price - state.lower_price, 5.0)

    def test_wick_opportunity_expands_band_when_tail_range_is_large(self):
        steady = [
            bar(
                "TESTUSDT",
                index,
                open_price=100.0,
                high=100.08,
                low=99.92,
                close=100.0,
            )
            for index in range(80)
        ]
        tail = [
            bar("TESTUSDT", 80, open_price=100.0, high=101.4, low=99.9, close=100.4),
            bar("TESTUSDT", 81, open_price=100.4, high=100.1, low=98.6, close=99.7),
            bar("TESTUSDT", 82, open_price=99.7, high=101.2, low=99.8, close=100.5),
            bar("TESTUSDT", 83, open_price=100.5, high=100.2, low=98.8, close=99.9),
        ]
        window = steady + tail
        disabled = research.build_band_snapshot(
            window,
            self.profile(
                band_lookback_seconds=80,
                wick_opportunity_enabled=False,
            ),
        )
        enabled = research.build_band_snapshot(
            window,
            self.profile(
                band_lookback_seconds=80,
                wick_opportunity_enabled=True,
                min_wick_opportunity_percent=0.75,
                min_wick_to_stable_width_ratio=1.2,
            ),
        )

        self.assertIsNotNone(disabled)
        self.assertIsNotNone(enabled)
        self.assertFalse(disabled.wick_opportunity)
        self.assertTrue(enabled.wick_opportunity)
        self.assertGreater(enabled.width_percent, disabled.width_percent)
        self.assertGreater(enabled.wick_tail_range_percent, enabled.stable_width_percent)

    def test_dynamic_wick_model_moves_entry_toward_learned_wick_depth(self):
        seconds = wick_training_seconds(count=120)

        state, reasons = research.build_micro_grid_state(
            seconds,
            80,
            self.profile(
                min_width_percent=0.1,
                min_edge_alternations=1,
                min_reversal_response_rate=0.1,
                max_drift_to_width=2.0,
                wick_min_samples=2,
                wick_entry_quantile=30.0,
            ),
        )
        # The grid-order profile relaxes the EV statistical gates and disables
        # walk-forward validation so the synthetic 120-second training window
        # can still produce an EV model; this test exercises the EV
        # entry-placement behavior, not the (tightened) overfit controls.
        orders = (
            research.build_grid_orders(
                "TESTUSDT",
                state,
                self.profile(
                    wick_ev_min_fills=2,
                    wick_ev_confidence_z=0.0,
                    wick_ev_walk_forward_enabled=False,
                    spike_depth_entry_enabled=False,
                    wick_min_samples=2,
                ),
            )
            if state
            else []
        )

        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)
        self.assertGreater(state.long_wick_sample_count, 0)
        long_order = next(order for order in orders if order.side == "long")
        self.assertGreaterEqual(
            research.edge_fraction_for_order("long", long_order.entry_price, state),
            self.profile().wick_ev_min_entry_edge_fraction,
        )
        self.assertTrue(any(code.startswith("wick_sample_count:") for code in long_order.reason_codes))

    def test_edge_reversal_readiness_blocks_one_way_breakdown(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100 - index * 0.1, high=100 - index * 0.1, low=99.9 - index * 0.3, close=99.8 - index * 0.3)
            for index in range(20)
        ]

        long_ready, short_ready = research.edge_reversal_readiness(seconds, lower=94.0, upper=102.0, profile=self.profile())

        self.assertFalse(long_ready)
        self.assertFalse(short_ready)

    def test_edge_touch_response_uses_wick_success_fraction_not_full_target(self):
        window = [
            bar("TESTUSDT", 0, open_price=100.0, high=100.1, low=99.8, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=100.2, low=98.4, close=98.7),
            bar("TESTUSDT", 2, open_price=98.7, high=99.6, low=98.6, close=99.4),
            bar("TESTUSDT", 3, open_price=99.4, high=99.8, low=99.3, close=99.7),
        ]

        lower_touches, upper_touches, alternations, response_rate = research.edge_touch_stats(
            window,
            lower=98.0,
            upper=102.0,
            profile=self.profile(
                edge_response_seconds=3,
                edge_zone_fraction=0.16,
                edge_response_fraction=0.22,
                wick_success_fraction=0.22,
                target_fraction=0.76,
            ),
        )

        self.assertEqual(lower_touches, 1)
        self.assertEqual(upper_touches, 0)
        self.assertEqual(alternations, 0)
        self.assertEqual(response_rate, 1.0)

    def test_edge_touch_response_rejects_adverse_break_before_rebound(self):
        window = [
            bar("TESTUSDT", 0, open_price=100.0, high=100.1, low=98.5, close=98.8),
            bar("TESTUSDT", 1, open_price=98.8, high=99.0, low=97.4, close=97.8),
            bar("TESTUSDT", 2, open_price=97.8, high=99.8, low=97.7, close=99.6),
        ]

        lower_touches, upper_touches, alternations, response_rate = research.edge_touch_stats(
            window,
            lower=98.0,
            upper=102.0,
            profile=self.profile(
                edge_response_seconds=3,
                edge_zone_fraction=0.16,
                edge_response_fraction=0.22,
                edge_response_max_adverse_fraction=0.12,
            ),
        )

        self.assertEqual(lower_touches, 1)
        self.assertEqual(upper_touches, 0)
        self.assertEqual(alternations, 0)
        self.assertEqual(response_rate, 0.0)

    def test_triple_ema_stochastic_pullback_scores_low_recovery_for_long(self):
        seconds = pullback_low_recovery_seconds(count=120)
        profile = self.profile(
            min_width_percent=0.1,
            min_edge_alternations=0,
            min_reversal_response_rate=0.1,
            max_drift_to_width=2.0,
            wick_require_positive_ev=False,
        )

        state, reasons = research.build_micro_grid_state(seconds, 100, profile)
        orders = research.build_grid_orders("TESTUSDT", state, profile) if state else []

        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)
        self.assertEqual(state.pullback_model_reason, "ok")
        self.assertGreater(state.long_pullback_quality, state.short_pullback_quality)
        self.assertTrue(any(code.startswith("triple_ema_bias:") for code in orders[0].reason_codes))
        self.assertTrue(any(code.startswith("stochastic_k:") for code in orders[0].reason_codes))

    def test_triple_ema_stochastic_pullback_scores_high_rejection_for_short(self):
        seconds = pullback_high_rejection_seconds(count=120)
        profile = self.profile(
            min_width_percent=0.1,
            min_edge_alternations=0,
            min_reversal_response_rate=0.1,
            max_drift_to_width=2.0,
            wick_require_positive_ev=False,
        )

        state, reasons = research.build_micro_grid_state(seconds, 100, profile)

        self.assertEqual(reasons, [])
        self.assertIsNotNone(state)
        self.assertEqual(state.pullback_model_reason, "ok")
        self.assertGreater(state.short_pullback_quality, state.long_pullback_quality)

    def test_pullback_model_softens_entry_depth_without_default_hard_filter(self):
        state = self.state()
        shallow_quality_state = research.replace(
            state,
            current_price=100.0,
            long_entry_edge_fraction=0.28,
            long_pullback_quality=0.0,
            short_pullback_quality=1.0,
            pullback_model_reason="ok",
        )
        disabled_profile = self.profile(wick_require_positive_ev=False, pullback_model_enabled=False, grid_layer_count=1)
        enabled_profile = self.profile(
            wick_require_positive_ev=False,
            pullback_model_enabled=True,
            pullback_min_quality=0.0,
            pullback_entry_shift_fraction=0.08,
            pullback_min_size_multiplier=0.35,
            grid_layer_count=1,
        )

        disabled_long = next(order for order in research.build_grid_orders("TESTUSDT", shallow_quality_state, disabled_profile) if order.side == "long")
        enabled_long = next(order for order in research.build_grid_orders("TESTUSDT", shallow_quality_state, enabled_profile) if order.side == "long")
        enabled_short = next(order for order in research.build_grid_orders("TESTUSDT", shallow_quality_state, enabled_profile) if order.side == "short")

        self.assertLess(enabled_long.entry_price, disabled_long.entry_price)
        self.assertAlmostEqual(enabled_long.size_weight, 0.35)
        self.assertAlmostEqual(enabled_short.size_weight, 1.0)
        self.assertTrue(any(code.startswith("long_pullback_quality:") for code in enabled_long.reason_codes))
        self.assertTrue(any(code == "pullback_size_multiplier:0.35" for code in enabled_long.reason_codes))

    def test_dynamic_level_planner_moves_entry_deeper_when_volatility_is_high(self):
        state = research.replace(
            self.state(),
            width_percent=1.0,
            instantaneous_vol_percent=0.12,
            bollinger_width_percent=1.5,
            long_pullback_quality=0.1,
            long_wick_success_rate=0.35,
            long_wick_score=0.2,
            long_reversal_ready=False,
            long_entry_continuation_fraction=0.18,
            drift_to_width=0.9,
            recent_drift_to_width=0.8,
        )

        plan = research.dynamic_level_plan(
            "long",
            state,
            self.profile(dynamic_level_planner_enabled=True),
            base_entry_edge_fraction=0.12,
            base_stop_fraction=0.20,
            base_target_fraction=0.35,
            base_hold_seconds=180,
        )

        self.assertLess(plan.entry_edge_fraction, 0.12)
        self.assertEqual(plan.mode, "wrong_direction_fast_exit")
        self.assertTrue(any(code.startswith("planner_vol_fraction:") for code in plan.reason_codes))

    def test_dynamic_level_planner_marks_wrong_direction_fast_exit(self):
        state = research.replace(
            self.state(),
            width_percent=0.8,
            instantaneous_vol_percent=0.08,
            long_pullback_quality=0.1,
            long_reversal_ready=False,
            long_entry_continuation_fraction=0.30,
            drift_to_width=1.2,
            recent_drift_to_width=1.0,
            long_wick_stop_rate=0.4,
            long_wick_same_bar_stop_rate=0.2,
        )

        plan = research.dynamic_level_plan(
            "long",
            state,
            self.profile(dynamic_level_planner_enabled=True, max_drift_to_width=0.6),
            base_entry_edge_fraction=0.08,
            base_stop_fraction=0.24,
            base_target_fraction=0.45,
            base_hold_seconds=240,
        )

        self.assertEqual(plan.mode, "wrong_direction_fast_exit")
        self.assertLess(plan.hold_seconds, 240)
        self.assertLess(plan.trailing_activate_fraction, self.profile().trailing_activate_fraction)

    def test_wick_candidate_labels_stop_then_recovery(self):
        path = [
            bar("TESTUSDT", 0, open_price=100.2, high=100.3, low=100.0, close=100.1),
            bar("TESTUSDT", 1, open_price=100.1, high=100.2, low=98.8, close=99.0),
            bar("TESTUSDT", 2, open_price=99.0, high=100.4, low=98.9, close=100.2),
            bar("TESTUSDT", 3, open_price=100.2, high=102.2, low=100.1, close=102.0),
        ]

        outcome = research.simulate_wick_candidate_path(
            "long",
            path,
            self.profile(max_hold_seconds=4, post_stop_lookahead_seconds=3),
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
        )

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["exit_reason"], "stop_loss")
        self.assertTrue(outcome["recovered_to_entry"])
        self.assertTrue(outcome["recovered_to_target"])
        self.assertFalse(outcome["true_wrong_direction"])

    def test_wick_candidate_labels_true_wrong_direction(self):
        path = [
            bar("TESTUSDT", 0, open_price=100.2, high=100.3, low=100.0, close=100.1),
            bar("TESTUSDT", 1, open_price=100.1, high=100.2, low=98.8, close=99.0),
            bar("TESTUSDT", 2, open_price=99.0, high=99.2, low=98.2, close=98.4),
            bar("TESTUSDT", 3, open_price=98.4, high=98.7, low=97.9, close=98.0),
        ]

        outcome = research.simulate_wick_candidate_path(
            "long",
            path,
            self.profile(max_hold_seconds=4, post_stop_lookahead_seconds=3),
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
        )

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["exit_reason"], "stop_loss")
        self.assertFalse(outcome["recovered_to_entry"])
        self.assertTrue(outcome["true_wrong_direction"])

    def test_dynamic_level_planner_uses_history_to_allow_recovery(self):
        state = research.replace(
            self.state(),
            width_percent=1.0,
            instantaneous_vol_percent=0.10,
            long_pullback_quality=0.45,
            long_reversal_ready=True,
            long_entry_reversal_fraction=0.25,
            long_entry_continuation_fraction=0.03,
            long_wick_fill_count=18,
            long_wick_win_rate=0.38,
            long_wick_stop_rate=0.45,
            long_wick_recovery_rate=0.78,
            long_wick_stop_then_target_rate=0.35,
            long_wick_true_wrong_rate=0.12,
        )

        plan = research.dynamic_level_plan(
            "long",
            state,
            self.profile(dynamic_level_planner_enabled=True, planner_history_min_fills=3),
            base_entry_edge_fraction=0.12,
            base_stop_fraction=0.18,
            base_target_fraction=0.30,
            base_hold_seconds=180,
        )

        self.assertEqual(plan.mode, "recovery_allowed")
        self.assertLess(plan.entry_edge_fraction, 0.12)
        self.assertGreater(plan.stop_span_fraction, 0.18)
        self.assertTrue(any(code.startswith("planner_history_weight:") for code in plan.reason_codes))

    def test_dynamic_level_planner_reprices_without_widening_when_recovery_does_not_reach_target(self):
        state = research.replace(
            self.state(),
            width_percent=1.0,
            instantaneous_vol_percent=0.10,
            long_pullback_quality=0.45,
            long_reversal_ready=True,
            long_entry_reversal_fraction=0.25,
            long_entry_continuation_fraction=0.03,
            long_wick_fill_count=18,
            long_wick_win_rate=0.38,
            long_wick_stop_rate=0.45,
            long_wick_recovery_rate=0.78,
            long_wick_stop_then_target_rate=0.05,
            long_wick_true_wrong_rate=0.12,
        )

        plan = research.dynamic_level_plan(
            "long",
            state,
            self.profile(
                dynamic_level_planner_enabled=True,
                planner_history_min_fills=3,
                wick_min_entry_fraction=-0.18,
            ),
            base_entry_edge_fraction=0.12,
            base_stop_fraction=0.18,
            base_target_fraction=0.30,
            base_hold_seconds=180,
        )

        self.assertEqual(plan.mode, "reprice_only")
        self.assertLess(plan.entry_edge_fraction, 0.12)
        self.assertLessEqual(plan.stop_span_fraction, 0.20)
        self.assertTrue(any(code == "planner_historical_reprice_edge:True" for code in plan.reason_codes))

    def test_side_flow_filter_blocks_weak_short_against_strong_buy_flow(self):
        state = research.replace(
            self.state(),
            current_price=100.0,
            entry_taker_buy_ratio=0.72,
            long_pullback_quality=0.7,
            short_pullback_quality=0.35,
        )
        profile = self.profile(
            grid_layer_count=1,
            wick_require_positive_ev=False,
            side_flow_filter_enabled=True,
            side_flow_extreme_taker_ratio=0.64,
            side_flow_min_pullback_quality=0.58,
        )

        orders = research.build_grid_orders("TESTUSDT", state, profile)
        filtered, reasons = research.apply_side_flow_cooldowns(
            orders,
            state,
            profile,
            index=100,
            side_flow_block_until_index={"long": -1, "short": -1},
        )

        self.assertIn("long", {order.side for order in filtered})
        self.assertNotIn("short", {order.side for order in filtered})
        self.assertIn("short_side_flow_against_order", reasons)
        reasons = research.grid_price_or_reward_rejection_reasons(state, profile)
        self.assertIn("short_side_flow_against_order", reasons)

    def test_side_flow_filter_cools_down_same_side_after_block(self):
        profile = self.profile(
            grid_layer_count=1,
            wick_require_positive_ev=False,
            side_flow_filter_enabled=True,
            side_flow_extreme_taker_ratio=0.64,
            side_flow_min_pullback_quality=0.58,
            side_flow_block_cooldown_seconds=45,
            signal_stride_seconds=3,
        )
        blocked_state = research.replace(
            self.state(),
            current_price=100.0,
            entry_taker_buy_ratio=0.72,
            short_pullback_quality=0.35,
        )
        recovered_state = research.replace(
            self.state(),
            current_price=100.0,
            entry_taker_buy_ratio=0.50,
            short_pullback_quality=0.80,
        )
        cooldowns = {"long": -1, "short": -1}
        initial_orders = research.build_grid_orders("TESTUSDT", blocked_state, profile)
        _, first_reasons = research.apply_side_flow_cooldowns(initial_orders, blocked_state, profile, 100, cooldowns)
        next_orders = research.build_grid_orders("TESTUSDT", recovered_state, profile)
        filtered, second_reasons = research.apply_side_flow_cooldowns(next_orders, recovered_state, profile, 112, cooldowns)
        later_filtered, later_reasons = research.apply_side_flow_cooldowns(next_orders, recovered_state, profile, 148, cooldowns)

        self.assertIn("short_side_flow_against_order", first_reasons)
        self.assertNotIn("short", {order.side for order in filtered})
        self.assertIn("short_side_flow_cooldown", second_reasons)
        self.assertIn("short", {order.side for order in later_filtered})
        self.assertNotIn("short_side_flow_cooldown", later_reasons)

    def test_dynamic_level_planner_reason_codes_are_written_to_orders(self):
        state = research.replace(
            self.state(),
            current_price=100.0,
            width_percent=4.0,
            instantaneous_vol_percent=0.3,
            bollinger_width_percent=4.0,
            reservation_price=100.0,
            lower_price=98.0,
            upper_price=102.0,
            long_entry_edge_fraction=0.20,
            short_entry_edge_fraction=0.20,
            long_pullback_quality=0.8,
            short_pullback_quality=0.2,
            long_wick_success_rate=0.8,
            short_wick_success_rate=0.4,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(dynamic_level_planner_enabled=True, grid_layer_count=1, wick_require_positive_ev=False),
        )

        self.assertTrue(orders)
        self.assertTrue(any(code == "dynamic_level_planner_enabled:True" for code in orders[0].reason_codes))
        self.assertTrue(any(code.startswith("planner_mode:") for code in orders[0].reason_codes))

    def test_edge_reversal_readiness_allows_bounce_from_lower_edge(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=100.3, low=99.7, close=100.0)
            for index in range(16)
        ]
        seconds.extend(
            [
                bar("TESTUSDT", 16, open_price=100.0, high=100.1, low=98.05, close=98.4),
                bar("TESTUSDT", 17, open_price=98.4, high=98.9, low=98.2, close=98.8),
                bar("TESTUSDT", 18, open_price=98.8, high=99.2, low=98.7, close=99.1),
            ]
        )

        long_ready, short_ready = research.edge_reversal_readiness(seconds, lower=98.0, upper=102.0, profile=self.profile())

        self.assertTrue(long_ready)
        self.assertFalse(short_ready)

    def test_edge_reversal_readiness_blocks_fresh_upper_breakout(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0 + index * 0.12, high=100.2 + index * 0.12, low=99.9 + index * 0.12, close=100.1 + index * 0.12)
            for index in range(20)
        ]

        detail = research.edge_reversal_readiness_detail(seconds, lower=98.0, upper=102.0, profile=self.profile())

        self.assertFalse(detail["short_ready"])
        self.assertIn(detail["short_reason"], {"upper_extreme_too_fresh", "insufficient_upper_rejection", "upper_edge_still_breaking_up", "entry_path_too_directional"})

    def test_edge_reversal_readiness_allows_upper_rejection(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=100.3, low=99.7, close=100.0)
            for index in range(16)
        ]
        seconds.extend(
            [
                bar("TESTUSDT", 16, open_price=101.5, high=102.3, low=101.3, close=102.1),
                bar("TESTUSDT", 17, open_price=102.1, high=102.2, low=101.2, close=101.4),
                bar("TESTUSDT", 18, open_price=101.4, high=101.5, low=100.9, close=101.0),
            ]
        )

        long_ready, short_ready = research.edge_reversal_readiness(seconds, lower=98.0, upper=102.0, profile=self.profile())

        self.assertFalse(long_ready)
        self.assertTrue(short_ready)

    def test_grid_layers_stay_passive_and_deeper_from_current_price(self):
        state = research.MicroGridState(
            signal_index=0,
            signal_time=bar("TESTUSDT", 0, open_price=100, high=100, low=100, close=100).open_time_iso,
            center_price=100,
            projected_center_price=100,
            lower_price=98,
            upper_price=102,
            width_percent=4,
            close_position_percent=50,
            center_cross_count=6,
            turn_count=8,
            lower_touch_count=3,
            upper_touch_count=3,
            edge_alternation_count=5,
            reversal_response_rate=1.0,
            path_efficiency=0.1,
            drift_percent=0.0,
            drift_to_width=0.0,
            recent_path_efficiency=0.1,
            recent_drift_percent=0.0,
            recent_drift_to_width=0.0,
            amplitude_percent=2.0,
            score=10.0,
            trend_pause=False,
            trend_direction=None,
            current_price=100.0,
            instantaneous_vol_percent=0.2,
            bollinger_width_percent=4.0,
            reservation_price=100.0,
            long_entry_edge_fraction=0.42,
            short_entry_edge_fraction=0.42,
            long_wick_model="ev",
            short_wick_model="ev",
            long_wick_avg_net_percent=0.1,
            short_wick_avg_net_percent=0.1,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                wick_require_positive_ev=True,
                grid_layer_count=3,
                grid_layer_spacing_fraction=0.35,
                min_reservation_edge_fraction=-0.12,
                max_reservation_edge_fraction=0.50,
            ),
        )

        long_entries = [order.entry_price for order in orders if order.side == "long"]
        short_entries = [order.entry_price for order in orders if order.side == "short"]
        self.assertEqual(len(long_entries), 3)
        self.assertEqual(len(short_entries), 3)
        self.assertEqual(long_entries, sorted(long_entries, reverse=True))
        self.assertEqual(short_entries, sorted(short_entries))
        self.assertTrue(all(entry < state.current_price for entry in long_entries))
        self.assertTrue(all(entry > state.current_price for entry in short_entries))

    def test_dynamic_entry_edge_starts_just_outside_band_edge(self):
        state = research.replace(
            self.state(),
            current_price=100.0,
            long_entry_edge_fraction=0.42,
            short_entry_edge_fraction=0.42,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                dynamic_entry_edge_enabled=True,
                dynamic_entry_base_edge_fraction=-0.08,
                dynamic_entry_max_push_fraction=0.24,
                pullback_model_enabled=False,
                spike_depth_entry_enabled=False,
                grid_layer_count=1,
                wick_require_positive_ev=False,
            ),
        )

        long = next(order for order in orders if order.side == "long")
        short = next(order for order in orders if order.side == "short")
        self.assertAlmostEqual(research.edge_fraction_for_order("long", long.entry_price, state), -0.08)
        self.assertAlmostEqual(research.edge_fraction_for_order("short", short.entry_price, state), -0.08)
        self.assertIn("dynamic_entry_base_edge_fraction:-0.08", long.reason_codes)
        self.assertIn("dynamic_entry_applied_edge_fraction:-0.08", short.reason_codes)

    def test_dynamic_entry_edge_pushes_farther_when_flow_and_momentum_are_forceful(self):
        state = research.replace(
            self.state(),
            current_price=100.0,
            long_entry_edge_fraction=0.42,
            short_entry_edge_fraction=0.42,
            recent_drift_percent=-1.4,
            instantaneous_vol_percent=0.8,
            recent_spike_depth_percent=2.0,
            entry_taker_buy_ratio=0.18,
            long_entry_continuation_fraction=0.18,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                dynamic_entry_edge_enabled=True,
                dynamic_entry_base_edge_fraction=-0.08,
                dynamic_entry_max_push_fraction=0.24,
                pullback_model_enabled=False,
                spike_depth_entry_enabled=False,
                grid_layer_count=1,
                wick_require_positive_ev=False,
            ),
        )

        long = next(order for order in orders if order.side == "long")
        long_edge = research.edge_fraction_for_order("long", long.entry_price, state)
        self.assertLess(long_edge, -0.08)
        self.assertGreaterEqual(long_edge + 1e-9, -0.32)
        self.assertTrue(any(code.startswith("dynamic_entry_total_push_fraction:") for code in long.reason_codes))
        self.assertIn("dynamic_entry_flow_pressure:1.0", long.reason_codes)

    def test_dynamic_exit_geometry_uses_flow_volatility_and_mean_reversion_target(self):
        state = research.replace(
            self.state(),
            current_price=100.0,
            long_entry_edge_fraction=0.42,
            short_entry_edge_fraction=0.42,
            long_stop_span_fraction=0.12,
            long_target_span_fraction=0.20,
            recent_drift_percent=-1.4,
            instantaneous_vol_percent=0.8,
            recent_spike_depth_percent=2.0,
            entry_taker_buy_ratio=0.18,
            long_entry_continuation_fraction=0.12,
            long_wick_success_rate=0.75,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                dynamic_entry_edge_enabled=True,
                dynamic_entry_base_edge_fraction=-0.08,
                dynamic_entry_max_push_fraction=0.24,
                dynamic_exit_geometry_enabled=True,
                pullback_model_enabled=False,
                spike_depth_entry_enabled=False,
                grid_layer_count=1,
                wick_require_positive_ev=False,
            ),
        )

        long = next(order for order in orders if order.side == "long")
        values = research.reason_code_map(long.reason_codes)
        stop_fraction = research.code_float(values, "dynamic_exit_stop_span_fraction", 0.0)
        target_fraction = research.code_float(values, "dynamic_exit_target_span_fraction", 0.0)
        edge_fraction = research.edge_fraction_for_order("long", long.entry_price, state)

        self.assertGreater(stop_fraction, 0.12)
        self.assertGreater(target_fraction, 0.50 - edge_fraction - 0.08)
        self.assertTrue(any(code.startswith("dynamic_exit_quality:") for code in long.reason_codes))
        self.assertTrue(any(code.startswith("dynamic_exit_stop_pressure:") for code in long.reason_codes))

    def test_spike_depth_entry_can_extend_beyond_legacy_min_edge_for_upper_wick_short(self):
        state = research.replace(
            self.state(),
            current_price=101.2,
            lower_price=98.0,
            upper_price=102.0,
            width_percent=4.0,
            close_position_percent=92.0,
            short_entry_edge_fraction=0.42,
            short_stop_span_fraction=0.18,
            short_target_span_fraction=0.35,
            recent_spike_depth_percent=2.4,
            recent_drift_percent=1.2,
            instantaneous_vol_percent=0.5,
            entry_taker_buy_ratio=0.62,
            short_pullback_quality=0.55,
            short_entry_continuation_fraction=0.02,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                dynamic_entry_edge_enabled=True,
                dynamic_exit_geometry_enabled=True,
                pullback_model_enabled=False,
                spike_depth_entry_enabled=True,
                spike_depth_entry_fraction=0.92,
                spike_depth_tail_buffer_fraction=0.22,
                spike_depth_stop_fraction=1.45,
                spike_depth_max_entry_edge_fraction=-1.35,
                spike_depth_max_stop_fraction=1.25,
                min_reservation_edge_fraction=-0.36,
                wick_min_entry_fraction=-1.35,
                wick_max_stop_fraction=0.72,
                dynamic_exit_max_stop_fraction=0.78,
                grid_layer_count=1,
                wick_require_positive_ev=False,
            ),
        )

        short = next(order for order in orders if order.side == "short")
        values = research.reason_code_map(short.reason_codes)
        short_edge = research.edge_fraction_for_order("short", short.entry_price, state)
        stop_fraction = research.code_float(values, "stop_span_fraction", 0.0)

        self.assertLess(short_edge, -0.36)
        self.assertGreater(stop_fraction, 0.56)
        self.assertIn("spike_depth_dynamic_min_edge_fraction:-", " ".join(short.reason_codes))
        self.assertTrue(any(code.startswith("spike_depth_short_tail_pressure:") for code in short.reason_codes))

    def test_directional_path_is_rejected_as_trend_pause(self):
        state, reasons = research.build_micro_grid_state(trend_seconds(count=120), 80, self.profile())

        self.assertIsNone(state)
        self.assertIn("trend_pause_up", reasons)
        self.assertIn("path_too_directional", reasons)

    def test_recent_directional_acceleration_is_diagnostic_only(self):
        seconds = oscillating_seconds(count=120)
        for index in range(50, 80):
            price = 1.15 - (index - 50) * 0.006
            seconds[index] = bar("TESTUSDT", index, open_price=price + 0.004, high=price + 0.004, low=price - 0.004, close=price)

        state, reasons = research.build_micro_grid_state(
            seconds,
            80,
            self.profile(
                min_width_percent=0.1,
                min_edge_alternations=1,
                min_reversal_response_rate=0.1,
                max_drift_to_width=2.0,
            ),
        )

        self.assertNotIn("recent_path_too_directional", reasons)
        self.assertNotIn("recent_drift_too_large_vs_width", reasons)

    def test_min_target_net_usdt_filters_orders_without_enough_meat(self):
        state = self.state()

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                min_target_net_usdt=5.0,
                target_net_filter_notional_usdt=120.0,
                wick_require_positive_ev=False,
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
            ),
        )

        self.assertEqual(orders, [])

    def test_cost_aware_target_extends_thin_target_when_band_has_room(self):
        state = self.state()

        target, reason = research.cost_aware_target(
            "long",
            entry=98.5,
            target=98.58,
            state=state,
            profile=self.profile(
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
                fee_filter_leverage=10.0,
                min_net_margin_reward_percent=0.25,
                target_extension_enabled=True,
                target_extension_max_fraction=0.65,
            ),
        )

        self.assertEqual(reason, "extended_to_cost_floor")
        self.assertGreater(target, 98.58)
        self.assertGreaterEqual(research.percent_delta(98.5, target), 0.095)

    def test_fresh_edge_reversal_reasons_reduce_quality_but_do_not_block(self):
        scale, reasons = research.micro_trade_quality_scale_from_reason_codes(
            [
                "stable_width_percent:0.6",
                "edge_reversal_reason:upper_extreme_too_fresh",
                "basket_size_weight:0.75",
            ]
        )

        self.assertGreater(scale, 0.0)
        self.assertLess(scale, 1.0)
        self.assertIn("quality_edge_reversal_fresh:upper_extreme_too_fresh", reasons)

    def test_directional_entry_path_still_blocks_micro_grid_quality(self):
        scale, reasons = research.micro_trade_quality_scale_from_reason_codes(
            [
                "stable_width_percent:0.6",
                "edge_reversal_reason:entry_path_too_directional",
                "basket_size_weight:0.75",
            ]
        )

        self.assertEqual(scale, 0.0)
        self.assertIn("quality_edge_reversal_blocked:entry_path_too_directional", reasons)

    def test_default_cost_aware_target_only_requires_nominal_fee_coverage(self):
        state = self.state()

        target, reason = research.cost_aware_target(
            "long",
            entry=98.5,
            target=98.55,
            state=state,
            profile=self.profile(
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
                fee_filter_leverage=20.0,
                min_net_margin_reward_percent=0.0,
                target_extension_enabled=True,
                target_extension_max_fraction=0.65,
            ),
        )

        self.assertEqual(reason, "extended_to_cost_floor")
        self.assertGreaterEqual(research.percent_delta(98.5, target), 0.07)
        self.assertLess(research.percent_delta(98.5, target), 0.08)

    def test_cost_aware_target_does_not_fake_room_past_target_cap(self):
        state = self.state()

        target, reason = research.cost_aware_target(
            "long",
            entry=100.5,
            target=100.55,
            state=state,
            profile=self.profile(
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
                fee_filter_leverage=10.0,
                min_net_margin_reward_percent=1.50,
                target_extension_enabled=True,
                target_extension_max_fraction=0.55,
            ),
        )

        self.assertEqual(reason, "insufficient_room")
        self.assertEqual(target, 100.55)

    def test_wide_band_survives_target_net_filter(self):
        state = research.MicroGridState(
            signal_index=0,
            signal_time=bar("TESTUSDT", 0, open_price=100, high=100, low=100, close=100).open_time_iso,
            center_price=100,
            projected_center_price=100,
            lower_price=92,
            upper_price=108,
            width_percent=16,
            close_position_percent=50,
            center_cross_count=6,
            turn_count=8,
            lower_touch_count=3,
            upper_touch_count=3,
            edge_alternation_count=5,
            reversal_response_rate=1.0,
            path_efficiency=0.1,
            drift_percent=0.0,
            drift_to_width=0.0,
            recent_path_efficiency=0.1,
            recent_drift_percent=0.0,
            recent_drift_to_width=0.0,
            amplitude_percent=8.0,
            score=10.0,
            trend_pause=False,
            trend_direction=None,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                min_target_net_usdt=5.0,
                target_net_filter_notional_usdt=120.0,
                wick_require_positive_ev=False,
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
            ),
        )

        self.assertEqual({order.side for order in orders}, {"long", "short"})
        self.assertTrue(any(code.startswith("estimated_target_net_usdt:") for code in orders[0].reason_codes))

    def test_positive_ev_requirement_blocks_default_wick_orders(self):
        orders = research.build_grid_orders("TESTUSDT", self.state(), self.profile(wick_require_positive_ev=True))

        self.assertNotEqual(orders, [])
        self.assertTrue(any("wick_model:default" in code for code in orders[0].reason_codes))

    def test_ev_entry_floor_does_not_double_kill_non_ev_fallback(self):
        state = research.replace(
            self.state(),
            long_wick_model="default_no_positive_ev",
            short_wick_model="default_no_positive_ev",
            long_entry_edge_fraction=0.04,
            short_entry_edge_fraction=0.04,
            current_price=100.0,
        )

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                wick_require_positive_ev=True,
                wick_ev_min_entry_edge_fraction=0.08,
                post_only_entry_gap_bps=0.0,
                pullback_model_enabled=False,
                grid_layer_count=1,
            ),
        )

        self.assertEqual({order.side for order in orders}, {"long", "short"})
        self.assertTrue(all(abs(research.edge_fraction_for_order(order.side, order.entry_price, state) - 0.04) < 1e-9 for order in orders))

    def test_zero_post_only_gap_allows_passive_edge_touch_orders(self):
        self.assertTrue(research.is_passive_entry("long", 100.0, 100.0, self.profile(post_only_entry_gap_bps=0.0)))
        self.assertTrue(research.is_passive_entry("short", 100.0, 100.0, self.profile(post_only_entry_gap_bps=0.0)))

        strict = self.profile(post_only_entry_gap_bps=0.2, maker_fee_bps=2.0, taker_fee_bps=4.0, exit_slippage_bps=1.0)
        self.assertFalse(research.is_passive_entry("long", 100.0, 100.0, strict))

    def test_margin_reward_filter_is_disabled_by_default_for_leveraged_micro_moves(self):
        state = self.state()

        orders = research.build_grid_orders(
            "TESTUSDT",
            state,
            self.profile(
                wick_require_positive_ev=False,
                min_net_margin_reward_percent=0.0,
                min_net_notional_reward_percent=0.0,
                min_reward_cost_ratio=1.0,
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
            ),
        )

        self.assertNotEqual(orders, [])
        self.assertTrue(any("net_margin_reward_percent:" in code for code in orders[0].reason_codes))

    def test_explicit_margin_reward_filter_can_still_reject_tiny_targets(self):
        state = self.state()

        reasons = research.single_grid_order_rejection_reasons(
            state,
            self.profile(
                min_net_margin_reward_percent=100.0,
                min_net_notional_reward_percent=0.0,
                min_reward_cost_ratio=1.0,
                maker_fee_bps=2.0,
                taker_fee_bps=4.0,
                exit_slippage_bps=1.0,
            ),
            side="long",
            entry=98.5,
            target=98.6,
            stop=97.0,
        )

        self.assertIn("long_net_margin_reward_too_low", reasons)

    def test_ev_candidate_rejects_high_same_bar_stop_rate(self):
        result = {
            "fill_count": 10,
            "fill_rate": 0.8,
            "win_rate": 0.7,
            "stop_rate": 0.2,
            "same_bar_stop_rate": 0.2,
            "avg_net_percent": 0.12,
            "expected_net_percent": 0.08,
        }

        self.assertFalse(
            research.candidate_passes_ev_filters(
                result,
                self.profile(
                    wick_ev_min_fills=5,
                    wick_ev_min_fill_rate=0.1,
                    wick_ev_min_win_rate=0.45,
                    wick_ev_max_stop_rate=0.3,
                    wick_ev_max_same_bar_stop_rate=0.08,
                    wick_ev_min_avg_net_percent=0.04,
                ),
            )
        )

    def test_default_ev_filter_allows_moderate_same_bar_stop_rate(self):
        result = {
            "fill_count": 10,
            "fill_rate": 0.8,
            "win_rate": 0.7,
            "stop_rate": 0.2,
            "same_bar_stop_rate": 0.2,
            "avg_net_percent": 0.12,
            "expected_net_percent": 0.08,
        }

        self.assertTrue(
            research.candidate_passes_ev_filters(
                result,
                self.profile(
                    wick_ev_min_fills=5,
                    wick_ev_min_fill_rate=0.1,
                    wick_ev_min_win_rate=0.45,
                    wick_ev_max_stop_rate=0.3,
                    wick_ev_min_avg_net_percent=0.04,
                ),
            )
        )

    def test_long_limit_entry_fills_and_exits_on_target(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=101, high=101, low=100.4, close=100.7),
            bar("TESTUSDT", 1, open_price=100.7, high=100.8, low=99.8, close=100.1),
            bar("TESTUSDT", 2, open_price=100.4, high=102.2, low=100.3, close=102.0),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )

        trade, status, fill_index = research.simulate_grid_order(seconds, order, self.profile(max_hold_seconds=5), notional_usdt=100)

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 1)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertGreater(trade.net_pnl_usdt, 0)
        self.assertEqual(trade.initial_risk_usdt, 2.0)

    def test_tick_replay_uses_true_sequence_when_target_precedes_stop_in_same_second(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=101, high=102.4, low=98.5, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=100.0, low=100.0, close=100.0),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )
        ticks = tick_stream("TESTUSDT", [(100, 100.0), (200, 102.1), (300, 98.8)])

        trade, status, fill_index = research.simulate_grid_order(
            seconds,
            order,
            self.profile(max_hold_seconds=5),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertEqual(trade.hold_seconds, 1)
        self.assertGreater(trade.net_pnl_usdt, 0)

    def test_tick_replay_uses_true_sequence_when_stop_precedes_target_in_same_second(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=101, high=102.4, low=98.5, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=102.2, low=100.0, close=102.0),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )
        ticks = tick_stream("TESTUSDT", [(100, 100.0), (200, 98.8), (300, 102.1)])

        trade, status, fill_index = research.simulate_grid_order(
            seconds,
            order,
            self.profile(max_hold_seconds=5),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "same_bar_stop")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "same_bar_stop")
        self.assertLess(trade.net_pnl_usdt, 0)

    def test_post_fill_confirmation_exits_when_fill_does_not_revert(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=101, high=101, low=99.6, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=100.0, low=99.3, close=99.5),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )
        ticks = tick_stream("TESTUSDT", [(100, 100.0), (2_000, 99.8), (4_000, 99.65), (9_000, 99.7)])

        trade, status, fill_index = research.simulate_grid_order(
            seconds,
            order,
            self.profile(
                max_hold_seconds=20,
                post_fill_confirmation_enabled=True,
                post_fill_confirmation_seconds=8,
                post_fill_confirmation_min_progress=0.08,
                post_fill_confirmation_max_adverse_progress=0.20,
                post_fill_confirmation_exit_loss_fraction=0.30,
            ),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "post_fill_confirmation_exit")
        self.assertIn("post_fill_confirmation_reason:post_fill_confirmation_no_reversal", trade.reason_codes)
        self.assertLess(trade.net_pnl_usdt, 0)
        self.assertGreater(trade.net_pnl_usdt, -1.0)

    def test_post_fill_confirmation_does_not_override_original_target(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=101, high=104.5, low=99.8, close=104.0),
            bar("TESTUSDT", 1, open_price=104.0, high=104.0, low=104.0, close=104.0),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )
        ticks = tick_stream("TESTUSDT", [(100, 100.0), (1_000, 101.0), (2_000, 104.1), (3_000, 103.6)])

        trade, status, fill_index = research.simulate_grid_order(
            seconds,
            order,
            self.profile(max_hold_seconds=20, post_fill_confirmation_enabled=True),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertGreater(trade.net_pnl_usdt, 0)

    def test_tick_replay_can_hold_across_full_oscillation_wave(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=103.0, low=99.8, close=101.0)
            for index in range(90)
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=102.5,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )
        ticks = tick_stream(
            "TESTUSDT",
            [
                (500, 100.0),
                (20_000, 100.6),
                (45_000, 101.2),
                (70_000, 102.6),
            ],
        )

        trade, status, fill_index = research.simulate_grid_order(
            seconds,
            order,
            self.profile(max_hold_seconds=120),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertGreaterEqual(trade.hold_seconds, 70)
        self.assertGreater(trade.net_pnl_usdt, 2.0)

    def test_sparse_tick_stream_uses_second_bar_at_hold_horizon_instead_of_false_data_end(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=100.2, low=99.8, close=100.0)
            for index in range(10)
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=5,
        )
        ticks = tick_stream("TESTUSDT", [(100, 100.0, True), (1_000, 100.1, False)])

        trade, status, _ = research.simulate_grid_order(
            seconds,
            order,
            self.profile(max_hold_seconds=5),
            notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "max_hold_exit")
        self.assertGreaterEqual(research.parse_iso_ms(trade.exit_time), BASE_MS + 5_100)

    def test_sparse_filled_basket_uses_second_bar_at_hold_horizon(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=100.2, low=99.8, close=100.0)
            for index in range(10)
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=98.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=[],
            max_hold_seconds=5,
        )
        fills = [research.BasketFill(order=order, fill_time_ms=BASE_MS + 100)]
        ticks = tick_stream("TESTUSDT", [(100, 100.0, True), (1_000, 100.1, False)])

        trade, status, _ = research.simulate_filled_basket_on_ticks(
            seconds,
            fills,
            self.profile(max_hold_seconds=5),
            base_notional_usdt=100.0,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "max_hold_exit")
        self.assertGreaterEqual(research.parse_iso_ms(trade.exit_time), BASE_MS + 5_100)

    def test_dca_basket_can_survive_first_layer_wick_and_exit_on_target(self):
        seconds = [
            bar("TESTUSDT", index, open_price=100.0, high=106.0, low=99.0, close=101.0)
            for index in range(30)
        ]
        state = self.state()
        orders = [
            research.GridOrder(
                symbol="TESTUSDT",
                side="short",
                signal_index=0,
                signal_time=seconds[0].open_time_iso,
                entry_price=101.0,
                stop_price=104.0,
                target_price=99.0,
                state=state,
                reason_codes=["signal_mode:micro_smart_grid", "grid_layer:0", "grid_layer_size:1.0"],
                size_weight=1.0,
            ),
            research.GridOrder(
                symbol="TESTUSDT",
                side="short",
                signal_index=0,
                signal_time=seconds[0].open_time_iso,
                entry_price=103.0,
                stop_price=106.0,
                target_price=101.0,
                state=state,
                reason_codes=["signal_mode:micro_smart_grid", "grid_layer:1", "grid_layer_size:0.7"],
                size_weight=0.7,
            ),
        ]
        ticks = tick_stream(
            "TESTUSDT",
            [
                (100, 101.0, False),
                (200, 103.0, False),
                (300, 104.5, False),
                (1_500, 101.0, True),
                (2_000, 99.7, True),
            ],
        )

        trade, status, fill_index = research.simulate_grid_basket(
            seconds,
            orders,
            self.profile(max_hold_seconds=10),
            base_notional_usdt=100,
            tick_stream=ticks,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertIn("execution_mode:dca_basket", trade.reason_codes)
        self.assertIn("basket_fill_count:2", trade.reason_codes)
        self.assertGreater(trade.net_pnl_usdt, 0)

    def test_same_second_stop_is_conservative_and_marks_bad_entry_when_path_recovers(self):
        seconds = [
            bar("TESTUSDT", 0, open_price=100.3, high=100.4, low=98.8, close=99.0),
            bar("TESTUSDT", 1, open_price=99.0, high=100.2, low=98.9, close=100.0),
            bar("TESTUSDT", 2, open_price=100.0, high=102.4, low=99.9, close=102.0),
        ]
        order = research.GridOrder(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            signal_time=seconds[0].open_time_iso,
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
            state=self.state(),
            reason_codes=["signal_mode:micro_smart_grid"],
        )

        trade, status, fill_index = research.simulate_grid_order(seconds, order, self.profile(max_hold_seconds=3), notional_usdt=100)

        self.assertEqual(status, "same_bar_stop")
        self.assertEqual(fill_index, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "same_bar_stop")
        self.assertIn("post_stop_path:bad_entry_or_stop", trade.reason_codes)

    def test_portfolio_replay_realizes_pnl_at_exit_and_enforces_concurrency(self):
        profile = self.profile(reentry_cooldown_seconds=8)
        first = self.trade("AAAUSDT", entry_index=0, exit_index=60, net_pnl=10.0)
        skipped_overlap = self.trade("BBBUSDT", entry_index=10, exit_index=20, net_pnl=100.0)
        after_exit = self.trade("AAAUSDT", entry_index=70, exit_index=80, net_pnl=10.0)

        replay = research.replay_portfolio(
            [first, skipped_overlap, after_exit],
            profile=profile,
            initial_capital=100.0,
            max_open_positions=1,
            risk_per_trade_fraction=0.1,
            max_notional_fraction=1.0,
        )

        self.assertEqual(replay["summary"]["trade_count"], 2)
        self.assertEqual(replay["summary"]["replay_skip_counts"]["concurrency"], 1)
        self.assertAlmostEqual(replay["trades"][0]["equity_after_exit_usdt"], 110.0)
        self.assertAlmostEqual(replay["trades"][1]["equity_before_entry_usdt"], 110.0)
        self.assertAlmostEqual(replay["summary"]["final_capital_usdt"], 121.0)

    def test_failure_summary_uses_post_stop_path_reason_codes(self):
        trades = [
            {"net_pnl_usdt": -0.2, "gross_pnl_usdt": -0.2, "mfe_percent": 0.5, "exit_reason": "stop_loss", "side": "long", "symbol": "AAAUSDT", "reason_codes": ["post_stop_path:bad_entry_or_stop"]},
            {"net_pnl_usdt": -0.2, "gross_pnl_usdt": -0.2, "mfe_percent": 0.01, "exit_reason": "stop_loss", "side": "short", "symbol": "BBBUSDT", "reason_codes": ["post_stop_path:wrong_wave_prediction"]},
            {"net_pnl_usdt": -0.01, "gross_pnl_usdt": 0.02, "mfe_percent": 0.1, "exit_reason": "trailing_stop", "side": "short", "symbol": "CCCUSDT", "reason_codes": []},
        ]

        summary = research.failure_summary(trades, profile=self.profile())

        self.assertEqual(summary["loss_count"], 3)
        self.assertEqual(summary["bucket_counts"]["stop_or_level_too_tight"], 1)
        self.assertEqual(summary["bucket_counts"]["wrong_wave_prediction"], 1)
        self.assertEqual(summary["bucket_counts"]["cost_drag"], 1)

    def test_trade_selection_score_prefers_stronger_setup_over_earlier_fill(self):
        weak = research.replace(
            self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=0.0),
            entry_time=bar("AAAUSDT", 10, open_price=100, high=100, low=100, close=100).open_time_iso,
            reason_codes=[
                "long_pullback_quality:0.15",
                "edge_reversal_ready:False",
                "entry_reversal_fraction:0.02",
                "entry_continuation_fraction:0.12",
                "wick_success_rate:0.4",
                "wick_score:0.4",
                "net_notional_reward_percent:0.12",
                "entry_edge_fraction:-0.02",
                "stop_span_fraction:0.26",
                "basket_fill_count:1",
            ],
        )
        strong = research.replace(
            self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=0.0),
            entry_time=bar("AAAUSDT", 12, open_price=100, high=100, low=100, close=100).open_time_iso,
            reason_codes=[
                "long_pullback_quality:0.70",
                "edge_reversal_ready:True",
                "entry_reversal_fraction:0.25",
                "entry_continuation_fraction:0.0",
                "wick_success_rate:0.8",
                "wick_score:0.8",
                "net_notional_reward_percent:0.20",
                "entry_edge_fraction:-0.12",
                "stop_span_fraction:0.26",
                "basket_fill_count:2",
            ],
        )

        chosen = sorted(
            [(research.parse_iso_ms(weak.entry_time), weak), (research.parse_iso_ms(strong.entry_time), strong)],
            key=lambda item: research.trade_selection_key(item[1], item[0]),
        )[0][1]

        self.assertIs(chosen, strong)

    def test_margin_and_leverage_caps_scale_notional_explicitly(self):
        trade = self.trade("AAAUSDT", entry_index=0, exit_index=10, net_pnl=1.0)

        replay = research.replay_portfolio(
            [trade],
            profile=self.profile(),
            initial_capital=30.0,
            max_open_positions=1,
            risk_per_trade_fraction=10.0,
            max_notional_fraction=10.0,
            max_margin_fraction=0.4,
            max_leverage=10.0,
        )

        scaled = replay["trades"][0]
        self.assertEqual(scaled["notional_usdt"], 120.0)
        self.assertEqual(scaled["initial_margin_usdt"], 12.0)
        self.assertEqual(scaled["assumed_leverage"], 10.0)
        self.assertEqual(scaled["equity_scale"], 6.0)

    def test_portfolio_replay_reserves_margin_for_concurrent_positions(self):
        first = self.trade("AAAUSDT", entry_index=0, exit_index=30, net_pnl=1.0)
        second = self.trade("BBBUSDT", entry_index=1, exit_index=30, net_pnl=1.0)

        replay = research.replay_portfolio(
            [first, second],
            profile=self.profile(),
            initial_capital=30.0,
            max_open_positions=2,
            risk_per_trade_fraction=10.0,
            max_notional_fraction=2.6666666667,
            max_margin_fraction=0.4,
            max_leverage=10.0,
        )

        first_scaled, second_scaled = replay["trades"]
        self.assertAlmostEqual(first_scaled["notional_usdt"], 80.0)
        self.assertAlmostEqual(first_scaled["initial_margin_usdt"], 8.0)
        self.assertAlmostEqual(second_scaled["notional_usdt"], 40.0)
        self.assertAlmostEqual(second_scaled["initial_margin_usdt"], 4.0)
        self.assertEqual(replay["summary"]["max_margin_used_percent_of_equity"], 40.0)

    def test_absolute_live_caps_bound_position_and_portfolio_notional(self):
        trades = [
            self.trade("AAAUSDT", entry_index=0, exit_index=30, net_pnl=1.0),
            self.trade("BBBUSDT", entry_index=1, exit_index=30, net_pnl=1.0),
            self.trade("CCCUSDT", entry_index=2, exit_index=30, net_pnl=1.0),
        ]

        replay = research.replay_portfolio(
            trades,
            profile=self.profile(),
            initial_capital=400.0,
            max_open_positions=3,
            risk_per_trade_fraction=10.0,
            max_notional_fraction=100.0,
            max_margin_fraction=1.0,
            max_leverage=30.0,
            max_position_notional_usdt=2_400.0,
            max_margin_per_position_usdt=80.0,
            max_portfolio_margin_usdt=400.0,
            max_portfolio_notional_usdt=4_800.0,
            pullback_scale_mode="none",
        )

        self.assertEqual(replay["summary"]["trade_count"], 2)
        self.assertEqual(replay["summary"]["replay_skip_counts"]["sizing"], 1)
        self.assertEqual([trade["notional_usdt"] for trade in replay["trades"]], [2_400.0, 2_400.0])
        self.assertEqual(replay["summary"]["max_portfolio_notional_used_usdt"], 4_800.0)
        self.assertEqual(replay["sizing"]["initial_capital_usdt"], 400.0)
        self.assertEqual(replay["sizing"]["max_portfolio_notional_usdt"], 4_800.0)

    def test_absolute_risk_cap_does_not_grow_with_equity_fraction(self):
        trade = self.trade("AAAUSDT", entry_index=0, exit_index=10, net_pnl=1.0)

        replay = research.replay_portfolio(
            [trade],
            profile=self.profile(),
            initial_capital=400.0,
            max_open_positions=1,
            risk_per_trade_fraction=1.0,
            max_notional_fraction=100.0,
            max_margin_fraction=1.0,
            max_leverage=30.0,
            max_risk_per_trade_usdt=40.0,
            pullback_scale_mode="none",
        )

        self.assertEqual(replay["trades"][0]["initial_risk_usdt"], 40.0)
        self.assertEqual(replay["trades"][0]["notional_usdt"], 80.0)

    def test_pullback_size_multiplier_caps_portfolio_scale(self):
        trade = research.replace(
            self.trade("AAAUSDT", entry_index=0, exit_index=10, net_pnl=1.0),
            reason_codes=["pullback_size_multiplier:0.35"],
        )

        replay = research.replay_portfolio(
            [trade],
            profile=self.profile(),
            initial_capital=30.0,
            max_open_positions=1,
            risk_per_trade_fraction=10.0,
            max_notional_fraction=10.0,
            max_margin_fraction=0.4,
            max_leverage=10.0,
        )

        scaled = replay["trades"][0]
        self.assertEqual(scaled["pullback_scale_cap"], 0.35)
        self.assertEqual(scaled["notional_usdt"], 7.0)
        self.assertEqual(scaled["initial_margin_usdt"], 0.7)

    def test_live_like_pullback_scale_mode_does_not_cap_portfolio_scale(self):
        trade = research.replace(
            self.trade("AAAUSDT", entry_index=0, exit_index=10, net_pnl=1.0),
            reason_codes=["pullback_size_multiplier:0.35"],
        )

        replay = research.replay_portfolio(
            [trade],
            profile=self.profile(),
            initial_capital=30.0,
            max_open_positions=1,
            risk_per_trade_fraction=10.0,
            max_notional_fraction=10.0,
            max_margin_fraction=0.4,
            max_leverage=10.0,
            pullback_scale_mode="none",
        )

        scaled = replay["trades"][0]
        self.assertEqual(scaled["pullback_scale_cap"], 0.35)
        self.assertEqual(scaled["notional_usdt"], 120.0)
        self.assertEqual(scaled["initial_margin_usdt"], 12.0)

    def test_portfolio_replay_cools_symbol_after_daily_loss(self):
        loser = self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=-1.0)
        same_symbol_after_loss = self.trade("AAAUSDT", entry_index=10, exit_index=15, net_pnl=10.0)
        other_symbol = self.trade("BBBUSDT", entry_index=10, exit_index=15, net_pnl=10.0)

        replay = research.replay_portfolio(
            [loser, same_symbol_after_loss, other_symbol],
            profile=self.profile(max_symbol_losses_per_day=1),
            initial_capital=100.0,
            max_open_positions=2,
            risk_per_trade_fraction=0.1,
            max_notional_fraction=1.0,
        )

        self.assertEqual(replay["summary"]["trade_count"], 2)
        self.assertEqual([trade["symbol"] for trade in replay["trades"]], ["AAAUSDT", "BBBUSDT"])
        self.assertEqual(replay["summary"]["replay_skip_counts"]["symbol_cooldown"], 1)

    def test_portfolio_replay_can_filter_degraded_rolling_symbol_quality(self):
        first_loss = self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=-1.0)
        second_loss = self.trade("AAAUSDT", entry_index=20, exit_index=25, net_pnl=-1.0)
        skipped_same_symbol = self.trade("AAAUSDT", entry_index=40, exit_index=45, net_pnl=10.0)
        other_symbol = self.trade("BBBUSDT", entry_index=40, exit_index=45, net_pnl=10.0)

        replay = research.replay_portfolio(
            [first_loss, second_loss, skipped_same_symbol, other_symbol],
            profile=self.profile(),
            initial_capital=100.0,
            max_open_positions=2,
            risk_per_trade_fraction=0.1,
            max_notional_fraction=1.0,
            symbol_quality_filter_enabled=True,
            symbol_quality_min_samples=2,
            symbol_quality_min_profit_factor=0.75,
            symbol_quality_max_stop_rate=0.65,
            symbol_quality_min_scale=0.0,
        )

        self.assertEqual([trade["symbol"] for trade in replay["trades"]], ["AAAUSDT", "AAAUSDT", "BBBUSDT"])
        self.assertEqual(replay["summary"]["replay_skip_counts"]["symbol_quality"], 1)

    def test_rolling_symbol_quality_can_downscale_instead_of_skip(self):
        first_loss = self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=-1.0)
        second_loss = self.trade("AAAUSDT", entry_index=20, exit_index=25, net_pnl=-1.0)
        reduced_same_symbol = self.trade("AAAUSDT", entry_index=40, exit_index=45, net_pnl=10.0)

        replay = research.replay_portfolio(
            [first_loss, second_loss, reduced_same_symbol],
            profile=self.profile(),
            initial_capital=100.0,
            max_open_positions=1,
            risk_per_trade_fraction=0.1,
            max_notional_fraction=1.0,
            symbol_quality_filter_enabled=True,
            symbol_quality_min_samples=2,
            symbol_quality_min_profit_factor=0.75,
            symbol_quality_max_stop_rate=0.65,
            symbol_quality_min_scale=0.25,
        )

        self.assertEqual(replay["summary"]["trade_count"], 3)
        self.assertEqual(replay["summary"]["replay_skip_counts"]["symbol_quality"], 0)
        self.assertEqual(replay["trades"][-1]["symbol_quality_scale"], 0.25)
        self.assertIn("degraded:n=2", replay["trades"][-1]["symbol_quality_reason"])

    def test_portfolio_replay_default_does_not_dead_stop_symbol_after_loss(self):
        loser = self.trade("AAAUSDT", entry_index=0, exit_index=5, net_pnl=-1.0)
        same_symbol_after_loss = self.trade("AAAUSDT", entry_index=20, exit_index=25, net_pnl=10.0)

        replay = research.replay_portfolio(
            [loser, same_symbol_after_loss],
            profile=self.profile(),
            initial_capital=100.0,
            max_open_positions=1,
            risk_per_trade_fraction=0.1,
            max_notional_fraction=1.0,
        )

        self.assertEqual(replay["summary"]["trade_count"], 2)
        self.assertEqual([trade["symbol"] for trade in replay["trades"]], ["AAAUSDT", "AAAUSDT"])
        self.assertEqual(replay["summary"]["replay_skip_counts"]["symbol_cooldown"], 0)

    def trade(self, symbol, *, entry_index, exit_index, net_pnl):
        entry = bar(symbol, entry_index, open_price=100, high=100, low=100, close=100)
        exit_bar = bar(symbol, exit_index, open_price=100, high=100, low=100, close=100)
        return research.MicroGridTrade(
            symbol=symbol,
            side="long",
            signal_time=entry.open_time_iso,
            entry_time=entry.open_time_iso,
            exit_time=exit_bar.close_time_iso,
            entry_price=100.0,
            exit_price=100.0,
            notional_usdt=20.0,
            initial_risk_usdt=10.0,
            gross_pnl_usdt=net_pnl,
            fees_usdt=0.0,
            slippage_usdt=0.0,
            net_pnl_usdt=net_pnl,
            hold_seconds=exit_index - entry_index + 1,
            mfe_percent=1.0,
            mae_percent=-1.0,
            realized_r=net_pnl / 10.0,
            exit_reason="take_profit" if net_pnl > 0 else "stop_loss",
            reason_codes=["test"],
        )

    def pending_quality_seconds(self, *, expanding_volume, post_signal_taker_buy_fraction=0.2):
        bars = []
        for index in range(60):
            if index < 30:
                close = 100.0
            else:
                close = 100.0 - (index - 29) * 0.1
            quote_volume = 30.0 if expanding_volume and index >= 30 else 10.0
            open_price = bars[-1].close if bars else close
            bars.append(
                bar(
                    "TESTUSDT",
                    index,
                    open_price=open_price,
                    high=max(open_price, close) + 0.03,
                    low=min(open_price, close) - 0.03,
                    close=close,
                    quote_volume=quote_volume,
                )
            )
            bars[-1] = replace(
                bars[-1],
                taker_buy_quote_volume=quote_volume * (post_signal_taker_buy_fraction if index >= 30 else 0.5),
            )
        return bars

    def reversal_scout_seconds(self, *, reverses):
        bars = []
        for index in range(60):
            if index < 30:
                close = 100.0
            elif reverses:
                path = [99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.7, 99.9, 99.7, 99.5, 99.3]
                close = path[min(index - 30, len(path) - 1)]
            else:
                close = 99.8 - (index - 30) * 0.04
            open_price = bars[-1].close if bars else close
            bars.append(
                bar(
                    "TESTUSDT",
                    index,
                    open_price=open_price,
                    high=max(open_price, close) + 0.03,
                    low=min(open_price, close) - 0.03,
                    close=close,
                    quote_volume=20.0,
                )
            )
        return bars


if __name__ == "__main__":
    unittest.main()
