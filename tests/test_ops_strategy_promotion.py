import json
import tempfile
import unittest
from pathlib import Path

from bfa.ops.strategy_promotion import build_strategy_promotion_check_report


def matrix_payload(*, promoted=True):
    verdict = "candidate_for_forward_paper" if promoted else "negative_or_flat"
    net = 1.25 if promoted else -0.5
    drawdown = 0.4 if promoted else 2.2
    return {
        "schema": "bfa_hot_backtest_matrix_v1",
        "promotion": {
            "overall": "candidate_for_forward_paper" if promoted else "keep_caps_unchanged_drawdown_risk",
            "cells": [
                {
                    "interval": "5m",
                    "variant": "quant_setup",
                    "verdict": verdict,
                    "trade_count": 12,
                    "net_pnl_usdt": net,
                    "positive_window_rate": 0.67 if promoted else 0.33,
                    "worst_drawdown_usdt": drawdown,
                    "max_daily_loss_usdt": 2.0,
                }
            ],
            "variants": {
                "quant_setup": {
                    "interval_count": 1,
                    "candidate_interval_count": 1 if promoted else 0,
                    "total_net_pnl_usdt": net,
                    "worst_drawdown_usdt": drawdown,
                    "verdict": verdict if promoted else "drawdown_exceeds_pilot_cap",
                }
            },
        },
    }


def mixed_interval_matrix_payload():
    return {
        "schema": "bfa_hot_backtest_matrix_v1",
        "promotion": {
            "overall": "keep_caps_unchanged_drawdown_risk",
            "cells": [
                {
                    "interval": "5m",
                    "variant": "quant_setup_selective",
                    "verdict": "candidate_for_forward_paper",
                    "trade_count": 51,
                    "net_pnl_usdt": 1.62468567,
                    "positive_window_rate": 1.0,
                    "worst_drawdown_usdt": 1.27227818,
                    "max_daily_loss_usdt": 1.5,
                },
                {
                    "interval": "15m",
                    "variant": "quant_setup_selective",
                    "verdict": "negative_or_flat",
                    "trade_count": 60,
                    "net_pnl_usdt": -1.40156817,
                    "positive_window_rate": 0.33333333,
                    "worst_drawdown_usdt": 2.39698293,
                    "max_daily_loss_usdt": 1.5,
                },
            ],
            "variants": {
                "quant_setup_selective": {
                    "interval_count": 2,
                    "candidate_interval_count": 1,
                    "total_net_pnl_usdt": 0.2231175,
                    "worst_drawdown_usdt": 2.39698293,
                    "verdict": "drawdown_exceeds_pilot_cap",
                }
            },
        },
    }


class StrategyPromotionTests(unittest.TestCase):
    def write_report(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "matrix.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_negative_matrix_blocks_promotion(self):
        report = build_strategy_promotion_check_report(self.write_report(matrix_payload(promoted=False)))

        self.assertFalse(report.promotion_allowed)
        self.assertEqual(report.status, "keep_live_paused")
        self.assertIn("variant_not_promoted", report.reasons)
        self.assertIn("variant_total_net_pnl_not_positive", report.reasons)
        self.assertIn("5m:cell_not_promoted", report.reasons)

    def test_promoted_matrix_allows_promotion(self):
        report = build_strategy_promotion_check_report(self.write_report(matrix_payload(promoted=True)))

        self.assertTrue(report.promotion_allowed)
        self.assertEqual(report.status, "promotion_allowed")
        self.assertEqual(report.reasons, ["strategy_matrix_promoted"])
        self.assertTrue(report.live_resume_allowed)
        self.assertTrue(report.cell_checks[0].passed)

    def test_mixed_matrix_still_blocks_default_all_interval_scope(self):
        report = build_strategy_promotion_check_report(
            self.write_report(mixed_interval_matrix_payload()),
            variant="quant_setup_selective",
        )

        self.assertFalse(report.promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(report.scope, "all-intervals")
        self.assertIn("variant_not_promoted", report.reasons)
        self.assertIn("15m:cell_net_pnl_not_positive", report.reasons)

    def test_selected_interval_scope_allows_forward_paper_candidate_only(self):
        report = build_strategy_promotion_check_report(
            self.write_report(mixed_interval_matrix_payload()),
            variant="quant_setup_selective",
            scope="selected-intervals",
            intervals=["5m"],
        )

        self.assertTrue(report.promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(report.status, "forward_paper_allowed")
        self.assertEqual(report.scope, "selected-intervals")
        self.assertEqual(report.intervals, ["5m"])
        self.assertEqual(report.selected_summary["intervals"], ["5m"])
        self.assertEqual(report.selected_summary["trade_count"], 51)
        self.assertEqual(report.reasons, ["selected_intervals_promoted"])
        self.assertEqual(len(report.cell_checks), 1)
        self.assertEqual(report.cell_checks[0].interval, "5m")

    def test_selected_interval_scope_blocks_failed_selected_cell(self):
        report = build_strategy_promotion_check_report(
            self.write_report(mixed_interval_matrix_payload()),
            variant="quant_setup_selective",
            scope="selected-intervals",
            intervals=["15m"],
        )

        self.assertFalse(report.promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertIn("selected_intervals_total_net_pnl_not_positive", report.reasons)
        self.assertIn("15m:cell_not_promoted", report.reasons)

    def test_selected_interval_scope_requires_interval_list(self):
        report = build_strategy_promotion_check_report(
            self.write_report(mixed_interval_matrix_payload()),
            variant="quant_setup_selective",
            scope="selected-intervals",
        )

        self.assertFalse(report.promotion_allowed)
        self.assertIn("selected_intervals_required", report.reasons)

    def test_missing_report_is_invalid(self):
        report = build_strategy_promotion_check_report("missing-matrix.json")

        self.assertFalse(report.promotion_allowed)
        self.assertEqual(report.status, "invalid_report")
        self.assertEqual(report.reasons, ["matrix_report_missing"])


if __name__ == "__main__":
    unittest.main()
