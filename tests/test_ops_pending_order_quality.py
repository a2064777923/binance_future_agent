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

    def test_adverse_momentum_and_flow_cancel_falling_knife_entry(self):
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
                }
            },
            open_orders=self.open_orders(),
        )

        self.assertIn("pending_order_trend_and_flow_deteriorated", report.items[0].reasons)
        self.assertEqual(report.items[0].status, "quality_canceled")

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


if __name__ == "__main__":
    unittest.main()
