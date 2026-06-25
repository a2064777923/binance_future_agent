import unittest
from datetime import datetime, timezone

from bfa.backtest.adapters import (
    FoldRange,
    FoldResult,
    LimitRangeFoldRunner,
    MicroGridFoldRunner,
    TrendFoldRunner,
)
from bfa.backtest.cost import CostModel
from bfa.backtest.models import BacktestBar


FIVE_MIN = 300_000
ONE_MIN = 60_000
ONE_SEC = 1_000


def _ts(month: str, day: int) -> datetime:
    y, m = month.split("-")
    return datetime(int(y), int(m), day, tzinfo=timezone.utc)


def _bars(n=40, base=1_770_000_000_000):
    bars = []
    for i in range(n):
        bars.append(BacktestBar(
            symbol="BTCUSDT", open_time=base + i * FIVE_MIN,
            open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.5 + i,
            volume=10.0, close_time=base + i * FIVE_MIN + FIVE_MIN - 1,
            quote_volume=8_000_000.0, taker_buy_quote_volume=4_500_000.0))
    return bars


class TestTrendFoldRunner(unittest.TestCase):
    def test_fold_range_is_frozen(self):
        fr = FoldRange(leg="trend", symbols=("BTCUSDT",), train_start=_ts("2026-01", 1),
                       train_end=_ts("2026-01", 31), test_start=_ts("2026-02", 1),
                       test_end=_ts("2026-02", 28))
        with self.assertRaises(Exception):
            fr.leg = "micro"  # frozen dataclass

    def test_run_fold_returns_fold_result_with_accounting(self):
        runner = TrendFoldRunner(
            cost_model=CostModel(),
            variant_name="quant_setup_live_action_flow",
            bars_by_symbol={"BTCUSDT": _bars()},
            funding_rates_by_symbol={"BTCUSDT": []},
            config_overrides={"max_hold_bars": 4, "lookback_bars": 3},
        )
        result = runner.run_fold(
            FoldRange(leg="trend", symbols=("BTCUSDT",),
                      train_start=_ts("2026-01", 1), train_end=_ts("2026-01", 31),
                      test_start=_ts("2026-02", 1), test_end=_ts("2026-02", 28)),
            split="test",
            params={},
        )
        self.assertIsInstance(result, FoldResult)
        self.assertEqual(result.leg, "trend")
        self.assertEqual(result.split, "test")
        # candidate accounting must always be present (full candidate flow)
        self.assertIn("rejected_signals", result.candidate_accounting)
        self.assertIn("trade_count", result.candidate_accounting)
        # funding_paid present even when zero
        self.assertEqual(result.funding_paid, 0.0)
        # each trade dict carries the verdict net_pnl (post fee+funding)
        for t in result.trades:
            self.assertIn("net_pnl_usdt", t)
            self.assertIn("funding_cost_usdt", t)

    def test_params_min_post_cost_edge_ratio_applied_to_profile(self):
        runner = TrendFoldRunner(
            cost_model=CostModel(),
            variant_name="quant_setup_live_action_flow",
            bars_by_symbol={"BTCUSDT": _bars()},
            funding_rates_by_symbol={"BTCUSDT": []},
            config_overrides={"max_hold_bars": 4, "lookback_bars": 3},
        )
        config_lo = runner._build_config({"min_post_cost_edge_ratio": 1.0})
        config_hi = runner._build_config({"min_post_cost_edge_ratio": 2.5})
        self.assertAlmostEqual(config_lo.setup_profile["min_post_cost_edge_ratio"], 1.0)
        self.assertAlmostEqual(config_hi.setup_profile["min_post_cost_edge_ratio"], 2.5)


def _rhythmic_1m_bars(symbol="AAAUSDT", count=160, base=1_700_000_000_000):
    """Oscillating 1m bars that fire limit-range rhythm signals (mirrors the
    pattern in tests/test_limit_range_research_script.py)."""
    closes = [99.15, 99.65, 100.25, 100.85, 100.3, 99.7]
    bars = []
    for index in range(count):
        close = closes[index % len(closes)]
        open_price = closes[(index - 1) % len(closes)] if index else 100.0
        bars.append(BacktestBar(
            symbol=symbol, open_time=base + index * ONE_MIN,
            open=open_price, high=max(open_price, close) + 0.12,
            low=min(open_price, close) - 0.12, close=close,
            volume=1_000.0, close_time=base + index * ONE_MIN + 59_999,
            quote_volume=1_000_000.0 + (index % 3) * 1_000,
            taker_buy_quote_volume=(1_000_000.0 + (index % 3) * 1_000) / 2,
        ))
    return bars


class TestLimitRangeFoldRunner(unittest.TestCase):
    def test_run_fold_returns_fold_result_with_full_accounting(self):
        # bars live on 2023-11-14 (base 1_700_000_000_000 ms)
        runner = LimitRangeFoldRunner(
            cost_model=CostModel(),
            bars_by_symbol={"AAAUSDT": _rhythmic_1m_bars()},
            funding_rates_by_symbol={"AAAUSDT": []},
        )
        result = runner.run_fold(
            FoldRange(leg="limit_range", symbols=("AAAUSDT",),
                      train_start=datetime(2023, 11, 1, tzinfo=timezone.utc),
                      train_end=datetime(2023, 11, 30, 23, 59, 59, tzinfo=timezone.utc),
                      test_start=datetime(2023, 11, 14, tzinfo=timezone.utc),
                      test_end=datetime(2023, 11, 15, tzinfo=timezone.utc)),
            split="test",
            params={"min_reward_cost_ratio": 1.0, "target_stop_geometry": "a"},
        )
        self.assertIsInstance(result, FoldResult)
        self.assertEqual(result.leg, "limit_range")
        self.assertEqual(result.split, "test")
        # full candidate flow accounting: order stage + front-end + trade_count
        acc = result.candidate_accounting
        self.assertIn("trade_count", acc)
        self.assertIn("order_stats", acc)
        self.assertIn("orders_created", acc["order_stats"])
        self.assertEqual(result.funding_paid, 0.0)
        for t in result.trades:
            self.assertIn("net_pnl_usdt", t)
            self.assertIn("funding_cost_usdt", t)

    def test_geometry_b_widens_target_and_tightens_stop(self):
        runner = LimitRangeFoldRunner(
            cost_model=CostModel(),
            bars_by_symbol={"AAAUSDT": _rhythmic_1m_bars()},
            funding_rates_by_symbol={"AAAUSDT": []},
        )
        prof_a = runner._build_profile({"target_stop_geometry": "a"})
        prof_b = runner._build_profile({"target_stop_geometry": "b"})
        self.assertGreater(prof_b.target_range_fraction, prof_a.target_range_fraction)
        self.assertLess(prof_b.stop_outside_fraction, prof_a.stop_outside_fraction)

    def test_min_reward_cost_ratio_applied_to_profile(self):
        runner = LimitRangeFoldRunner(
            cost_model=CostModel(),
            bars_by_symbol={"AAAUSDT": _rhythmic_1m_bars()},
            funding_rates_by_symbol={"AAAUSDT": []},
        )
        prof = runner._build_profile({"min_reward_cost_ratio": 2.5})
        self.assertAlmostEqual(prof.min_reward_cost_ratio, 2.5)


def _oscillating_seconds(symbol="TESTUSDT", count=900, base=1_700_000_000_000):
    """Second bars oscillating in a tight band so micro-grid can build state.
    Mirrors the pattern in tests/test_micro_grid_research_script.py."""
    closes = [99.6, 99.85, 100.0, 100.15, 100.4, 100.15, 100.0, 99.85]
    bars = []
    for index in range(count):
        close = closes[index % len(closes)]
        open_price = closes[(index - 1) % len(closes)] if index else 100.0
        bars.append(BacktestBar(
            symbol=symbol, open_time=base + index * ONE_SEC,
            open=open_price, high=max(open_price, close) + 0.05,
            low=min(open_price, close) - 0.05, close=close,
            volume=10.0, close_time=base + index * ONE_SEC + 999,
            quote_volume=50_000.0, taker_buy_quote_volume=25_000.0))
    return bars


class TestMicroGridFoldRunner(unittest.TestCase):
    def test_run_fold_returns_fold_result_with_full_accounting(self):
        runner = MicroGridFoldRunner(
            cost_model=CostModel(),
            seconds_by_symbol={"TESTUSDT": _oscillating_seconds()},
            funding_rates_by_symbol={"TESTUSDT": []},
        )
        result = runner.run_fold(
            FoldRange(leg="micro", symbols=("TESTUSDT",),
                      train_start=datetime(2023, 11, 1, tzinfo=timezone.utc),
                      train_end=datetime(2023, 11, 30, 23, 59, 59, tzinfo=timezone.utc),
                      test_start=datetime(2023, 11, 14, tzinfo=timezone.utc),
                      test_end=datetime(2023, 11, 15, tzinfo=timezone.utc)),
            split="test",
            params={"min_reward_cost_ratio": 1.0, "target_fraction": 0.5,
                    "wick_depth_gate": "current"},
        )
        self.assertIsInstance(result, FoldResult)
        self.assertEqual(result.leg, "micro")
        self.assertEqual(result.split, "test")
        acc = result.candidate_accounting
        self.assertIn("trade_count", acc)
        self.assertIn("diagnostics", acc)
        self.assertIn("order_stats", acc)
        self.assertIn("evaluated_windows", acc["diagnostics"])
        self.assertIn("orders_created", acc["order_stats"])
        self.assertEqual(result.funding_paid, 0.0)
        for t in result.trades:
            self.assertIn("net_pnl_usdt", t)
            self.assertIn("funding_cost_usdt", t)

    def test_grid_knobs_map_to_profile(self):
        runner = MicroGridFoldRunner(
            cost_model=CostModel(),
            seconds_by_symbol={"TESTUSDT": _oscillating_seconds()},
            funding_rates_by_symbol={"TESTUSDT": []},
        )
        prof = runner._build_profile(
            {"min_reward_cost_ratio": 2.2, "target_fraction": 1.0,
             "wick_depth_gate": "strict"})
        self.assertAlmostEqual(prof.min_reward_cost_ratio, 2.2)
        self.assertAlmostEqual(prof.spike_depth_target_fraction, 1.0)
        # strict raises the dead-market floor so only the deepest wicks qualify
        self.assertGreater(prof.spike_depth_min_percent,
                           MicroGridFoldRunner._WICK_DEPTH_CURRENT)


if __name__ == "__main__":
    unittest.main()
