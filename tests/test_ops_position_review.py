import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.position_hold_check import position_hold_check_from_live_status
from bfa.ops.position_review import position_review_from_hold_check


def report(*, positions=None, open_orders=None, open_algo_orders=None, protective_complete=True):
    return LiveStatusReport(
        db_path=":memory:",
        runtime_dir="/tmp",
        counts={},
        latest={},
        openai_backoff=OpenAiBackoffStatus(active=False),
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


class PositionReviewTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def insert_submitted_intent(self, *, hold_time_minutes=60, stop_price=96, target_price=108):
        self.store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:00:00Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="order_intent:BTCUSDT:2026-06-20T03:00:00Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.2,
                    "entry_price": 100,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "leverage": 5,
                    "metadata": {"hold_time_minutes": hold_time_minutes},
                },
            },
            event_type="order_intent",
        )

    def hold_check(self, *, mark_price, checked_at="2026-06-20T03:20:00Z", protected=True, hold_time_minutes=60):
        self.insert_submitted_intent(hold_time_minutes=hold_time_minutes)
        algo_orders = [
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
        ] if protected else []
        return position_hold_check_from_live_status(
            report(
                positions=[
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.2",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": str(mark_price),
                        "unRealizedProfit": str((mark_price - 100) * 0.2),
                    }
                ],
                open_algo_orders=algo_orders,
                protective_complete=protected,
            ),
            connection=self.connection,
            checked_at=checked_at,
        )

    def test_recommends_trail_or_reduce_when_position_nears_target(self):
        review = position_review_from_hold_check(self.hold_check(mark_price=107), review_interval_minutes=15)

        item = review.positions[0]
        self.assertFalse(review.action_required)
        self.assertEqual(review.status, "review_ok")
        self.assertEqual(item.recommendation, "trail_or_reduce")
        self.assertIn("near_target", item.reasons)
        self.assertAlmostEqual(item.target_progress, 0.875)
        self.assertAlmostEqual(item.stop_r_multiple, 1.75)

    def test_recommends_close_review_when_hold_time_expired(self):
        review = position_review_from_hold_check(
            self.hold_check(mark_price=101, checked_at="2026-06-20T04:10:00Z", hold_time_minutes=30),
        )

        item = review.positions[0]
        self.assertTrue(review.action_required)
        self.assertEqual(review.status, "review_required")
        self.assertEqual(item.recommendation, "close_review")
        self.assertEqual(item.urgency, "high")
        self.assertIn("hold_time_expired", item.reasons)

    def test_recommends_close_review_for_unprotected_position(self):
        review = position_review_from_hold_check(self.hold_check(mark_price=101, protected=False))

        item = review.positions[0]
        self.assertTrue(review.action_required)
        self.assertEqual(review.status, "urgent_attention")
        self.assertEqual(item.recommendation, "close_review")
        self.assertEqual(item.urgency, "urgent")
        self.assertIn("unprotected_position", item.reasons)


if __name__ == "__main__":
    unittest.main()
