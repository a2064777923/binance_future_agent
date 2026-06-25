import unittest
from datetime import datetime, timezone

from bfa.backtest.adapters import FoldRange, FoldResult, TrendFoldRunner
from bfa.backtest.cost import CostModel
from bfa.backtest.models import BacktestBar


FIVE_MIN = 300_000


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


if __name__ == "__main__":
    unittest.main()
