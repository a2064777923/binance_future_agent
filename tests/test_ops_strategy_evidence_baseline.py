import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.ops.strategy_evidence_baseline import build_strategy_evidence_baseline_report


def signal_payload(symbol, *, side="short", reasons=None, factor_reason="taker_flow_acceleration"):
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
        "setup": {
            "side": side,
            "reasons": reasons or ["quant_short_setup"],
            "warnings": [],
            "factor_scores": [
                {
                    "name": "taker_flow",
                    "weighted_score": -8.0,
                    "reasons": [factor_reason],
                }
            ],
        },
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


class StrategyEvidenceBaselineTests(unittest.TestCase):
    def make_db(self, pnls):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "paper.sqlite"
        connection = connect(db)
        store = EventStore(connection)
        for index, pnl in enumerate(pnls):
            symbol = "BTWUSDT" if index < 3 else "SOLUSDT"
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=f"2026-06-20T00:{index:02d}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload=signal_payload(symbol),
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:{index:02d}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(signal_id, symbol, pnl),
            )
        connection.close()
        return db

    def test_baseline_groups_negative_strategy_evidence_and_read_only_guarantees(self):
        db = self.make_db([-0.3, -0.25, -0.2, 0.1])

        report = build_strategy_evidence_baseline_report(
            load_config(env={"BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES": "4"}),
            db_path=str(db),
            min_outcomes=4,
            min_win_rate=0.5,
            min_net_pnl_usdt=0.0,
            max_worst_drawdown_usdt=0.2,
            check_systemd=False,
            server_state_overrides={
                "paper.timer": "active",
                "live.timer": "inactive",
                "live.service": "inactive",
            },
            exchange_state="clear",
        )

        payload = report.to_dict()
        self.assertEqual(report.status, "keep_live_paused")
        self.assertFalse(report.live_resume_allowed)
        self.assertIn("paper_total_net_pnl_not_above_min", payload["reasons"]["strategy_evidence"])
        self.assertIn("paper_win_rate_below_min", payload["reasons"]["strategy_evidence"])
        self.assertEqual(payload["reasons"]["server_state"], [])
        self.assertEqual(payload["reasons"]["exchange_state"], [])
        self.assertEqual(payload["reasons"]["confirmation"], ["operator_confirmation_required"])
        self.assertEqual(payload["performance"]["summary"]["outcome_count"], 4)
        self.assertEqual(payload["loss_attribution"]["worst_groups"]["symbols"][0]["name"], "BTWUSDT")
        self.assertFalse(payload["read_only"]["creates_order_intents"])
        self.assertFalse(payload["read_only"]["changes_systemd_state"])

    def test_baseline_reports_server_and_manual_exchange_blockers(self):
        db = self.make_db([0.3, 0.2])

        report = build_strategy_evidence_baseline_report(
            load_config(env={}),
            db_path=str(db),
            min_outcomes=2,
            min_win_rate=0.5,
            min_net_pnl_usdt=0.0,
            max_worst_drawdown_usdt=1.5,
            check_systemd=False,
            server_state_overrides={
                "paper.timer": "inactive",
                "live.timer": "active",
                "live.service": "active",
            },
            exchange_state="manual_exposure",
            manual_exposure_symbols=["ethusdt"],
        )

        payload = report.to_dict()
        self.assertFalse(report.live_resume_allowed)
        self.assertIn("paper_timer_not_active_or_unknown", payload["reasons"]["server_state"])
        self.assertIn("live_timer_already_active", payload["reasons"]["server_state"])
        self.assertIn("live_service_currently_active", payload["reasons"]["server_state"])
        self.assertEqual(payload["reasons"]["exchange_state"], ["manual_exchange_exposure_present"])
        self.assertEqual(payload["exchange_state"]["manual_exposure_symbols"], ["ETHUSDT"])
        self.assertFalse(payload["exchange_state"]["manual_exposure_is_agent_evidence"])


if __name__ == "__main__":
    unittest.main()
