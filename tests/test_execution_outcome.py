import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.outcome import (
    LocalSubmittedIntent,
    build_latest_trade_outcome,
    load_submitted_intents,
    persist_trade_outcome,
    reconcile_submitted_trade_outcomes,
    summarize_trade_outcome,
)
from bfa.execution.store import persist_order_intent


class FakeTradeClient:
    def __init__(self, trades):
        self.trades = trades
        self.calls = []

    def user_trades(self, symbol, *, start_time=None, end_time=None, limit=500):
        self.calls.append((symbol, start_time, end_time, limit))
        return list(self.trades)


class FakeTradeMapClient:
    def __init__(self, trades_by_symbol):
        self.trades_by_symbol = trades_by_symbol
        self.calls = []

    def user_trades(self, symbol, *, start_time=None, end_time=None, limit=500):
        self.calls.append((symbol, start_time, end_time, limit))
        return list(self.trades_by_symbol.get(symbol, []))


class TradeOutcomeTests(unittest.TestCase):
    def test_summarizes_closed_round_trip_net_of_commission(self):
        intent = LocalSubmittedIntent(
            event_id=1,
            occurred_at="2026-06-20T02:49:17Z",
            symbol="ZECUSDT",
            side="BUY",
            quantity=0.032,
            entry_price=467.68,
            leverage=3,
        )

        outcome = summarize_trade_outcome(
            intent,
            [
                {
                    "id": 10,
                    "orderId": 100,
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "positionSide": "LONG",
                    "qty": "0.032",
                    "price": "467.68",
                    "quoteQty": "14.96576",
                    "realizedPnl": "0",
                    "commission": "0.00748288",
                    "commissionAsset": "USDT",
                    "time": 1781923762837,
                    "buyer": True,
                    "maker": False,
                },
                {
                    "id": 11,
                    "orderId": 101,
                    "symbol": "ZECUSDT",
                    "side": "SELL",
                    "positionSide": "LONG",
                    "qty": "0.032",
                    "price": "471.49",
                    "quoteQty": "15.08768",
                    "realizedPnl": "0.12192",
                    "commission": "0.00754384",
                    "commissionAsset": "USDT",
                    "time": 1781924000000,
                    "buyer": False,
                    "maker": False,
                },
            ],
        )

        self.assertEqual(outcome.status, "closed")
        self.assertEqual(outcome.trade_count, 2)
        self.assertAlmostEqual(outcome.net_quantity, 0.0)
        self.assertAlmostEqual(outcome.gross_realized_pnl_usdt, 0.12192)
        self.assertAlmostEqual(outcome.commission_usdt, 0.01502672)
        self.assertAlmostEqual(outcome.net_realized_pnl_usdt, 0.10689328)

    def test_build_latest_trade_outcome_loads_submitted_intent_and_can_persist(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        intent = OrderIntent(
            symbol="ZECUSDT",
            side="BUY",
            quantity=0.032,
            notional_usdt=14.96576,
            entry_price=467.68,
            stop_price=466.35,
            target_price=471.49,
            leverage=3,
            mode="live",
            decided_at="2026-06-20T02:49:17Z",
        )
        persist_order_intent(
            store,
            intent=intent,
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
        )
        client = FakeTradeClient(
            [
                {
                    "id": 10,
                    "orderId": 100,
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "qty": "0.032",
                    "price": "467.68",
                    "quoteQty": "14.96576",
                    "realizedPnl": "0",
                    "commission": "0.00748288",
                    "commissionAsset": "USDT",
                    "time": 1781923762837,
                },
                {
                    "id": 11,
                    "orderId": 101,
                    "symbol": "ZECUSDT",
                    "side": "SELL",
                    "qty": "0.032",
                    "price": "471.49",
                    "quoteQty": "15.08768",
                    "realizedPnl": "0.12192",
                    "commission": "0.00754384",
                    "commissionAsset": "USDT",
                    "time": 1781924000000,
                },
            ]
        )

        outcome = build_latest_trade_outcome(store, client, symbol="ZECUSDT", persist=True)

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.status, "closed")
        self.assertEqual(client.calls[0][0], "ZECUSDT")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 1)

    def test_persist_trade_outcome_records_fill_and_outcome_events(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        outcome = summarize_trade_outcome(
            LocalSubmittedIntent(
                event_id=1,
                occurred_at="2026-06-20T02:49:17Z",
                symbol="ZECUSDT",
                side="BUY",
                quantity=0.032,
                entry_price=467.68,
                leverage=3,
            ),
            [
                {
                    "id": 10,
                    "orderId": 100,
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "qty": "0.032",
                    "price": "467.68",
                    "quoteQty": "14.96576",
                    "realizedPnl": "0",
                    "commission": "0.00748288",
                    "commissionAsset": "USDT",
                    "time": 1781923762837,
                }
            ],
        )

        persisted = persist_trade_outcome(store, outcome)

        self.assertEqual(persisted["fills"], 1)
        self.assertEqual(persisted["fills_existing"], 0)
        self.assertEqual(persisted["outcome_inserted"], 1)
        self.assertGreater(persisted["outcomes"], 0)

    def test_persist_trade_outcome_is_idempotent_by_ref_id(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        outcome = summarize_trade_outcome(
            LocalSubmittedIntent(
                event_id=1,
                occurred_at="2026-06-20T02:49:17Z",
                symbol="ZECUSDT",
                side="BUY",
                quantity=0.032,
                entry_price=467.68,
                leverage=3,
            ),
            [
                {
                    "id": 10,
                    "orderId": 100,
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "qty": "0.032",
                    "price": "467.68",
                    "quoteQty": "14.96576",
                    "realizedPnl": "0",
                    "commission": "0.00748288",
                    "commissionAsset": "USDT",
                    "time": 1781923762837,
                }
            ],
        )

        first = persist_trade_outcome(store, outcome)
        second = persist_trade_outcome(store, outcome)

        self.assertEqual(first["fills"], 1)
        self.assertEqual(first["fills_existing"], 0)
        self.assertEqual(first["outcome_inserted"], 1)
        self.assertEqual(second["fills"], 0)
        self.assertEqual(second["fills_existing"], 1)
        self.assertEqual(second["outcome_inserted"], 0)
        self.assertEqual(first["outcomes"], second["outcomes"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 1)

    def test_reconcile_submitted_trade_outcomes_persists_only_closed_outcomes(self):
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
                "intent": {
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "quantity": 0.032,
                    "entry_price": 467.68,
                    "leverage": 3,
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
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
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient(
            {
                "ZECUSDT": [
                    {
                        "id": 10,
                        "orderId": 100,
                        "symbol": "ZECUSDT",
                        "side": "BUY",
                        "qty": "0.032",
                        "price": "467.68",
                        "quoteQty": "14.96576",
                        "realizedPnl": "0",
                        "commission": "0.00748288",
                        "commissionAsset": "USDT",
                        "time": 1781923762837,
                    },
                    {
                        "id": 11,
                        "orderId": 101,
                        "symbol": "ZECUSDT",
                        "side": "SELL",
                        "qty": "0.032",
                        "price": "471.49",
                        "quoteQty": "15.08768",
                        "realizedPnl": "0.12192",
                        "commission": "0.00754384",
                        "commissionAsset": "USDT",
                        "time": 1781924000000,
                    },
                ],
                "BNBUSDT": [
                    {
                        "id": 20,
                        "orderId": 200,
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "qty": "0.01",
                        "price": "581.47",
                        "quoteQty": "5.8147",
                        "realizedPnl": "0",
                        "commission": "0.00232588",
                        "commissionAsset": "USDT",
                        "time": 1781926994383,
                    }
                ],
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client, persist_closed=True)
        payload = report.to_dict()

        self.assertEqual(payload["summary"]["submitted_intents"], 2)
        self.assertEqual(payload["summary"]["checked"], 2)
        self.assertEqual(payload["summary"]["closed"], 1)
        self.assertEqual(payload["summary"]["open_or_partial"], 1)
        self.assertEqual(payload["summary"]["persisted_outcomes_inserted"], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 1)
        self.assertEqual([call[0] for call in client.calls], ["ZECUSDT", "BNBUSDT"])

    def test_reconcile_scans_reconcilable_non_submitted_statuses_and_since_filter(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T02:49:17Z",
            source="execution.live",
            symbol="OLDUSDT",
            ref_id="order_intent:OLDUSDT:2026-06-20T02:49:17Z",
            payload={
                "status": "entry_order_partial_filled_protected",
                "intent": {
                    "symbol": "OLDUSDT",
                    "side": "BUY",
                    "quantity": 1.0,
                    "entry_price": 1.0,
                    "leverage": 3,
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:49:17Z",
            source="execution.live",
            symbol="ZECUSDT",
            ref_id="order_intent:ZECUSDT:2026-06-20T03:49:17Z",
            payload={
                "status": "entry_order_partial_filled_protected",
                "intent": {
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "quantity": 0.032,
                    "entry_price": 467.68,
                    "leverage": 3,
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:50:17Z",
            source="execution.live",
            symbol="SKIPUSDT",
            ref_id="order_intent:SKIPUSDT:2026-06-20T03:50:17Z",
            payload={
                "status": "entry_order_pending",
                "intent": {
                    "symbol": "SKIPUSDT",
                    "side": "BUY",
                    "quantity": 1.0,
                    "entry_price": 1.0,
                    "leverage": 3,
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient(
            {
                "ZECUSDT": [
                    {
                        "id": 10,
                        "orderId": 100,
                        "symbol": "ZECUSDT",
                        "side": "BUY",
                        "qty": "0.032",
                        "price": "467.68",
                        "quoteQty": "14.96576",
                        "realizedPnl": "0",
                        "commission": "0.00748288",
                        "commissionAsset": "USDT",
                        "time": 1781923762837,
                    },
                    {
                        "id": 11,
                        "orderId": 101,
                        "symbol": "ZECUSDT",
                        "side": "SELL",
                        "qty": "0.032",
                        "price": "471.49",
                        "quoteQty": "15.08768",
                        "realizedPnl": "0.12192",
                        "commission": "0.00754384",
                        "commissionAsset": "USDT",
                        "time": 1781924000000,
                    },
                ]
            }
        )

        intents = load_submitted_intents(connection, since="2026-06-20T03:00:00Z")
        report = reconcile_submitted_trade_outcomes(
            store,
            client,
            persist_closed=True,
            since="2026-06-20T03:00:00Z",
        )
        payload = report.to_dict()

        self.assertEqual([intent.symbol for intent in intents], ["ZECUSDT"])
        self.assertEqual(payload["summary"]["submitted_intents"], 1)
        self.assertEqual(payload["summary"]["reconcilable_intents"], 1)
        self.assertEqual(payload["summary"]["closed"], 1)
        self.assertEqual(payload["summary"]["persisted_outcomes_inserted"], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 1)
        self.assertEqual([call[0] for call in client.calls], ["ZECUSDT"])

    def test_reconcile_submitted_trade_outcomes_skips_already_closed_by_default(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        zec_event_id = store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T02:49:17Z",
            source="execution.live",
            symbol="ZECUSDT",
            ref_id="order_intent:ZECUSDT:2026-06-20T02:49:17Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "ZECUSDT",
                    "side": "BUY",
                    "quantity": 0.032,
                    "entry_price": 467.68,
                    "leverage": 3,
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-20T03:29:50Z",
            source="binance_usdm",
            symbol="ZECUSDT",
            ref_id=f"outcome:{zec_event_id}:closed",
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
                "intent": {
                    "symbol": "BNBUSDT",
                    "side": "BUY",
                    "quantity": 0.01,
                    "entry_price": 581.47,
                    "leverage": 5,
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient({"BNBUSDT": []})

        report = reconcile_submitted_trade_outcomes(store, client)

        self.assertEqual(
            [item["status"] for item in report.to_dict()["items"]],
            ["already_reconciled", "open_or_partial"],
        )
        self.assertEqual(report.to_dict()["summary"]["already_reconciled"], 1)
        self.assertEqual([call[0] for call in client.calls], ["BNBUSDT"])


if __name__ == "__main__":
    unittest.main()
