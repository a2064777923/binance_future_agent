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
        self.assertTrue(report.cell_checks[0].passed)

    def test_missing_report_is_invalid(self):
        report = build_strategy_promotion_check_report("missing-matrix.json")

        self.assertFalse(report.promotion_allowed)
        self.assertEqual(report.status, "invalid_report")
        self.assertEqual(report.reasons, ["matrix_report_missing"])


if __name__ == "__main__":
    unittest.main()
