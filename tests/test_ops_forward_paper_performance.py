import tempfile
import unittest
from pathlib import Path

from bfa.event_store.store import EventStore
from bfa.ops.forward_paper_performance import build_forward_paper_performance_report


def signal_payload(symbol, event_id_suffix, *, opened_at):
    return {
        "schema": "bfa_paper_signal_v1",
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": opened_at,
        "expiry_time": opened_at,
        "side": "long",
        "entry_price": 100.0,
        "stop_price": 98.0,
        "target_price": 104.0,
        "notional_usdt": 12.0,
        "hold_bars": 4,
        "status": "open",
        "setup": {"id": event_id_suffix},
    }


def outcome_payload(signal_event_id, symbol, pnl, *, closed_at, exit_reason="take_profit"):
    return {
        "schema": "bfa_paper_outcome_v1",
        "signal_event_id": signal_event_id,
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": "2026-06-20T00:00:00Z",
        "closed_at": closed_at,
        "side": "long",
        "entry_price": 100.0,
        "exit_price": 104.0 if pnl > 0 else 98.0,
        "quantity": 0.12,
        "notional_usdt": 12.0,
        "gross_pnl_usdt": pnl,
        "fees_usdt": 0.0,
        "slippage_usdt": 0.0,
        "net_pnl_usdt": pnl,
        "exit_reason": exit_reason,
    }


class ForwardPaperPerformanceTests(unittest.TestCase):
    def make_db(self, pnls):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "paper.sqlite"
        from bfa.event_store.migrations import connect

        connection = connect(db)
        store = EventStore(connection)
        signal_ids = []
        for index, pnl in enumerate(pnls):
            symbol = "AAAUSDT" if index % 2 == 0 else "BBBUSDT"
            opened_at = f"2026-06-20T00:{index:02d}:00Z"
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=opened_at,
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload=signal_payload(symbol, index, opened_at=opened_at),
            )
            signal_ids.append(signal_id)
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:{index:02d}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(
                    signal_id,
                    symbol,
                    pnl,
                    closed_at=f"2026-06-20T01:{index:02d}:00Z",
                    exit_reason="take_profit" if pnl > 0 else "stop_loss",
                ),
            )
        connection.close()
        return db

    def test_promising_paper_evidence_passes_paper_gate_not_live_resume(self):
        db = self.make_db([0.2, -0.05, 0.18, 0.1, -0.04])

        report = build_forward_paper_performance_report(
            str(db),
            min_outcomes=5,
            min_win_rate=0.5,
            min_net_pnl_usdt=0.0,
            max_worst_drawdown_usdt=1.5,
        )

        payload = report.to_dict()
        self.assertEqual(report.status, "paper_evidence_promising")
        self.assertTrue(report.paper_promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(payload["summary"]["outcome_count"], 5)
        self.assertEqual(payload["summary"]["win_rate"], 0.6)
        self.assertGreater(payload["summary"]["total_net_pnl_usdt"], 0)
        self.assertEqual(payload["reasons"], ["paper_thresholds_passed"])

    def test_insufficient_outcomes_keep_live_paused(self):
        db = self.make_db([0.2, 0.1])

        report = build_forward_paper_performance_report(str(db), min_outcomes=5)

        self.assertEqual(report.status, "insufficient_paper_evidence")
        self.assertFalse(report.paper_promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertIn("paper_outcome_count_below_min", report.reasons)

    def test_enough_bad_outcomes_keep_live_paused_with_metrics(self):
        db = self.make_db([0.2, -0.4, -0.1, 0.05, -0.2])

        report = build_forward_paper_performance_report(
            str(db),
            min_outcomes=5,
            min_win_rate=0.5,
            min_net_pnl_usdt=0.0,
            max_worst_drawdown_usdt=0.3,
        )

        payload = report.to_dict()
        self.assertEqual(report.status, "keep_live_paused")
        self.assertFalse(report.paper_promotion_allowed)
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(payload["summary"]["outcome_count"], 5)
        self.assertEqual(payload["summary"]["win_rate"], 0.4)
        self.assertLess(payload["summary"]["total_net_pnl_usdt"], 0)
        self.assertGreaterEqual(payload["summary"]["worst_drawdown_usdt"], 0.3)
        self.assertIn("paper_total_net_pnl_not_above_min", report.reasons)
        self.assertIn("paper_win_rate_below_min", report.reasons)
        self.assertIn("paper_worst_drawdown_exceeds_cap", report.reasons)

    def test_no_signals_reports_no_paper_evidence(self):
        db = self.make_db([])

        report = build_forward_paper_performance_report(str(db), min_outcomes=1)

        self.assertEqual(report.status, "no_paper_evidence")
        self.assertIn("paper_signals_missing", report.reasons)


if __name__ == "__main__":
    unittest.main()
