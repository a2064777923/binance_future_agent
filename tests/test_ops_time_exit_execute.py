import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.ops.time_exit_execute import build_time_exit_execute_report


class FakeSignedClient:
    def __init__(self, *, close_sets_position_zero=True):
        self.orders = []
        self.cancelled_algo_symbols = []
        self.closed = False
        self.close_sets_position_zero = close_sets_position_zero

    def account(self):
        return {"availableBalance": "30", "totalWalletBalance": "30"}

    def position_risk(self):
        amount = "0" if self.closed else "0.01"
        return [
            {
                "symbol": "BNBUSDT",
                "positionAmt": amount,
                "positionSide": "LONG",
                "entryPrice": "581.47",
                "markPrice": "582.00",
                "unRealizedProfit": "0.0053",
            }
        ]

    def open_orders(self):
        return []

    def open_algo_orders(self):
        return [
            {"symbol": "BNBUSDT", "positionSide": "LONG"},
            {"symbol": "BNBUSDT", "positionSide": "LONG"},
        ]

    def new_order(self, **kwargs):
        self.orders.append(kwargs)
        self.closed = self.close_sets_position_zero
        return {"orderId": 42, "symbol": kwargs["symbol"], "side": kwargs["side"], "status": "NEW"}

    def cancel_all_open_algo_orders(self, symbol):
        self.cancelled_algo_symbols.append(symbol)
        return {"code": 200, "msg": "success", "symbol": symbol}


class TimeExitExecuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)
        self.store.insert_artifact(
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
                    "metadata": {"hold_time_minutes": 0},
                },
            },
            event_type="order_intent",
        )

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def config(self):
        return load_config(
            env={
                "BFA_MODE": "live",
                "BFA_POSITION_MODE": "hedge",
                "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
            }
        )

    def test_requires_confirmation_token_without_placing_order(self):
        fake = FakeSignedClient()

        report = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:20:00Z",
            signed_client=fake,
        )

        self.assertEqual(report.status, "confirmation_required")
        self.assertTrue(report.confirmation_required)
        self.assertFalse(report.exit_executed)
        self.assertTrue(report.expected_confirmation_token.startswith("TIME-EXIT-BNBUSDT-"))
        self.assertEqual(fake.orders, [])
        self.assertEqual(fake.cancelled_algo_symbols, [])

    def test_executes_close_and_cancels_algo_orders_with_matching_token(self):
        fake = FakeSignedClient()
        preview = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:20:00Z",
            signed_client=fake,
        )

        report = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=fake,
            confirm_token=preview.expected_confirmation_token,
        )

        self.assertEqual(report.status, "time_exit_submitted")
        self.assertTrue(report.exit_executed)
        self.assertEqual(fake.orders[0]["symbol"], "BNBUSDT")
        self.assertEqual(fake.orders[0]["side"], "SELL")
        self.assertEqual(fake.orders[0]["order_type"], "MARKET")
        self.assertEqual(fake.orders[0]["quantity"], 0.01)
        self.assertEqual(fake.orders[0]["position_side"], "LONG")
        self.assertFalse(fake.orders[0]["reduce_only"])
        self.assertEqual(fake.cancelled_algo_symbols, ["BNBUSDT"])
        self.assertGreaterEqual(report.execution.persisted["exchange_response"], 1)

    def test_defers_algo_cleanup_when_position_remains_nonzero_after_close_submission(self):
        fake = FakeSignedClient(close_sets_position_zero=False)
        preview = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:20:00Z",
            signed_client=fake,
        )

        report = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=fake,
            confirm_token=preview.expected_confirmation_token,
        )

        self.assertEqual(report.status, "time_exit_submitted_cleanup_deferred")
        self.assertTrue(report.exit_executed)
        self.assertEqual(len(fake.orders), 1)
        self.assertEqual(fake.cancelled_algo_symbols, [])
        self.assertEqual(report.execution.post_close_position_amt, 0.01)

    def test_blocks_confirmed_execution_with_now_override(self):
        fake = FakeSignedClient()
        preview = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:20:00Z",
            signed_client=fake,
        )

        report = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:21:00Z",
            signed_client=fake,
            confirm_token=preview.expected_confirmation_token,
        )

        self.assertEqual(report.status, "execution_blocked")
        self.assertIn("now_override_not_allowed_for_confirmed_execution", report.reasons)
        self.assertFalse(report.exit_executed)
        self.assertEqual(fake.orders, [])

    def test_blocks_when_live_service_is_active(self):
        fake = FakeSignedClient()

        report = build_time_exit_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:20:00Z",
            signed_client=fake,
            service_active=True,
        )

        self.assertEqual(report.status, "execution_blocked")
        self.assertIn("live_service_active", report.reasons)
        self.assertFalse(report.exit_executed)
        self.assertEqual(fake.orders, [])


if __name__ == "__main__":
    unittest.main()
