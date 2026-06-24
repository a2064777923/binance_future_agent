import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.position_hold_check import position_hold_check_from_live_status, time_exit_plan_from_hold_check


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


def protective_algo_orders(symbol="BNBUSDT", position_side="LONG"):
    return [
        {"symbol": symbol, "positionSide": position_side, "type": "STOP_MARKET", "triggerPrice": "575.0"},
        {"symbol": symbol, "positionSide": position_side, "type": "TAKE_PROFIT_MARKET", "triggerPrice": "593.0"},
    ]


class PositionHoldCheckTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def insert_submitted_intent(self, *, hold_time_minutes=60, status="submitted"):
        return self.store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:43:09Z",
            source="execution.live",
            symbol="BNBUSDT",
            ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
            payload={
                "status": status,
                "intent": {
                    "symbol": "BNBUSDT",
                    "side": "BUY",
                    "quantity": 0.01,
                    "entry_price": 581.47,
                    "stop_price": 575.0,
                    "target_price": 593.0,
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
                open_algo_orders=protective_algo_orders(),
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertFalse(result.action_required)
        self.assertEqual(result.status, "within_hold_window")
        self.assertEqual(result.positions[0].matching_intent.event_id, 1)
        self.assertEqual(result.positions[0].matching_intent.stop_price, 575.0)
        self.assertEqual(result.positions[0].matching_intent.target_price, 593.0)
        self.assertFalse(result.positions[0].overdue)
        self.assertAlmostEqual(result.positions[0].elapsed_minutes, 16.85)

    def test_flags_review_required_when_hold_time_expired(self):
        self.insert_submitted_intent(hold_time_minutes=30)

        result = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=protective_algo_orders(),
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

    def test_pending_entry_order_intent_matches_filled_position(self):
        self.insert_submitted_intent(hold_time_minutes=60, status="entry_order_pending")

        result = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=protective_algo_orders(),
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertEqual(result.status, "within_hold_window")
        self.assertEqual(result.positions[0].matching_intent.event_id, 1)
        self.assertNotIn("active_position_without_matching_submitted_intent", result.reasons)

    def test_duplicate_stop_orders_do_not_count_as_complete_protection(self):
        self.insert_submitted_intent(hold_time_minutes=60)

        result = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=[
                    {"symbol": "BNBUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "triggerPrice": "575.0"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG", "type": "STOP_MARKET", "triggerPrice": "574.0"},
                ],
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        self.assertEqual(result.status, "urgent_attention")
        self.assertEqual(result.positions[0].algo_protection_count, 1)
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

    def test_time_exit_plan_ready_for_overdue_protected_long_in_hedge_mode(self):
        self.insert_submitted_intent(hold_time_minutes=30)
        hold_check = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=protective_algo_orders(),
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:20:00Z",
        )

        result = time_exit_plan_from_hold_check(hold_check, position_mode="hedge")

        self.assertTrue(result.exit_allowed)
        self.assertEqual(result.status, "exit_plan_ready")
        self.assertEqual(result.plans[0].order_plan.symbol, "BNBUSDT")
        self.assertEqual(result.plans[0].order_plan.side, "SELL")
        self.assertEqual(result.plans[0].order_plan.order_type, "MARKET")
        self.assertEqual(result.plans[0].order_plan.quantity, 0.01)
        self.assertEqual(result.plans[0].order_plan.position_side, "LONG")
        self.assertFalse(result.plans[0].order_plan.reduce_only)

    def test_time_exit_plan_blocked_before_hold_time_expires(self):
        self.insert_submitted_intent(hold_time_minutes=60)
        hold_check = position_hold_check_from_live_status(
            report(
                positions=[{"symbol": "BNBUSDT", "positionAmt": "0.01", "positionSide": "LONG"}],
                open_algo_orders=protective_algo_orders(),
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:00:00Z",
        )

        result = time_exit_plan_from_hold_check(hold_check, position_mode="hedge")

        self.assertFalse(result.exit_allowed)
        self.assertEqual(result.status, "exit_plan_blocked")
        self.assertIn("hold_time_not_expired", result.plans[0].reasons)


if __name__ == "__main__":
    unittest.main()
