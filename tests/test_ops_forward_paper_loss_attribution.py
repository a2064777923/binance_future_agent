import tempfile
import unittest
from pathlib import Path

from bfa.event_store.store import EventStore
from bfa.ops.forward_paper_loss_attribution import build_forward_paper_loss_attribution_report


def setup_payload(*, symbol, side, reasons, warnings=None, factor_reasons=None, negative_factor="momentum"):
    return {
        "symbol": symbol,
        "decision": "trade",
        "side": side,
        "confidence": 0.72,
        "edge_score": 35.0,
        "risk_reward_ratio": 1.5,
        "reasons": reasons,
        "warnings": warnings or [],
        "factor_scores": [
            {
                "name": negative_factor,
                "value": -1.0,
                "score": -10.0,
                "weight": 1.0,
                "weighted_score": -10.0,
                "reasons": factor_reasons or ["ema_trend_down"],
            }
        ],
    }


def signal_payload(symbol, *, side="short", reasons=None, warnings=None):
    return {
        "schema": "bfa_paper_signal_v1",
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": "2026-06-20T00:00:00Z",
        "expiry_time": "2026-06-20T00:20:00Z",
        "side": side,
        "entry_price": 100.0,
        "stop_price": 102.0,
        "target_price": 96.0,
        "notional_usdt": 12.0,
        "hold_bars": 4,
        "status": "open",
        "setup": setup_payload(
            symbol=symbol,
            side=side,
            reasons=reasons or ["quant_short_setup", "ema_trend_down"],
            warnings=warnings,
        ),
    }


def outcome_payload(signal_event_id, symbol, pnl, *, side="short", exit_reason="stop_loss"):
    return {
        "schema": "bfa_paper_outcome_v1",
        "signal_event_id": signal_event_id,
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": "2026-06-20T00:00:00Z",
        "closed_at": "2026-06-20T00:20:00Z",
        "side": side,
        "entry_price": 100.0,
        "exit_price": 102.0 if pnl < 0 else 96.0,
        "quantity": 0.12,
        "notional_usdt": 12.0,
        "gross_pnl_usdt": pnl,
        "fees_usdt": 0.0,
        "slippage_usdt": 0.0,
        "net_pnl_usdt": pnl,
        "exit_reason": exit_reason,
    }


class ForwardPaperLossAttributionTests(unittest.TestCase):
    def make_db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "paper.sqlite"
        from bfa.event_store.migrations import connect

        connection = connect(db)
        store = EventStore(connection)
        rows = [
            ("BICOUSDT", -0.30, "short", "stop_loss", ["crowding_risk"]),
            ("BICOUSDT", -0.25, "short", "stop_loss", ["crowding_risk"]),
            ("SOLUSDT", 0.12, "long", "take_profit", []),
        ]
        for index, (symbol, pnl, side, exit_reason, warnings) in enumerate(rows):
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=f"2026-06-20T00:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload=signal_payload(symbol, side=side, warnings=warnings),
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(signal_id, symbol, pnl, side=side, exit_reason=exit_reason),
            )
        connection.close()
        return db

    def test_loss_attribution_ranks_losing_groups_and_candidates(self):
        report = build_forward_paper_loss_attribution_report(str(self.make_db()), min_group_outcomes=1)

        payload = report.to_dict()
        self.assertEqual(report.status, "loss_attribution_ready")
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(payload["schema"], "bfa_forward_paper_loss_attribution_v1")
        self.assertEqual(payload["summary"]["outcome_count"], 3)
        self.assertEqual(payload["summary"]["total_net_pnl_usdt"], -0.43)
        self.assertEqual(payload["worst_groups"]["symbols"][0]["name"], "BICOUSDT")
        self.assertEqual(payload["worst_groups"]["sides"][0]["name"], "short")
        self.assertEqual(payload["worst_groups"]["exit_reasons"][0]["name"], "stop_loss")
        self.assertTrue(any(item["name"] == "crowding_risk" for item in payload["worst_groups"]["setup_warnings"]))
        self.assertTrue(any(item["action"] == "quarantine_or_reduce_symbol" for item in payload["recalibration_candidates"]))

    def test_empty_db_reports_no_paper_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            report = build_forward_paper_loss_attribution_report(str(db))

        self.assertEqual(report.status, "no_paper_evidence")
        self.assertFalse(report.live_resume_allowed)
        self.assertIn("paper_signals_missing", report.reasons)


if __name__ == "__main__":
    unittest.main()
