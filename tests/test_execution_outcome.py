import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.outcome import (
    LocalSubmittedIntent,
    build_latest_trade_outcome,
    persist_trade_outcome,
    summarize_trade_outcome,
)
from bfa.execution.store import persist_order_intent


class FakeTradeClient:
    def __init__(self, trades):
        self.trades = trades
        self.calls = []

    def user_trades(self, symbol, *, start_time=None, limit=500):
        self.calls.append((symbol, start_time, limit))
        return list(self.trades)


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


if __name__ == "__main__":
    unittest.main()
