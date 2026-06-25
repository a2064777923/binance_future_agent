import unittest
from datetime import datetime, timezone

from bfa.backtest.adapters import FoldRange, FoldResult
from bfa.backtest.walk_forward import (
    WalkForwardValidator,
    expanding_month_folds,
    grid_combos,
    classify_verdict,
    LEG_GRIDS,
)


def _ts(month: str, day: int) -> datetime:
    y, m = month.split("-")
    return datetime(int(y), int(m), day, tzinfo=timezone.utc)


class TestFoldsAndVerdict(unittest.TestCase):
    def test_expanding_folds_non_overlapping(self):
        folds = expanding_month_folds(["2025-12", "2026-01", "2026-02", "2026-03"],
                                      symbols=("BTCUSDT",), leg="trend")
        self.assertEqual(len(folds), 3)
        # fold1: train Dec, test Jan
        self.assertEqual(folds[0].train_start, _ts("2025-12", 1))
        self.assertEqual(folds[0].test_start, _ts("2026-01", 1))
        self.assertEqual(folds[0].test_end,
                         datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc))
        # fold3: train Dec..Feb, test Mar (final holdout)
        self.assertEqual(folds[2].test_start, _ts("2026-03", 1))
        self.assertTrue(folds[2].train_end < folds[2].test_start)

    def test_grid_combos_match_leg_grid(self):
        combos = grid_combos("trend")
        self.assertTrue(len(combos) >= 4)
        # every combo has the grid knobs
        for c in combos:
            self.assertIn("min_post_cost_edge_ratio", c)

    def test_verdict_unverified_when_under_30_trades(self):
        v = classify_verdict(total_trades=15, agg_net_pnl=10.0, agg_profit_factor=1.5,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[5, 5, 5])
        self.assertEqual(v, "unverified")

    def test_verdict_unverified_when_any_fold_under_30_even_if_aggregate_ok(self):
        v = classify_verdict(total_trades=40, agg_net_pnl=10.0, agg_profit_factor=1.5,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[5, 20, 15])
        self.assertEqual(v, "unverified")

    def test_verdict_negative_when_post_cost_loss(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=-5.0, agg_profit_factor=0.8,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_negative")

    def test_verdict_thin_when_pf_between_1_and_1_3(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=2.0, agg_profit_factor=1.15,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_positive_thin")

    def test_verdict_positive(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=20.0, agg_profit_factor=1.8,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_positive")

    def test_verdict_unverified_when_ratio_below_1_8(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=20.0, agg_profit_factor=1.8,
                             selected_ratio=1.0, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "unverified")

    def test_verdict_unverified_when_full_candidate_flow_false(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=20.0, agg_profit_factor=1.8,
                             selected_ratio=2.2, full_candidate_flow=False,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "unverified")


class TestWalkForwardValidator(unittest.TestCase):
    def test_run_emits_structured_verdict(self):
        fold = FoldRange(
            leg="trend", symbols=("BTCUSDT",),
            train_start=_ts("2025-12", 1), train_end=_ts("2025-12", 31),
            test_start=_ts("2026-01", 1), test_end=_ts("2026-01", 31),
        )

        class FakeRunner:
            def run_fold(self, range, *, split, params):
                if split == "train":
                    trades = [{"net_pnl_usdt": 1.0}] * 15
                else:
                    trades = [{"net_pnl_usdt": 1.0}] * 35
                return FoldResult(
                    leg="trend", fold_id="fold1", split=split, trades=trades,
                    candidate_accounting={"trade_count": len(trades)},
                    funding_paid=0.0, params=params,
                )

        validator = WalkForwardValidator(
            runner=FakeRunner(), folds=[fold], cost_model_snapshot={},
        )
        result = validator.run()
        self.assertEqual(result["leg"], "trend")
        self.assertIn("selected_params_per_fold", result)
        self.assertIn("oos_test_results", result)
        self.assertIn("oos_aggregate", result)
        self.assertIn("verdict", result)
        self.assertIn("pass_bar", result)


if __name__ == "__main__":
    unittest.main()
