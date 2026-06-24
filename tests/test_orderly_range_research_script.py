import importlib.util
import sys
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from bfa.backtest.models import BacktestBar


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_orderly_range_research.py"
SPEC = importlib.util.spec_from_file_location("orderly_range_research", SCRIPT_PATH)
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


def oscillating_bars(symbol="TESTUSDT", count=70, *, low=99.0, high=101.0):
    bars = []
    closes = [99.2, 100.8, 99.3, 100.7, 99.25, 100.75]
    for index in range(count):
        close = closes[index % len(closes)]
        open_price = closes[(index - 1) % len(closes)] if index else 100.0
        bars.append(
            bar(
                symbol,
                index,
                open_price=open_price,
                high=high if close > 100 else max(close, open_price) + 0.2,
                low=low if close < 100 else min(close, open_price) - 0.2,
                close=close,
            )
        )
    return bars


class OrderlyRangeResearchScriptTests(unittest.TestCase):
    def profile(self):
        return research.RangeProfile(
            lookback_minutes=12,
            min_width_percent=0.6,
            max_width_percent=3.0,
            max_path_efficiency=0.45,
            max_volume_cv=0.1,
            max_trend_abs_percent=1.0,
            min_touch_count=2,
            min_edge_alternations=2,
            min_mid_cross_count=2,
            low_zone_percent=25,
            high_zone_percent=75,
            min_quote_volume_usdt=100_000,
            limit_wait_minutes=3,
            max_hold_minutes=8,
            trailing_activate_r=0.2,
            trailing_lock_r=0.05,
            trailing_giveback_r=0.12,
        )

    def test_range_features_capture_orderly_oscillation(self):
        features = research.range_features(oscillating_bars(count=18))

        self.assertIsNotNone(features)
        self.assertGreaterEqual(features.lower_touch_count, 2)
        self.assertGreaterEqual(features.upper_touch_count, 2)
        self.assertGreaterEqual(features.edge_alternation_count, 2)
        self.assertGreaterEqual(features.mid_cross_count, 2)
        self.assertLess(features.path_efficiency, 0.45)

    def test_build_range_signal_uses_edge_side_and_limit_price(self):
        bars = oscillating_bars(count=21)
        bars[8] = bar("TESTUSDT", 8, open_price=100.0, high=101.0, low=99.0, close=99.3)
        bars[19] = bar("TESTUSDT", 19, open_price=100.8, high=101.0, low=99.0, close=99.2)

        signal = research.build_range_signal("TESTUSDT", bars, 20, self.profile())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "long")
        self.assertLess(signal.entry_price, 100.0)
        self.assertIn("signal_mode:orderly_range_reversion", signal.reason_codes)

    def test_recent_directional_edge_push_blocks_counter_signal(self):
        bars = oscillating_bars(count=21)
        bars[8] = bar("TESTUSDT", 8, open_price=100.0, high=101.0, low=99.0, close=100.7)
        bars[16] = bar("TESTUSDT", 16, open_price=100.8, high=101.0, low=99.7, close=100.5, quote_volume=1_000_000)
        bars[17] = bar("TESTUSDT", 17, open_price=100.5, high=100.6, low=99.4, close=99.9, quote_volume=3_000_000)
        bars[18] = bar("TESTUSDT", 18, open_price=99.9, high=100.0, low=99.1, close=99.5, quote_volume=3_000_000)
        bars[19] = bar("TESTUSDT", 19, open_price=99.5, high=99.6, low=99.0, close=99.2, quote_volume=3_000_000)

        signal = research.build_range_signal("TESTUSDT", bars, 20, self.profile())

        self.assertIsNone(signal)

    def test_portfolio_backtest_selects_candidates_and_records_real_entry_time(self):
        profile = self.profile()
        aaa = oscillating_bars("AAAUSDT", count=70)
        bbb = oscillating_bars("BBBUSDT", count=70, low=98.5, high=101.5)

        result = research.run_portfolio_backtest(
            {"AAAUSDT": aaa, "BBBUSDT": bbb},
            profile=profile,
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertGreater(result["summary"]["trade_count"], 0)
        first = result["trades"][0]
        self.assertIn(first["symbol"], {"AAAUSDT", "BBBUSDT"})
        self.assertNotEqual(first["entry_time"], "1970-01-01T00:00:00Z")
        self.assertIn("mfe_percent", first)
        self.assertIn("mae_percent", first)
        self.assertGreaterEqual(first["hold_minutes"], 1)
        self.assertIn(first["exit_reason"], {"take_profit", "stop_loss", "trailing_stop", "range_invalid_exit", "max_hold_safety_exit"})

    def test_trailing_stop_exit_is_separate_from_initial_stop_loss(self):
        bars = [
            bar("TESTUSDT", 0, open_price=100.0, high=100.2, low=99.8, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=101.0, low=99.9, close=100.8),
            bar("TESTUSDT", 2, open_price=100.8, high=100.85, low=100.3, close=100.35),
        ]
        signal = research.RangeSignal(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            score=1.0,
            entry_price=100.0,
            stop_price=99.0,
            target_price=102.0,
            range_low_price=99.0,
            range_high_price=101.0,
            features=research.range_features(oscillating_bars(count=12)),
            reason_codes=["signal_mode:orderly_range_reversion"],
        )
        position = research.OpenPosition(
            signal=signal,
            entry_index=0,
            entry_time=bars[0].open_time_iso,
            entry_price=100.0,
            raw_entry_price=100.0,
            quantity=1.0,
            notional_usdt=100.0,
            dynamic_stop_price=99.0,
            best_price=100.0,
            worst_price=100.0,
            fees_entry_usdt=0.0,
            slippage_entry_usdt=0.0,
        )

        trade, updated = research.update_position_on_bar(bars, 1, position, self.profile())
        self.assertIsNone(trade)
        trade, _ = research.update_position_on_bar(bars, 2, updated, self.profile())

        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "trailing_stop")

    def test_trailing_stop_waits_until_move_covers_costs(self):
        profile = self.profile()
        dynamic_stop = research.trailing_stop_price("long", 100.0, 100.12, 1.0, profile)

        self.assertEqual(dynamic_stop, 99.0)

    def test_range_invalid_exit_only_reacts_to_adverse_trend(self):
        profile = research.RangeProfile(
            lookback_minutes=3,
            min_hold_minutes=1,
            trend_exit_path_efficiency=0.2,
            max_volume_cv=2.0,
            min_quote_volume_usdt=1.0,
        )
        bars = [
            bar("TESTUSDT", 0, open_price=100.0, high=100.2, low=99.8, close=100.0),
            bar("TESTUSDT", 1, open_price=100.0, high=100.5, low=99.9, close=100.4),
            bar("TESTUSDT", 2, open_price=100.4, high=100.9, low=100.3, close=100.8),
            bar("TESTUSDT", 3, open_price=100.8, high=101.3, low=100.7, close=101.2),
        ]
        signal = research.RangeSignal(
            symbol="TESTUSDT",
            side="long",
            signal_index=0,
            score=1.0,
            entry_price=100.0,
            stop_price=99.0,
            target_price=105.0,
            range_low_price=99.0,
            range_high_price=101.0,
            features=research.range_features(oscillating_bars(count=12)),
            reason_codes=["signal_mode:orderly_range_reversion"],
        )
        position = research.OpenPosition(
            signal=signal,
            entry_index=0,
            entry_time=bars[0].open_time_iso,
            entry_price=100.0,
            raw_entry_price=100.0,
            quantity=1.0,
            notional_usdt=100.0,
            dynamic_stop_price=99.0,
            best_price=100.0,
            worst_price=100.0,
            fees_entry_usdt=0.0,
            slippage_entry_usdt=0.0,
        )

        self.assertFalse(research.should_exit_for_breakout_or_trend(bars, 3, position, profile))

    def test_profile_grid_can_be_limited_for_fast_research_runs(self):
        grid = research.profile_grid(research.RangeProfile(), max_profiles=5)

        self.assertEqual(len(grid), 5)
        self.assertGreater(len({profile.lookback_minutes for profile in grid}), 1)

    def test_profile_selection_penalizes_tiny_samples(self):
        tiny_sample = {
            "trade_count": 1,
            "return_percent": 10.0,
            "profit_factor": "inf",
            "win_rate": 1.0,
            "max_drawdown_percent_of_initial": 0.0,
        }
        enough_sample = {
            "trade_count": 10,
            "return_percent": -0.1,
            "profit_factor": 0.95,
            "win_rate": 0.55,
            "max_drawdown_percent_of_initial": 0.2,
        }

        tiny_score = research.profile_selection_score(tiny_sample, min_train_trades=10)
        enough_score = research.profile_selection_score(enough_sample, min_train_trades=10)

        self.assertLess(tiny_score, enough_score)

    def test_run_test_leaderboard_limits_profile_replays(self):
        profile = self.profile()
        leaderboard = [
            {"score": 1.0, "eligible_for_selection": True, "profile": research.asdict(profile)},
            {"score": 0.5, "eligible_for_selection": True, "profile": research.asdict(profile)},
        ]

        rows = research.run_test_leaderboard(
            leaderboard,
            {"AAAUSDT": oscillating_bars("AAAUSDT", count=70)},
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
            limit=1,
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("test_summary", rows[0])

    def test_split_validation_bars_uses_final_training_days(self):
        bars = oscillating_bars("TESTUSDT", count=6)
        for index, item in enumerate(bars):
            open_time = int(datetime(2026, 2, 1 + index, tzinfo=UTC).timestamp() * 1000)
            bars[index] = research.BacktestBar(
                symbol=item.symbol,
                open_time=open_time,
                open=item.open,
                high=item.high,
                low=item.low,
                close=item.close,
                volume=item.volume,
                close_time=open_time + 59_999,
                quote_volume=item.quote_volume,
                taker_buy_quote_volume=item.taker_buy_quote_volume,
            )

        fit, validation = research.split_validation_bars(
            {"TESTUSDT": bars},
            train_end=date(2026, 2, 6),
            validation_days=2,
        )

        self.assertEqual(len(fit["TESTUSDT"]), 4)
        self.assertEqual(len(validation["TESTUSDT"]), 2)


if __name__ == "__main__":
    unittest.main()
