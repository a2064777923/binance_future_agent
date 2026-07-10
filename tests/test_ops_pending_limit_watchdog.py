import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceSignedError
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_order_intent
from bfa.ops.pending_limit_watchdog import build_pending_limit_watchdog_report, execute_pending_limit_watchdog


class FakePendingLimitClient:
    def __init__(
        self,
        *,
        order_status="FILLED",
        executed_qty="0.2",
        protected=False,
        active_position=True,
        cancel_fails=False,
    ):
        self.order_status = order_status
        self.executed_qty = executed_qty
        self.protected = protected
        self.active_position = active_position
        self.calls = []
        self.algo_orders = []
        self.cancel_fails = cancel_fails

    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        return {
            "symbol": kwargs.get("symbol"),
            "status": self.order_status,
            "executedQty": self.executed_qty,
            "avgPrice": "100",
        }

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        if self.active_position:
            return [
                {
                    "symbol": symbol or "BTCUSDT",
                    "positionAmt": self.executed_qty,
                    "positionSide": "LONG",
                    "entryPrice": "100",
                    "markPrice": "100.5",
                }
            ]
        return []

    def open_algo_orders(self, symbol=None):
        self.calls.append(("open_algo_orders", symbol))
        if not self.protected:
            return []
        return [
            {"symbol": symbol, "type": "STOP_MARKET", "triggerPrice": "96"},
            {"symbol": symbol, "type": "TAKE_PROFIT_MARKET", "triggerPrice": "108"},
        ]

    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        self.algo_orders.append(kwargs)
        return {"algoId": 100 + len(self.algo_orders), **kwargs}

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        if self.cancel_fails:
            raise BinanceSignedError(
                endpoint="/fapi/v1/order",
                params={},
                status_code=500,
                binance_code=-1000,
                binance_message="synthetic cancel failure",
                headers={},
            )
        return {
            "symbol": kwargs.get("symbol"),
            "status": "CANCELED",
            "origClientOrderId": kwargs.get("orig_client_order_id"),
        }


class PendingLimitWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        connection = sqlite3.connect(self.db_path)
        try:
            store = EventStore(connection)
            persist_order_intent(
                store,
                intent=OrderIntent(
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=0.2,
                    notional_usdt=20.0,
                    entry_price=100.0,
                    stop_price=96.0,
                    target_price=108.0,
                    leverage=10,
                    mode="live",
                    decided_at="2026-06-20T09:00:00Z",
                    order_type="LIMIT",
                    time_in_force="GTX",
                    limit_wait_seconds=20,
                    metadata={"client_order_id": "bfa-btc-pending-1"},
                ),
                status="entry_order_pending",
                risk=RiskDecision(True, ["risk_accepted"]),
            )
        finally:
            connection.close()

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **overrides):
        env = {
            "BFA_MODE": "live",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
            "BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED": "false",
            "BFA_DB_PATH": str(self.db_path),
        }
        env.update(overrides)
        return load_config(env)

    def exchange_response_count(self):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM exchange_responses").fetchone()[0]
        finally:
            connection.close()

    def pending_row(self):
        connection = connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT * FROM pending_limit_entries ORDER BY intent_event_id ASC LIMIT 1"
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    def test_observe_mode_detects_filled_unprotected_without_placing_orders(self):
        client = FakePendingLimitClient()

        report = build_pending_limit_watchdog_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=False,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_action_ready")
        self.assertFalse(report.execution_enabled)
        self.assertFalse(report.action_taken)
        self.assertEqual(report.items[0].status, "filled_unprotected")
        self.assertEqual(report.items[0].action, "place_protective_orders_pending")
        self.assertEqual(client.algo_orders, [])
        self.assertEqual(self.exchange_response_count(), 0)

    def test_execute_mode_backfills_stop_and_take_profit(self):
        client = FakePendingLimitClient()

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_protected")
        self.assertTrue(report.execution_enabled)
        self.assertTrue(report.action_taken)
        self.assertEqual(report.protected_count, 1)
        self.assertEqual(report.items[0].status, "position_reconciled_protected")
        self.assertEqual([order["order_type"] for order in client.algo_orders], ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
        self.assertGreaterEqual(self.exchange_response_count(), 1)

    def test_execute_flag_without_env_permission_stays_observe_only(self):
        client = FakePendingLimitClient()

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="false"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_action_ready")
        self.assertIn("execution_not_enabled_by_config", report.reasons)
        self.assertEqual(client.algo_orders, [])

    def test_filled_order_without_current_position_never_backfills_protection(self):
        client = FakePendingLimitClient(active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_checked")
        self.assertTrue(report.execution_enabled)
        self.assertEqual(report.items[0].status, "filled_without_active_position")
        self.assertEqual(report.items[0].action, "mark_resolved")
        self.assertIn("no_matching_active_position", report.items[0].reasons)
        self.assertEqual(client.algo_orders, [])
        self.assertGreaterEqual(self.exchange_response_count(), 1)

    def test_new_unfilled_order_is_not_reconciled_from_sibling_position(self):
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=True)

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_checked")
        self.assertEqual(report.items[0].status, "still_pending")
        self.assertEqual(report.items[0].action, "watch")
        self.assertIn("pending_limit_not_filled", report.items[0].reasons)
        self.assertEqual(client.algo_orders, [])
        self.assertEqual(self.exchange_response_count(), 0)

    def test_expired_new_order_observe_mode_requests_cancel_without_mutating(self):
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:21Z",
            execute=False,
        )

        self.assertEqual(report.items[0].status, "expired_cancel_pending")
        self.assertEqual(report.items[0].action, "cancel_order_pending")
        self.assertFalse(any(call[0] == "cancel_order" for call in client.calls))
        self.assertEqual(self.pending_row()["status"], "pending")

    def test_expired_new_order_execute_mode_cancels_and_resolves(self):
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:21Z",
            execute=True,
        )

        self.assertEqual(report.items[0].status, "expired_canceled")
        self.assertEqual(report.items[0].action, "cancel_order")
        self.assertEqual(sum(call[0] == "cancel_order" for call in client.calls), 1)
        row = self.pending_row()
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["resolution_status"], "entry_order_expired_canceled")

    def test_partial_fill_cancels_remainder_before_protecting_executed_quantity(self):
        client = FakePendingLimitClient(order_status="PARTIALLY_FILLED", executed_qty="0.1")

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:10Z",
            execute=True,
        )

        self.assertEqual(report.items[0].status, "partial_filled_protected")
        call_names = [call[0] for call in client.calls]
        self.assertLess(call_names.index("cancel_order"), call_names.index("new_algo_order"))
        self.assertEqual(client.algo_orders[0]["order_type"], "STOP_MARKET")
        self.assertEqual(self.pending_row()["status"], "resolved")

    def test_cancel_failure_is_fail_closed_and_keeps_pending_unresolved(self):
        client = FakePendingLimitClient(
            order_status="NEW",
            executed_qty="0",
            active_position=False,
            cancel_fails=True,
        )

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:21Z",
            execute=True,
        )

        self.assertEqual(report.items[0].status, "expired_cancel_failed")
        self.assertEqual(report.status, "pending_limit_watchdog_check_failed")
        self.assertEqual(self.pending_row()["status"], "pending")

    def test_max_items_processes_earliest_expiry_without_scanning_history(self):
        connection = connect(self.db_path)
        try:
            store = EventStore(connection)
            persist_order_intent(
                store,
                intent=OrderIntent(
                    symbol="ETHUSDT",
                    side="SELL",
                    quantity=1,
                    notional_usdt=100,
                    entry_price=100,
                    stop_price=102,
                    target_price=96,
                    leverage=10,
                    mode="live",
                    decided_at="2026-06-20T09:00:10Z",
                    order_type="LIMIT",
                    time_in_force="GTX",
                    limit_wait_seconds=60,
                    metadata={"client_order_id": "bfa-eth-pending-2"},
                ),
                status="entry_order_pending",
                risk=RiskDecision(True, ["risk_accepted"]),
            )
            for index in range(100):
                store.insert_artifact(
                    "order_intents",
                    occurred_at=f"2026-06-19T00:00:{index % 60:02d}Z",
                    source="test",
                    symbol="NOISEUSDT",
                    ref_id=f"noise:{index}",
                    payload={"status": "rejected", "intent": {}},
                    event_type="order_intent",
                )
        finally:
            connection.close()
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = execute_pending_limit_watchdog(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:15Z",
            max_items=1,
            execute_protective_orders=True,
        )

        self.assertEqual(report.checked_count, 1)
        self.assertEqual(report.items[0].symbol, "BTCUSDT")
        self.assertEqual(sum(call[0] == "query_order" for call in client.calls), 1)


if __name__ == "__main__":
    unittest.main()
