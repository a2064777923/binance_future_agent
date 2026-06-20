import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.position_hold_check import position_hold_check_from_live_status


def report(*, positions=None, open_orders=None, open_algo_orders=None, protective_complete=True, backoff=False):
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


class PositionHoldCheckTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def insert_submitted_intent(self, *, hold_time_minutes=60):
        return self.store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:43:09Z",
            source="execution.live",
            symbol="BNBUSDT",
            ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BNBUSDT",
                    "side": "BUY",
                    "quantity": 0.01,
                    "entry_price": 581.47,
                    "leverage": 5,
                    "metadata": {"hold_time_minutes": hold_time_minutes},
                },
            },
            event_type="order_intent",
        )

    def test_reports_within_hold_window_when_position_is_protected(self):
        self.insert_submitted_intent(hold_time_minutes=60)

        result = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=[
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ],
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertFalse(result.action_required)
        self.assertEqual(result.status, "within_hold_window")
        self.assertEqual(result.positions[0].matching_intent.event_id, 1)
        self.assertFalse(result.positions[0].overdue)
        self.assertAlmostEqual(result.positions[0].elapsed_minutes, 16.85)

    def test_flags_review_required_when_hold_time_expired(self):
        self.insert_submitted_intent(hold_time_minutes=30)

        result = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=[
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ],
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:20:00Z",
        )

        self.assertTrue(result.action_required)
        self.assertEqual(result.status, "review_required")
        self.assertIn("hold_time_expired", result.reasons)
        self.assertTrue(result.positions[0].overdue)

    def test_requires_urgent_attention_without_algo_protection(self):
        self.insert_submitted_intent(hold_time_minutes=60)

        result = position_hold_check_from_live_status(
            report(positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}]),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertTrue(result.action_required)
        self.assertEqual(result.status, "urgent_attention")
        self.assertIn("active_position_without_confirmed_algo_protection", result.reasons)

    def test_missing_exchange_evidence_is_action_required(self):
        missing_exchange = LiveStatusReport(
            db_path=":memory:",
            runtime_dir="/tmp",
            counts={},
            latest={},
            openai_backoff=OpenAiBackoffStatus(active=False),
            protective_evidence=ProtectiveEvidence(complete=False),
            lva05_complete=False,
            exchange_evidence={},
        )

        result = position_hold_check_from_live_status(
            missing_exchange,
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertTrue(result.action_required)
        self.assertEqual(result.status, "keep_current_profile")
        self.assertIn("exchange_evidence_missing", result.reasons)


if __name__ == "__main__":
    unittest.main()
