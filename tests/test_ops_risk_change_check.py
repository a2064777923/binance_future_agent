import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.risk_change_check import (
    SubmittedIntentWithoutOutcome,
    risk_change_check_from_live_status,
    unreconciled_submitted_intents,
)


def report(*, positions=None, open_orders=None, open_algo_orders=None, protective_complete=False, backoff=False):
    return LiveStatusReport(
        db_path=":memory:",
        runtime_dir="/tmp",
        counts={},
        latest={},
        openai_backoff=OpenAiBackoffStatus(active=backoff),
        protective_evidence=ProtectiveEvidence(
            complete=protective_complete,
            status="entry_with_stop_loss_and_take_profit" if protective_complete else "missing",
        ),
        lva05_complete=protective_complete,
        exchange_evidence={
            "account": {"available_balance": "30"},
            "positions": [] if positions is None else positions,
            "open_orders": [] if open_orders is None else open_orders,
            "open_algo_orders": [] if open_algo_orders is None else open_algo_orders,
        },
    )


class RiskChangeCheckTests(unittest.TestCase):
    def test_allows_risk_change_when_exchange_clear_and_outcomes_reconciled(self):
        result = risk_change_check_from_live_status(
            report(),
            unreconciled_submitted_intents=[],
            target_leverage=8,
            current_max_leverage=5,
        )

        self.assertTrue(result.risk_change_allowed)
        self.assertEqual(result.status, "risk_change_allowed")
        self.assertEqual(result.reasons, ["exchange_clear_and_outcomes_reconciled"])
        self.assertEqual(result.target_leverage, 8)
        self.assertEqual(result.current_max_leverage, 5)

    def test_blocks_risk_change_when_position_is_open_even_if_protected(self):
        result = risk_change_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01"}],
                open_algo_orders=[{"symbol": "BNBUSDT", "clientAlgoId": "bfa-bnbusdt-sl"}],
                protective_complete=True,
            )
        )

        self.assertFalse(result.risk_change_allowed)
        self.assertEqual(result.status, "keep_current_profile")
        self.assertIn("active_position_present", result.reasons)
        self.assertIn("position_has_algo_protection", result.reasons)

    def test_requires_attention_for_orphan_orders(self):
        result = risk_change_check_from_live_status(report(open_orders=[{"symbol": "BNBUSDT"}]))

        self.assertFalse(result.risk_change_allowed)
        self.assertEqual(result.status, "urgent_attention")
        self.assertIn("open_orders_without_position", result.reasons)

    def test_blocks_risk_change_when_submitted_intent_lacks_outcome(self):
        missing = SubmittedIntentWithoutOutcome(
            event_id=7,
            occurred_at="2026-06-20T03:43:09Z",
            symbol="BNBUSDT",
            side="BUY",
            quantity=0.01,
            leverage=5,
        )

        result = risk_change_check_from_live_status(
            report(),
            unreconciled_submitted_intents=[missing],
        )

        self.assertFalse(result.risk_change_allowed)
        self.assertEqual(result.status, "keep_current_profile")
        self.assertIn("submitted_intents_missing_outcomes", result.reasons)
        self.assertEqual(result.unreconciled_submitted_intents[0].symbol, "BNBUSDT")

    def test_unreconciled_submitted_intents_ignores_rejected_and_outcomed_intents(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T02:49:17Z",
            source="execution.live",
            symbol="ZECUSDT",
            ref_id="order_intent:ZECUSDT:2026-06-20T02:49:17Z",
            payload={
                "status": "submitted",
                "intent": {"symbol": "ZECUSDT", "side": "BUY", "quantity": 0.032, "leverage": 3},
            },
            event_type="order_intent",
        )
        submitted_event_id = connection.execute(
            "SELECT event_id FROM order_intents WHERE symbol = 'ZECUSDT'"
        ).fetchone()["event_id"]
        store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-20T03:29:50Z",
            source="binance_usdm",
            symbol="ZECUSDT",
            ref_id=f"outcome:{submitted_event_id}:closed",
            payload={"status": "closed"},
            event_type="outcome",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:43:09Z",
            source="execution.live",
            symbol="BNBUSDT",
            ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
            payload={
                "status": "submitted",
                "intent": {"symbol": "BNBUSDT", "side": "BUY", "quantity": 0.01, "leverage": 5},
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T04:04:06Z",
            source="execution.live",
            symbol="ADAUSDT",
            ref_id="order_intent:ADAUSDT:2026-06-20T04:04:06Z",
            payload={
                "status": "rejected",
                "intent": {"symbol": "ADAUSDT", "side": "BUY", "quantity": 61, "leverage": 5},
            },
            event_type="order_intent",
        )

        missing = unreconciled_submitted_intents(connection)

        self.assertEqual([item.symbol for item in missing], ["BNBUSDT"])


if __name__ == "__main__":
    unittest.main()
