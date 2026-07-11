import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.outcome import (
    LocalSubmittedIntent,
    build_latest_trade_outcome,
    _capped_user_trades_end_time,
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


class FailingTradeMapClient(FakeTradeMapClient):
    def __init__(self, trades_by_symbol, fail_symbols):
        super().__init__(trades_by_symbol)
        self.fail_symbols = set(fail_symbols)

    def user_trades(self, symbol, *, start_time=None, end_time=None, limit=500):
        self.calls.append((symbol, start_time, end_time, limit))
        if symbol in self.fail_symbols:
            raise RuntimeError("synthetic fetch failure")
        return list(self.trades_by_symbol.get(symbol, []))


class CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.sql = []
        self.row_factory = connection.row_factory

    def execute(self, sql, params=()):
        self.sql.append(str(sql))
        return self.connection.execute(sql, params)


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

    def test_reconcile_caps_user_trade_query_window_to_binance_seven_day_limit(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T00:00:00Z",
            source="execution.live",
            symbol="ZECUSDT",
            ref_id="order_intent:ZECUSDT:2026-06-20T00:00:00Z",
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
            occurred_at="2026-07-05T00:00:00Z",
            source="execution.live",
            symbol="ZECUSDT",
            ref_id="order_intent:ZECUSDT:2026-07-05T00:00:00Z",
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
        client = FakeTradeClient([])

        reconcile_submitted_trade_outcomes(store, client)

        first_call = client.calls[0]
        self.assertEqual(first_call[0], "ZECUSDT")
        self.assertEqual(first_call[2] - first_call[1], 7 * 24 * 60 * 60 * 1000 - 1000)

    def test_user_trade_query_window_is_capped_to_now_for_recent_intents(self):
        start_time = 1783557622000

        end_time = _capped_user_trades_end_time(start_time, now_ms=start_time + 60_000)

        self.assertEqual(end_time, start_time + 60_000)

    def test_reconcile_records_fetch_error_without_aborting_batch(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"), start=1):
            store.insert_artifact(
                "order_intents",
                occurred_at=f"2026-07-05T00:0{index}:00Z",
                source="execution.live",
                symbol=symbol,
                ref_id=f"order_intent:{symbol}:{index}",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": symbol,
                        "side": "BUY",
                        "quantity": 1,
                        "entry_price": 100,
                        "leverage": 3,
                    },
                },
                event_type="order_intent",
            )
        client = FailingTradeMapClient({"ETHUSDT": []}, fail_symbols={"BTCUSDT"})

        report = reconcile_submitted_trade_outcomes(store, client)
        payload = report.to_dict()

        self.assertEqual(payload["summary"]["fetch_error"], 1)
        self.assertEqual(payload["summary"]["open_or_partial"], 1)
        self.assertEqual([item["status"] for item in payload["items"]], ["fetch_error", "open_or_partial"])

    def test_reconcile_can_limit_to_newest_submitted_intents(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT"), start=1):
            store.insert_artifact(
                "order_intents",
                occurred_at=f"2026-07-05T00:0{index}:00Z",
                source="execution.live",
                symbol=symbol,
                ref_id=f"order_intent:{symbol}:{index}",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": symbol,
                        "side": "BUY",
                        "quantity": 1,
                        "entry_price": 100,
                        "leverage": 3,
                    },
                },
                event_type="order_intent",
            )
        client = FakeTradeMapClient({})

        report = reconcile_submitted_trade_outcomes(store, client, max_intents=2)

        self.assertEqual(report.to_dict()["summary"]["submitted_intents"], 2)
        self.assertEqual([call[0] for call in client.calls], ["ETHUSDT", "SOLUSDT"])

    def test_reconcile_max_intents_is_applied_in_sql_before_filtering(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for index in range(40):
            store.insert_artifact(
                "order_intents",
                occurred_at=f"2026-07-05T00:{index:02d}:00Z",
                source="execution.live",
                symbol=f"T{index}USDT",
                ref_id=f"order_intent:T{index}USDT",
                payload={
                    "status": "rejected"
                    if index < 35
                    else "submitted",
                    "intent": {
                        "symbol": f"T{index}USDT",
                        "side": "BUY",
                        "quantity": 1,
                        "entry_price": 100,
                        "leverage": 3,
                    },
                },
                event_type="order_intent",
            )
        counting = CountingConnection(connection)

        intents = load_submitted_intents(counting, max_intents=3)

        self.assertEqual([intent.symbol for intent in intents], ["T37USDT", "T38USDT", "T39USDT"])
        self.assertTrue(any("LIMIT ?" in sql for sql in counting.sql))

    def test_reconcile_includes_pending_limit_watchdog_submitted_intents(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        pending_event_id = store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T12:29:28Z",
            source="execution.live",
            symbol="BIRBUSDT",
            ref_id="order_intent:BIRBUSDT:2026-07-05T12:29:28Z",
            payload={
                "status": "entry_order_pending",
                "intent": {
                    "symbol": "BIRBUSDT",
                    "side": "BUY",
                    "quantity": 10646,
                    "entry_price": 0.07754,
                    "leverage": 30,
                    "metadata": {
                        "client_order_id": "bfa-birbusdt-20260705122928-trc",
                    },
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T12:40:58Z",
            source="execution.live",
            symbol="BIRBUSDT",
            ref_id="order_intent:BIRBUSDT:2026-07-05T12:40:58Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BIRBUSDT",
                    "side": "BUY",
                    "quantity": 10646,
                    "entry_price": 0.07754,
                    "leverage": 30,
                    "metadata": {
                        "pending_intent_event_id": pending_event_id,
                        "pending_client_order_id": "bfa-birbusdt-20260705122928-trc",
                        "latency": {
                            "agent_started_at": "2026-07-05T12:29:28Z",
                        },
                    },
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient(
            {
                "BIRBUSDT": [
                    {
                        "id": 1001,
                        "orderId": 528508672,
                        "symbol": "BIRBUSDT",
                        "side": "BUY",
                        "qty": "10646",
                        "price": "0.07754",
                        "quoteQty": "825.49084",
                        "realizedPnl": "0",
                        "commission": "0.33019634",
                        "commissionAsset": "USDT",
                        "time": 1783255254215,
                    },
                    {
                        "id": 1002,
                        "orderId": 528700000,
                        "symbol": "BIRBUSDT",
                        "side": "SELL",
                        "qty": "10646",
                        "price": "0.07887",
                        "quoteQty": "839.65002",
                        "realizedPnl": "14.15918",
                        "commission": "0.33586001",
                        "commissionAsset": "USDT",
                        "time": 1783256708496,
                    },
                ],
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client, persist_closed=True)
        payload = report.to_dict()

        self.assertEqual(payload["summary"]["submitted_intents"], 1)
        self.assertEqual(payload["summary"]["closed"], 1)
        self.assertEqual(payload["summary"]["persisted_outcomes_inserted"], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 1)
        item = payload["items"][0]
        self.assertEqual(item["intent"]["original_event_id"], pending_event_id)
        self.assertEqual(client.calls[0][1], 1783254568000)

    def test_reconcile_skips_watchdog_submitted_order_when_query_showed_unfilled(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        pending_event_id = store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T12:29:28Z",
            source="execution.live",
            symbol="BIRBUSDT",
            ref_id="order_intent:BIRBUSDT:2026-07-05T12:29:28Z:trm",
            payload={
                "status": "entry_order_pending",
                "intent": {
                    "symbol": "BIRBUSDT",
                    "side": "BUY",
                    "quantity": 9378,
                    "entry_price": 0.07702,
                    "leverage": 30,
                    "metadata": {
                        "client_order_id": "bfa-birbusdt-20260705122928-trm",
                    },
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T12:40:58Z",
            source="execution.live",
            symbol="BIRBUSDT",
            ref_id="order_intent:BIRBUSDT:2026-07-05T12:40:58Z:trm",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BIRBUSDT",
                    "side": "BUY",
                    "quantity": 10646,
                    "entry_price": 0.07754,
                    "leverage": 30,
                    "metadata": {
                        "pending_intent_event_id": pending_event_id,
                        "pending_client_order_id": "bfa-birbusdt-20260705122928-trm",
                        "latency": {"agent_started_at": "2026-07-05T12:29:28Z"},
                    },
                },
            },
            event_type="order_intent",
        )
        store.insert_artifact(
            "exchange_responses",
            occurred_at="2026-07-05T12:40:58Z",
            source="binance_usdm",
            symbol="BIRBUSDT",
            ref_id="exchange_response:pending_limit_watchdog:BIRBUSDT:2026-07-05T12:40:58Z",
            payload={
                "response_type": "pending_limit_watchdog",
                "response": {
                    "watchdog_status": "filled_protected",
                    "pending_intent_event_id": pending_event_id,
                    "client_order_id": "bfa-birbusdt-20260705122928-trm",
                    "entry_order_query": {
                        "status": "NEW",
                        "executedQty": "0",
                        "avgPrice": "0.00",
                    },
                },
            },
            event_type="exchange_response",
        )

        intents = load_submitted_intents(connection, symbol="BIRBUSDT")
        report = reconcile_submitted_trade_outcomes(
            store,
            FakeTradeMapClient({"BIRBUSDT": []}),
            symbol="BIRBUSDT",
            persist_closed=True,
        )

        self.assertEqual(intents, [])
        self.assertEqual(report.to_dict()["summary"]["submitted_intents"], 0)

    def test_same_signal_layered_intents_do_not_truncate_each_other_window(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for suffix, quantity, entry_price in (
            ("trc", 10646, 0.07754),
            ("trm", 9378, 0.07702),
        ):
            pending_event_id = store.insert_artifact(
                "order_intents",
                occurred_at="2026-07-05T12:29:28Z",
                source="execution.live",
                symbol="BIRBUSDT",
                ref_id=f"order_intent:BIRBUSDT:2026-07-05T12:29:28Z:{suffix}",
                payload={
                    "status": "entry_order_pending",
                    "intent": {
                        "symbol": "BIRBUSDT",
                        "side": "BUY",
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "leverage": 30,
                        "metadata": {"client_order_id": f"bfa-birbusdt-20260705122928-{suffix}"},
                    },
                },
                event_type="order_intent",
            )
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-07-05T12:40:58Z",
                source="execution.live",
                symbol="BIRBUSDT",
                ref_id=f"order_intent:BIRBUSDT:2026-07-05T12:40:58Z:{suffix}",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BIRBUSDT",
                        "side": "BUY",
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "leverage": 30,
                        "metadata": {
                            "pending_intent_event_id": pending_event_id,
                            "pending_client_order_id": f"bfa-birbusdt-20260705122928-{suffix}",
                            "latency": {"agent_started_at": "2026-07-05T12:29:28Z"},
                        },
                    },
                },
                event_type="order_intent",
            )
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T13:10:00Z",
            source="execution.live",
            symbol="BIRBUSDT",
            ref_id="order_intent:BIRBUSDT:2026-07-05T13:10:00Z:next",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BIRBUSDT",
                    "side": "SELL",
                    "quantity": 1,
                    "entry_price": 0.08,
                    "leverage": 30,
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient({"BIRBUSDT": []})

        reconcile_submitted_trade_outcomes(store, client, symbol="BIRBUSDT")

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], 1783254568000)
        self.assertGreater(client.calls[0][2], client.calls[0][1])

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

    def test_position_adjustment_intent_is_not_loaded_as_entry(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T00:00:00Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="adjustment:1",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "SELL",
                    "quantity": 0.1,
                    "entry_price": 0,
                    "leverage": 10,
                    "order_type": "MARKET",
                    "reduce_only": True,
                    "metadata": {"position_adjustment": True},
                },
            },
            event_type="order_intent",
        )

        self.assertEqual(load_submitted_intents(connection), [])

    def test_same_symbol_intents_fetch_once_and_trade_ids_are_uniquely_owned(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for index, (order_id, occurred_at) in enumerate(((100, "2026-07-05T00:00:00Z"), (200, "2026-07-05T00:10:00Z"))):
            store.insert_artifact(
                "order_intents",
                occurred_at=occurred_at,
                source="execution.live",
                symbol="BTCUSDT",
                ref_id=f"entry:{index}",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1,
                        "entry_price": 100,
                        "leverage": 10,
                        "metadata": {"exchange_order_id": order_id},
                    },
                },
                event_type="order_intent",
            )
        client = FakeTradeMapClient(
            {
                "BTCUSDT": [
                    {"id": 1, "orderId": 100, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209601000},
                    {"id": 2, "orderId": 101, "symbol": "BTCUSDT", "side": "SELL", "qty": "1", "price": "101", "realizedPnl": "1", "commission": "0", "time": 1783209660000},
                    {"id": 3, "orderId": 200, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "102", "realizedPnl": "0", "commission": "0", "time": 1783210201000},
                    {"id": 4, "orderId": 201, "symbol": "BTCUSDT", "side": "SELL", "qty": "1", "price": "103", "realizedPnl": "1", "commission": "0", "time": 1783210260000},
                ]
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client, persist_closed=True)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(report.to_dict()["summary"]["closed"], 2)
        trade_ids = [
            trade["trade_id"]
            for item in report.to_dict()["items"]
            for trade in item["outcome"]["trades"]
        ]
        self.assertEqual(len(trade_ids), len(set(trade_ids)))

    def test_ambiguous_same_symbol_trade_attribution_stays_unreconciled(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        persist_order_intent(
            store,
            intent=OrderIntent(
                symbol="BTCUSDT",
                side="BUY",
                quantity=1,
                notional_usdt=100,
                entry_price=100,
                stop_price=98,
                target_price=104,
                leverage=10,
                mode="live",
                decided_at="2026-07-05T00:00:00Z",
            ),
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
        )
        client = FakeTradeMapClient(
            {
                "BTCUSDT": [
                    {"id": 1, "orderId": 100, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209601000},
                    {"id": 2, "orderId": 200, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "101", "realizedPnl": "0", "commission": "0", "time": 1783209602000},
                ]
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client)

        self.assertEqual(report.items[0].status, "unreconciled")
        self.assertEqual(report.items[0].reason, "ambiguous_trade_attribution")

    def test_entry_fill_quantity_mismatch_stays_unreconciled(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T00:00:00Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="quantity-mismatch",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 1,
                    "entry_price": 100,
                    "leverage": 10,
                    "metadata": {"exchange_order_id": 100},
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient(
            {
                "BTCUSDT": [
                    {"id": 1, "orderId": 100, "symbol": "BTCUSDT", "side": "BUY", "qty": "0.8", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209601000},
                    {"id": 2, "orderId": 101, "symbol": "BTCUSDT", "side": "SELL", "qty": "0.8", "price": "101", "realizedPnl": "0.8", "commission": "0", "time": 1783209660000},
                ]
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client)

        self.assertEqual(report.items[0].status, "unreconciled")
        self.assertEqual(report.items[0].reason, "ambiguous_trade_attribution")

    def test_manual_same_side_fill_cannot_be_folded_into_agent_round_trip(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-07-05T00:00:00Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="manual-scale-in",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 1,
                    "entry_price": 100,
                    "leverage": 10,
                    "metadata": {"exchange_order_id": 100},
                },
            },
            event_type="order_intent",
        )
        client = FakeTradeMapClient(
            {
                "BTCUSDT": [
                    {"id": 1, "orderId": 100, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209601000},
                    {"id": 2, "orderId": 999, "symbol": "BTCUSDT", "side": "BUY", "qty": "0.2", "price": "99", "realizedPnl": "0", "commission": "0", "time": 1783209610000},
                    {"id": 3, "orderId": 101, "symbol": "BTCUSDT", "side": "SELL", "qty": "1.2", "price": "101", "realizedPnl": "1.2", "commission": "0", "time": 1783209660000},
                ]
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client)

        self.assertEqual(report.items[0].status, "unreconciled")
        self.assertEqual(report.items[0].reason, "ambiguous_trade_attribution")

    def test_overlapping_order_ids_with_combined_exit_are_not_guessed(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        for index, order_id in enumerate((100, 200)):
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-07-05T00:00:00Z",
                source="execution.live",
                symbol="BTCUSDT",
                ref_id=f"overlap:{index}",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1,
                        "entry_price": 100,
                        "leverage": 10,
                        "metadata": {"exchange_order_id": order_id},
                    },
                },
                event_type="order_intent",
            )
        client = FakeTradeMapClient(
            {
                "BTCUSDT": [
                    {"id": 1, "orderId": 100, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209601000},
                    {"id": 2, "orderId": 200, "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100", "realizedPnl": "0", "commission": "0", "time": 1783209602000},
                    {"id": 3, "orderId": 300, "symbol": "BTCUSDT", "side": "SELL", "qty": "2", "price": "101", "realizedPnl": "2", "commission": "0", "time": 1783209660000},
                ]
            }
        )

        report = reconcile_submitted_trade_outcomes(store, client, persist_closed=True)

        self.assertEqual([item.status for item in report.items], ["unreconciled", "unreconciled"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
