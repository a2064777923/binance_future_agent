import importlib.util
import sys
import unittest
from pathlib import Path

from bfa.backtest.models import BacktestBar


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_limit_range_research.py"
SPEC = importlib.util.spec_from_file_location("limit_range_research", SCRIPT_PATH)
research = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)


def bar(symbol, index, *, open_price, high, low, close, quote_volume=1_000_000):
    open_time = 1_700_000_000_000 + index * 60_000
    return BacktestBar(
        symbol=symbol,
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1_000,
        close_time=open_time + 59_999,
        quote_volume=quote_volume,
        taker_buy_quote_volume=quote_volume / 2,
    )


def rhythmic_bars(symbol="TESTUSDT", count=140):
    closes = [99.15, 99.65, 100.25, 100.85, 100.3, 99.7]
    bars = []
    for index in range(count):
        close = closes[index % len(closes)]
        open_price = closes[(index - 1) % len(closes)] if index else 100.0
        bars.append(
            bar(
                symbol,
                index,
                open_price=open_price,
                high=max(open_price, close) + 0.12,
                low=min(open_price, close) - 0.12,
                close=close,
                quote_volume=1_000_000 + (index % 3) * 1_000,
            )
        )
    return bars


class LimitRangeResearchScriptTests(unittest.TestCase):
    def profile(self, **overrides):
        values = {
            "lookback_minutes": 60,
            "min_width_percent": 0.4,
            "max_path_efficiency": 0.7,
            "max_abs_trend_percent": 2.0,
            "max_band_shift_ratio": 1.0,
            "max_volume_cv": 2.0,
            "min_edge_touches_per_side": 2,
            "min_edge_alternations": 3,
            "min_mid_crosses": 2,
            "min_reaction_success_rate": 0.2,
            "low_zone_percent": 35.0,
            "high_zone_percent": 65.0,
            "min_risk_reward": 0.8,
            "min_reward_cost_ratio": 1.0,
        }
        values.update(overrides)
        return research.RhythmProfile(**values)

    def test_rhythm_features_capture_two_sided_range(self):
        features = research.rhythm_features(rhythmic_bars(count=60), self.profile())

        self.assertIsNotNone(features)
        self.assertGreaterEqual(features.lower_touch_count, 2)
        self.assertGreaterEqual(features.upper_touch_count, 2)
        self.assertGreaterEqual(features.edge_alternation_count, 3)
        self.assertGreaterEqual(features.mid_cross_count, 2)
        self.assertGreater(features.reaction_success_rate, 0.5)
        self.assertLess(features.band_shift_ratio, 0.2)

    def test_build_rhythm_signal_places_passive_limit_at_edge(self):
        bars = rhythmic_bars(count=90)

        signal = research.build_rhythm_signal("TESTUSDT", bars, 60, self.profile())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "long")
        self.assertLess(signal.entry_price, bars[59].close)
        self.assertLess(signal.stop_price, signal.entry_price)
        self.assertGreater(signal.target_price, signal.entry_price)
        self.assertIn("signal_mode:limit_range_rhythm_reversion", signal.reason_codes)

    def test_continuation_mode_flips_edge_signal_direction_and_uses_trigger_fill(self):
        bars = rhythmic_bars(count=90)
        profile = self.profile(
            trade_direction_mode="continuation",
            max_adverse_edge_push_percent=0.0,
            max_adverse_edge_push_efficiency=0.0,
            entry_band_fraction=0.0,
            stop_outside_fraction=0.2,
            target_range_fraction=0.4,
            maker_fee_bps=2,
            taker_fee_bps=4,
        )

        signal = research.build_rhythm_signal("TESTUSDT", bars, 60, profile)
        fill_bar = bar("TESTUSDT", 90, open_price=99.8, high=100.0, low=signal.entry_price - 0.01, close=99.4)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "short")
        self.assertIn("signal_mode:limit_range_rhythm_continuation", signal.reason_codes)
        self.assertTrue(research.order_fills_on_bar(fill_bar, signal, profile))
        self.assertEqual(research.entry_fee_bps(profile), 4)

    def test_limit_order_can_expire_without_a_trade(self):
        bars = rhythmic_bars(count=70)
        signal = research.RhythmSignal(
            symbol="TESTUSDT",
            side="long",
            signal_index=60,
            score=1.0,
            entry_price=90.0,
            stop_price=89.0,
            target_price=92.0,
            range_low_price=99.0,
            range_high_price=101.0,
            features=research.rhythm_features(bars[:60], self.profile()),
            reason_codes=["signal_mode:limit_range_rhythm_reversion"],
        )

        fill_index = research.find_limit_fill_index(bars, signal, self.profile(limit_wait_minutes=3))

        self.assertIsNone(fill_index)

    def test_portfolio_backtest_tracks_created_filled_and_expired_orders(self):
        result = research.run_portfolio_backtest(
            {"AAAUSDT": rhythmic_bars("AAAUSDT", count=140)},
            profile=self.profile(),
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertGreater(result["order_stats"]["orders_created"], 0)
        self.assertGreater(result["order_stats"]["orders_filled"], 0)
        self.assertGreater(result["order_stats"]["orders_expired"], 0)
        self.assertGreater(result["summary"]["trade_count"], 0)
        self.assertIn("mfe_percent", result["trades"][0])
        self.assertIn("mae_percent", result["trades"][0])

    def test_same_bar_stop_is_recorded_conservatively_after_limit_fill(self):
        bars = [
            bar("TESTUSDT", 0, open_price=100.3, high=100.4, low=99.4, close=99.7),
        ]
        signal = research.RhythmSignal(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            score=1.0,
            entry_price=100.0,
            stop_price=99.5,
            target_price=101.0,
            range_low_price=99.0,
            range_high_price=101.0,
            features=research.rhythm_features(rhythmic_bars(count=60), self.profile()),
            reason_codes=["signal_mode:limit_range_rhythm_reversion"],
        )
        order = research.PendingLimitOrder(signal=signal, created_index=0, expires_index=0)

        filled, position, trade = research.try_fill_order(
            order,
            bars,
            current_index=0,
            equity=30,
            profile=self.profile(),
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertTrue(filled)
        self.assertIsNone(position)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "same_bar_stop_loss")

    def test_failure_summary_separates_wrong_direction_from_stop_quality(self):
        trades = [
            {"net_pnl_usdt": -0.2, "gross_pnl_usdt": -0.15, "mfe_percent": 0.01, "exit_reason": "stop_loss", "side": "long", "symbol": "AAAUSDT"},
            {"net_pnl_usdt": -0.1, "gross_pnl_usdt": 0.02, "mfe_percent": 0.5, "exit_reason": "stop_loss", "side": "short", "symbol": "BBBUSDT"},
            {"net_pnl_usdt": -0.01, "gross_pnl_usdt": 0.02, "mfe_percent": 0.1, "exit_reason": "range_invalid_exit", "side": "short", "symbol": "CCCUSDT"},
        ]

        summary = research.failure_summary(trades, profile=self.profile())

        self.assertEqual(summary["loss_count"], 3)
        self.assertEqual(summary["bucket_counts"]["direction_or_range_wrong"], 1)
        self.assertEqual(summary["bucket_counts"]["entry_or_stop_too_tight"], 1)
        self.assertEqual(summary["bucket_counts"]["cost_drag"], 1)

    def test_profile_selection_penalizes_negative_return_even_with_trades(self):
        bad = {
            "trade_count": 50,
            "return_percent": -1.0,
            "profit_factor": 0.95,
            "win_rate": 0.54,
            "max_drawdown_percent_of_initial": 2.0,
        }
        good = {
            "trade_count": 50,
            "return_percent": 0.2,
            "profit_factor": 1.04,
            "win_rate": 0.52,
            "max_drawdown_percent_of_initial": 2.0,
        }

        self.assertLess(
            research.profile_selection_score(bad, min_trades=20),
            research.profile_selection_score(good, min_trades=20),
        )


if __name__ == "__main__":
    unittest.main()
