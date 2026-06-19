import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.ops.live_status import build_live_status_report


class OpsLiveStatusTests(unittest.TestCase):
    def config(self, root):
        return load_config(
            {
                "BFA_DB_PATH": str(root / "agent.sqlite"),
                "BFA_RUNTIME_DIR": str(root / "runtime"),
            }
        )

    def intent(self):
        return OrderIntent(
            symbol="SOLUSDT",
            side="BUY",
            quantity=0.2,
            notional_usdt=20.0,
            entry_price=100.0,
            stop_price=96.0,
            target_price=108.0,
            leverage=3,
            mode="live",
            decided_at="2026-06-20T10:00:00Z",
        )

    def test_empty_status_reports_no_protective_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = build_live_status_report(self.config(root), now_epoch=100)

        payload = report.to_dict()
        self.assertFalse(payload["lva05_complete"])
        self.assertFalse(payload["openai_backoff"]["active"])
        self.assertEqual(payload["counts"]["order_intents"], 0)
        self.assertIsNone(payload["latest"]["order_intent"])

    def test_reports_openai_backoff_and_protective_order_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "openai_backoff.json").write_text(
                json.dumps(
                    {
                        "retry_after_epoch": 200,
                        "retry_after": "2026-06-20T10:05:00Z",
                        "reason": "openai_error:TimeoutError",
                    }
                ),
                encoding="utf-8",
            )
            connection = sqlite3.connect(root / "agent.sqlite")
            connection.row_factory = sqlite3.Row
            store = EventStore(connection)
            intent = self.intent()
            persist_order_intent(
                store,
                intent=intent,
                status="submitted",
                risk=RiskDecision(True, ["risk_accepted"]),
            )
            persist_exchange_response(
                store,
                intent=intent,
                response={
                    "entry_order": {"orderId": 1},
                    "stop_loss_order": {"algoId": 2},
                    "take_profit_order": {"algoId": 3},
                },
            )
            connection.close()

            report = build_live_status_report(self.config(root), now_epoch=100)

        payload = report.to_dict()
        self.assertTrue(payload["openai_backoff"]["active"])
        self.assertEqual(payload["counts"]["submitted_order_intents"], 1)
        self.assertTrue(payload["lva05_complete"])
        self.assertEqual(
            payload["protective_evidence"]["status"],
            "entry_with_stop_loss_and_take_profit",
        )
        self.assertTrue(payload["protective_evidence"]["details"]["has_entry_order"])
        self.assertTrue(payload["protective_evidence"]["details"]["has_stop_loss_order"])
        self.assertTrue(payload["protective_evidence"]["details"]["has_take_profit_order"])


if __name__ == "__main__":
    unittest.main()
