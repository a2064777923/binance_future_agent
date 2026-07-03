import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_order_intent
from bfa.ops.pending_limit_watchdog import build_pending_limit_watchdog_report


class FakePendingLimitClient:
    def __init__(self, *, order_status="FILLED", executed_qty="0.2", protected=False, active_position=True):
        self.order_status = order_status
        self.executed_qty = executed_qty
        self.protected = protected
        self.active_position = active_position
        self.calls = []
        self.algo_orders = []
        self.new_orders = []

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

    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        self.new_orders.append(kwargs)
        return {"orderId": 200 + len(self.new_orders), "status": "NEW", **kwargs}

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        return {"symbol": kwargs.get("symbol"), "status": "CANCELED", "executedQty": "0", **kwargs}


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

    def insert_pending_intent(self, intent: OrderIntent, *, status="entry_order_pending"):
        connection = sqlite3.connect(self.db_path)
        try:
            store = EventStore(connection)
            persist_order_intent(store, intent=intent, status=status, risk=RiskDecision(True, ["risk_accepted"]))
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

    def test_execute_mode_cancels_partial_entry_remainder_before_protection(self):
        client = FakePendingLimitClient(order_status="PARTIALLY_FILLED", executed_qty="0.2")

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:05Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_protected")
        self.assertEqual(report.items[0].status, "position_reconciled_protected")
        self.assertIn("pending_limit_partial_entry_remainder_canceled", report.items[0].reasons)
        call_names = [call[0] for call in client.calls]
        self.assertLess(call_names.index("cancel_order"), call_names.index("open_algo_orders"))
        self.assertLess(call_names.index("cancel_order"), call_names.index("new_algo_order"))
        self.assertIn(("cancel_order", {"symbol": "BTCUSDT", "orig_client_order_id": "bfa-btc-pending-1"}), client.calls)

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

    def test_execute_mode_cancels_unfilled_order_after_limit_wait_seconds(self):
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:21Z",
            execute=True,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_resolved")
        self.assertEqual(report.items[0].status, "terminal_no_fill")
        self.assertEqual(report.items[0].action, "mark_resolved")
        self.assertIn(("cancel_order", {"symbol": "BTCUSDT", "orig_client_order_id": "bfa-btc-pending-1"}), client.calls)
        self.assertGreaterEqual(self.exchange_response_count(), 1)

    def test_observe_mode_reports_expired_pending_order_without_canceling(self):
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:21Z",
            execute=False,
        )

        self.assertEqual(report.status, "pending_limit_watchdog_action_ready")
        self.assertEqual(report.items[0].status, "pending_limit_wait_expired")
        self.assertEqual(report.items[0].action, "cancel_pending_order")
        self.assertNotIn("cancel_order", [call[0] for call in client.calls])

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

    def test_execute_mode_reprices_micro_grid_pending_order_once(self):
        cache_path = Path(self.tmp.name) / "seconds.json"
        cache_path.write_text(
            json.dumps(
                {
                    "schema": "bfa_raw_feed_second_bars_v1",
                    "symbols": {
                        "ETHUSDT": [
                            {
                                "symbol": "ETHUSDT",
                                "close": 100.0,
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        self.insert_pending_intent(
            OrderIntent(
                symbol="ETHUSDT",
                side="SELL",
                quantity=1.0,
                notional_usdt=101.0,
                entry_price=101.0,
                stop_price=103.0,
                target_price=98.0,
                leverage=10,
                mode="live",
                decided_at="2026-06-20T09:00:00Z",
                order_type="LIMIT",
                time_in_force="GTX",
                limit_wait_seconds=20,
                metadata={"client_order_id": "bfa-eth-pending-1", "strategy_leg": "micro_grid"},
                reason_codes=["strategy_leg:micro_grid"],
            )
        )
        client = FakePendingLimitClient(order_status="NEW", executed_qty="0", active_position=False)

        report = build_pending_limit_watchdog_report(
            self.config(
                BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED="true",
                BFA_PENDING_LIMIT_MICRO_GRID_REPRICE_ENABLED="true",
                BFA_LIVE_MICRO_GRID_SECONDS_CACHE=str(cache_path),
                BFA_PENDING_LIMIT_MICRO_GRID_REPRICE_AFTER_SECONDS="8",
                BFA_PENDING_LIMIT_MICRO_GRID_REPRICE_EDGE_BPS="8",
                BFA_PENDING_LIMIT_MICRO_GRID_REPRICE_WAIT_SECONDS="12",
            ),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-06-20T09:00:09Z",
            execute=True,
        )

        repriced = [item for item in report.items if item.status == "repriced_pending"]
        self.assertEqual(report.status, "pending_limit_watchdog_repriced")
        self.assertEqual(len(repriced), 1)
        self.assertTrue(report.action_taken)
        self.assertIn(("cancel_order", {"symbol": "ETHUSDT", "orig_client_order_id": "bfa-eth-pending-1"}), client.calls)
        self.assertEqual(len(client.new_orders), 1)
        self.assertEqual(client.new_orders[0]["symbol"], "ETHUSDT")
        self.assertEqual(client.new_orders[0]["time_in_force"], "GTX")
        self.assertGreater(client.new_orders[0]["price"], 100.0)
        self.assertLess(client.new_orders[0]["price"], 101.0)

        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute("SELECT payload_json FROM order_intents WHERE symbol = 'ETHUSDT'").fetchall()
        finally:
            connection.close()
        payloads = [json.loads(row[0]) for row in rows]
        pending_payloads = [payload for payload in payloads if payload["status"] == "entry_order_pending"]
        self.assertEqual(len(pending_payloads), 2)
        latest_intent = pending_payloads[-1]["intent"]
        self.assertEqual(latest_intent["metadata"]["pending_limit_watchdog_reprice_count"], 1)
        self.assertEqual(latest_intent["limit_wait_seconds"], 12)


if __name__ == "__main__":
    unittest.main()
