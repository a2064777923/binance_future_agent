import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.reconcile import reconcile_exchange_state
from bfa.execution.store import persist_order_intent


class FakeReconciliationClient:
    def __init__(self, *, open_orders=None, positions=None):
        self._open_orders = [] if open_orders is None else open_orders
        self._positions = [] if positions is None else positions
        self.calls = []

    def open_orders(self, symbol=None):
        self.calls.append(("open_orders", symbol))
        return list(self._open_orders)

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        return list(self._positions)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def intent(self, symbol="BTCUSDT", decided_at="2026-06-20T10:00:00Z"):
        return OrderIntent(
            symbol=symbol,
            side="BUY",
            quantity=0.2,
            notional_usdt=20.0,
            entry_price=100.0,
            stop_price=96.0,
            target_price=108.0,
            leverage=3,
            mode="live",
            decided_at=decided_at,
        )

    def persist_submitted(self, intent):
        return persist_order_intent(
            self.store,
            intent=intent,
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
        )

    def test_reports_matched_unknown_open_orders_and_position_symbols(self):
        self.persist_submitted(self.intent())
        client = FakeReconciliationClient(
            open_orders=[
                {
                    "clientOrderId": "bfa-btcusdt-20260620100000",
                    "orderId": 123,
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "status": "NEW",
                },
                {
                    "clientOrderId": "manual-order-1",
                    "orderId": 456,
                    "symbol": "ETHUSDT",
                    "side": "BUY",
                    "status": "NEW",
                },
            ],
            positions=[
                {"symbol": "BTCUSDT", "positionAmt": "0.200"},
                {"symbol": "ETHUSDT", "positionAmt": "0"},
            ],
        )

        report = reconcile_exchange_state(self.store, client)

        self.assertEqual(report.local_intent_count, 1)
        self.assertEqual(report.open_order_count, 2)
        self.assertEqual(report.matched[0]["client_order_id"], "bfa-btcusdt-20260620100000")
        self.assertEqual(report.matched[0]["match_type"], "open_order")
        self.assertEqual(report.missing_on_exchange, [])
        self.assertEqual(report.unknown_on_exchange[0]["client_order_id"], "manual-order-1")
        self.assertEqual(report.position_symbols, ["BTCUSDT"])
        self.assertEqual(client.calls, [("open_orders", None), ("position_risk", None)])

    def test_reports_missing_without_mutating_event_store(self):
        self.persist_submitted(self.intent(symbol="ETHUSDT"))
        before_count = self.connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0]
        before_changes = self.connection.total_changes
        client = FakeReconciliationClient(open_orders=[], positions=[])

        report = reconcile_exchange_state(self.store, client, symbol="ETHUSDT")

        after_count = self.connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0]
        self.assertEqual(report.matched, [])
        self.assertEqual(report.missing_on_exchange[0]["symbol"], "ETHUSDT")
        self.assertEqual(report.unknown_on_exchange, [])
        self.assertEqual(before_count, after_count)
        self.assertEqual(before_changes, self.connection.total_changes)
        self.assertEqual(client.calls, [("open_orders", "ETHUSDT"), ("position_risk", "ETHUSDT")])

    def test_matches_market_order_by_position_when_no_open_order_remains(self):
        self.persist_submitted(self.intent())
        client = FakeReconciliationClient(
            open_orders=[],
            positions=[{"symbol": "BTCUSDT", "positionAmt": "0.200"}],
        )

        report = reconcile_exchange_state(self.store, client)

        self.assertEqual(report.matched[0]["match_type"], "position")
        self.assertEqual(report.missing_on_exchange, [])

    def test_open_order_without_client_id_is_reported_unknown(self):
        client = FakeReconciliationClient(
            open_orders=[{"orderId": 789, "symbol": "BTCUSDT", "side": "BUY", "status": "NEW"}],
            positions=[],
        )

        report = reconcile_exchange_state(self.store, client)

        self.assertEqual(report.unknown_on_exchange[0]["exchange_order_id"], 789)
        self.assertIsNone(report.unknown_on_exchange[0]["client_order_id"])


if __name__ == "__main__":
    unittest.main()
