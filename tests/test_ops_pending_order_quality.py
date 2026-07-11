import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_order_intent
from bfa.ops.pending_order_quality import execute_pending_order_quality_check


class FakeQualityClient:
    def __init__(self):
        self.calls = []

    def cancel_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "CANCELED", **kwargs}


class PendingOrderQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        persist_order_intent(
            store,
            intent=OrderIntent(
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.2,
                notional_usdt=20,
                entry_price=100,
                stop_price=96,
                target_price=108,
                leverage=10,
                mode="live",
                decided_at="2026-07-10T09:00:00Z",
                order_type="LIMIT",
                limit_wait_seconds=1800,
                metadata={"client_order_id": "bfa-btc-quality-1", "strategy_leg": "trend"},
            ),
            status="entry_order_pending",
            risk=RiskDecision(True, ["risk_accepted"]),
        )
        connection.close()

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **overrides):
        values = {
            "BFA_PENDING_LIMIT_QUALITY_CHECK_ENABLED": "true",
            "BFA_PENDING_LIMIT_QUALITY_EXECUTE_ENABLED": "true",
        }
        values.update(overrides)
        return load_config(values)

    def open_orders(self):
        return [
            {
                "symbol": "BTCUSDT",
                "clientOrderId": "bfa-btc-quality-1",
                "status": "NEW",
                "type": "LIMIT",
                "side": "BUY",
                "origQty": "0.2",
                "executedQty": "0",
                "price": "100",
            }
        ]

    def pending_status(self):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(
                "SELECT status, resolution_status FROM pending_limit_entries"
            ).fetchone()
        finally:
            connection.close()

    def test_moving_away_entry_is_canceled_without_extra_market_request(self):
        client = FakeQualityClient()

        report = execute_pending_order_quality_check(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-07-10T09:01:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 101,
                    "kline_micro_momentum_percent": 0.2,
                    "taker_buy_sell_ratio": 1.1,
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertEqual(report.status, "quality_orders_canceled")
        self.assertEqual(report.items[0].reasons, ["short_term_fill_probability_deteriorated"])
        self.assertEqual(len(client.calls), 1)
        status, resolution = self.pending_status()
        self.assertEqual(status, "resolved")
        self.assertEqual(resolution, "entry_order_quality_canceled")

    def test_persistent_adverse_flow_volume_expansion_and_price_acceptance_cancel_entry(self):
        client = FakeQualityClient()

        report = execute_pending_order_quality_check(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-07-10T09:01:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 100.1,
                    "kline_micro_momentum_percent": -0.2,
                    "taker_buy_sell_ratio": 0.7,
                    "second_taker_buy_fractions": {"5": 0.18, "15": 0.24, "30": 0.31},
                    "second_returns_percent": {"5": -0.08, "15": -0.14, "30": -0.18},
                    "second_volume_expansion_ratio": 2.2,
                    "second_vwap": 100.3,
                    "second_closes": [100.4, 100.32, 100.22, 100.14, 100.1],
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertIn(
            "pending_order_adverse_flow_volume_price_acceptance",
            report.items[0].reasons,
        )
        self.assertEqual(report.items[0].status, "quality_canceled")

    def test_adverse_flow_without_volume_expansion_does_not_cancel(self):
        client = FakeQualityClient()

        report = execute_pending_order_quality_check(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-07-10T09:01:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 100.1,
                    "kline_micro_momentum_percent": -0.2,
                    "taker_buy_sell_ratio": 0.7,
                    "second_taker_buy_fractions": {"5": 0.18, "15": 0.24, "30": 0.31},
                    "second_returns_percent": {"5": -0.08, "15": -0.14, "30": -0.18},
                    "second_volume_expansion_ratio": 1.05,
                    "second_vwap": 100.3,
                    "second_closes": [100.4, 100.32, 100.22, 100.14, 100.1],
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertEqual(report.items[0].status, "quality_ok")
        self.assertEqual(client.calls, [])

    def test_ambiguous_quality_evidence_keeps_order(self):
        client = FakeQualityClient()

        report = execute_pending_order_quality_check(
            self.config(),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-07-10T09:01:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 100.05,
                    "kline_micro_momentum_percent": 0.01,
                    "taker_buy_sell_ratio": 1.0,
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertEqual(report.items[0].status, "quality_ok")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.pending_status()[0], "pending")

    def test_observe_mode_surfaces_cancel_without_mutation(self):
        client = FakeQualityClient()

        report = execute_pending_order_quality_check(
            self.config(BFA_PENDING_LIMIT_QUALITY_EXECUTE_ENABLED="false"),
            db_path=str(self.db_path),
            signed_client=client,
            checked_at="2026-07-10T09:01:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 101,
                    "kline_micro_momentum_percent": 0.2,
                    "taker_buy_sell_ratio": 1.1,
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertEqual(report.status, "quality_action_ready")
        self.assertEqual(report.items[0].status, "quality_cancel_ready")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.pending_status()[0], "pending")

    def test_quality_scan_covers_all_configured_trend_and_micro_pending_slots(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            store = EventStore(connection)
            for index in range(2, 12):
                persist_order_intent(
                    store,
                    intent=OrderIntent(
                        symbol="BTCUSDT",
                        side="BUY",
                        quantity=0.2,
                        notional_usdt=20,
                        entry_price=100,
                        stop_price=96,
                        target_price=108,
                        leverage=10,
                        mode="live",
                        decided_at=f"2026-07-10T09:00:{index:02d}Z",
                        order_type="LIMIT",
                        limit_wait_seconds=1800,
                        metadata={
                            "client_order_id": f"bfa-btc-quality-{index}",
                            "strategy_leg": "micro_grid" if index <= 4 else "trend",
                        },
                    ),
                    status="entry_order_pending",
                    risk=RiskDecision(True, ["risk_accepted"]),
                )
        finally:
            connection.close()
        open_orders = self.open_orders() + [
            {
                "symbol": "BTCUSDT",
                "clientOrderId": f"bfa-btc-quality-{index}",
                "status": "NEW",
                "type": "LIMIT",
                "side": "BUY",
                "origQty": "0.2",
                "executedQty": "0",
                "price": "100",
            }
            for index in range(2, 12)
        ]

        report = execute_pending_order_quality_check(
            self.config(BFA_PENDING_LIMIT_QUALITY_MAX_ITEMS="1"),
            db_path=str(self.db_path),
            signed_client=FakeQualityClient(),
            checked_at="2026-07-10T09:02:00Z",
            market_context_by_symbol={
                "BTCUSDT": {
                    "reference_price": 100.05,
                    "kline_micro_momentum_percent": 0.01,
                    "taker_buy_sell_ratio": 1.0,
                }
            },
            open_orders=open_orders,
        )

        self.assertEqual(len(report.items), 11)


if __name__ == "__main__":
    unittest.main()
