import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.market.models import MarketDataResponse
from bfa.ops.position_sentinel import build_position_sentinel_report


class FakeSignedClient:
    def __init__(self, *, mark_price="107", protected=True):
        self.mark_price = mark_price
        self.protected = protected
        self.algo_orders = []
        self.cancelled_algo_orders = []
        self.normal_orders = []

    def account(self):
        return {"availableBalance": "30", "totalWalletBalance": "30"}

    def position_risk(self):
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.2",
                "positionSide": "LONG",
                "entryPrice": "100",
                "markPrice": self.mark_price,
                "unRealizedProfit": str((float(self.mark_price) - 100) * 0.2),
            }
        ]

    def open_orders(self, symbol=None):
        return list(self.normal_orders)

    def open_algo_orders(self, symbol=None):
        if not self.protected:
            return []
        return [
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "type": "STOP_MARKET",
                "triggerPrice": "96",
                "algoId": 11,
                "clientAlgoId": "old-sl",
            },
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": "108",
                "algoId": 12,
                "clientAlgoId": "old-tp",
            },
        ]

    def new_algo_order(self, **kwargs):
        self.algo_orders.append(kwargs)
        return {"algoId": 100 + len(self.algo_orders), **kwargs}

    def cancel_algo_order(self, **kwargs):
        self.cancelled_algo_orders.append(kwargs)
        return {"status": "CANCELED", **kwargs}

    def position_risk_after(self):
        return self.position_risk()


class FakeMarketClient:
    def __init__(self, *, closes=None, volumes=None, high_offset=0.3, low_offset=0.2):
        self.closes = closes or [106.9, 107.2, 107.4, 107.1, 106.8, 106.5, 106.2, 105.9]
        self.volumes = volumes or [10 + index * 3 for index in range(len(self.closes))]
        self.high_offset = high_offset
        self.low_offset = low_offset

    def exchange_info(self):
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                            {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
                            {"filterType": "MIN_NOTIONAL", "notional": "5"},
                        ],
                    }
                ]
            },
        )

    def klines(self, symbol, *, interval, limit=24, start_time=None, end_time=None):
        rows = []
        for index, close in enumerate(self.closes):
            rows.append(
                [
                    1_700_000_000_000 + index * 60_000,
                    str(close + 0.1),
                    str(close + self.high_offset),
                    str(close - self.low_offset),
                    str(close),
                    str(self.volumes[index] if index < len(self.volumes) else 10),
                ]
            )
        return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=rows)


class PositionSentinelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self._insert_intent()

    def _insert_intent(self, *, metadata=None, reasons=None):
        connection = sqlite3.connect(self.db_path)
        store = EventStore(connection)
        store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:43:09Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="order_intent:BTCUSDT:2026-06-20T03:43:09Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.2,
                    "entry_price": 100,
                    "stop_price": 96,
                    "target_price": 108,
                    "leverage": 5,
                    "metadata": {"hold_time_minutes": 100000, **(metadata or {})},
                    "reason_codes": list(reasons or []),
                },
            },
            event_type="order_intent",
        )
        connection.close()

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_POSITION_MODE": "hedge",
            "BFA_TRAILING_PROTECTION_ENABLED": "true",
            "BFA_POSITION_SENTINEL_EXECUTE_ENABLED": "false",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_sentinel_reports_reversal_trailing_candidate_without_execution_by_default(self):
        fake_signed = FakeSignedClient(mark_price="107")
        report = build_position_sentinel_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=FakeMarketClient(),
        )

        self.assertEqual(report.status, "sentinel_action_ready")
        self.assertFalse(report.execution_enabled)
        self.assertEqual(report.reversal_signals[0].decision, "trail_or_backfill")
        self.assertIn("allowed_action:trail_protective_orders", report.reasons)
        self.assertEqual(fake_signed.algo_orders, [])
        self.assertGreaterEqual(report.persisted["position_sentinel"], 1)

    def test_sentinel_executes_trailing_when_execute_flag_and_config_allow(self):
        fake_signed = FakeSignedClient(mark_price="107")
        report = build_position_sentinel_report(
            self.config(BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=FakeMarketClient(),
            execute=True,
        )

        self.assertEqual(report.status, "sentinel_executed")
        self.assertTrue(report.execution_enabled)
        self.assertTrue(report.execution.adjustment_executed)
        self.assertEqual([order["order_type"] for order in fake_signed.algo_orders], ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
        self.assertEqual(len(fake_signed.cancelled_algo_orders), 2)

    def test_sentinel_can_act_even_when_normal_open_orders_exist(self):
        fake_signed = FakeSignedClient(mark_price="107")
        fake_signed.normal_orders.append({"symbol": "ETHUSDT", "status": "NEW"})

        report = build_position_sentinel_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=FakeMarketClient(),
        )

        self.assertEqual(report.status, "sentinel_action_ready")
        self.assertIn("normal_open_orders_ignored_for_sentinel", report.reasons)
        self.assertIn("allowed_action:trail_protective_orders", report.reasons)

    def test_sentinel_trails_hold_position_when_reversal_risk_rises(self):
        fake_signed = FakeSignedClient(mark_price="102")
        market = FakeMarketClient(
            closes=[102.7, 102.9, 103.1, 102.8, 102.5, 102.2, 102.0, 101.8],
            volumes=[10, 10, 10, 10, 24, 28, 31, 36],
        )

        report = build_position_sentinel_report(
            self.config(
                BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true",
                BFA_POSITION_SENTINEL_REVERSAL_THRESHOLD="0.4",
            ),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=market,
            execute=True,
        )

        self.assertEqual(report.reversal_signals[0].decision, "trail_or_backfill")
        self.assertEqual(report.status, "sentinel_executed")
        self.assertTrue(report.execution.adjustment_executed)
        order_plan = report.execution.executions[0].order_plan
        self.assertEqual(order_plan.action, "trail_protective_orders")
        self.assertIn("sentinel_reversal_risk_trailing", order_plan.reason_codes)
        self.assertGreater(order_plan.stop_price, 100)

    def test_sentinel_does_not_trail_tiny_profit_before_minimum_progress(self):
        fake_signed = FakeSignedClient(mark_price="100.4")
        market = FakeMarketClient(
            closes=[100.2, 100.3, 100.4, 100.35, 100.3, 100.35, 100.4, 100.35],
            volumes=[10, 10, 10, 10, 24, 28, 31, 36],
        )

        report = build_position_sentinel_report(
            self.config(
                BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true",
                BFA_POSITION_SENTINEL_REVERSAL_THRESHOLD="0.0",
            ),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=market,
            execute=True,
        )

        self.assertEqual(report.reversal_signals[0].decision, "observe")
        self.assertEqual(report.status, "sentinel_no_allowed_action")
        self.assertEqual(fake_signed.algo_orders, [])

    def test_micro_grid_profit_giveback_trails_from_recent_mfe(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self._insert_intent(
            metadata={"strategy_leg": "micro_grid", "regime_label": "RANGE", "route_decision": "allow"},
            reasons=["strategy_leg:micro_grid", "regime_label:RANGE", "route_decision:allow"],
        )
        fake_signed = FakeSignedClient(mark_price="100.6")
        market = FakeMarketClient(
            closes=[100.4, 101.0, 102.1, 101.5, 101.0, 100.8, 100.6, 100.5],
            volumes=[30, 30, 30, 30, 18, 16, 14, 12],
            high_offset=0.6,
            low_offset=0.2,
        )

        report = build_position_sentinel_report(
            self.config(BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=market,
            execute=True,
        )

        self.assertEqual(report.reversal_signals[0].decision, "trail_or_backfill")
        self.assertIn("recent_mfe_threshold_met", report.reversal_signals[0].reasons)
        self.assertIn("profit_giveback_detected", report.reversal_signals[0].reasons)
        self.assertEqual(report.status, "sentinel_executed")
        order_plan = report.execution.executions[0].order_plan
        self.assertIn("sentinel_profit_protection", order_plan.reason_codes)
        self.assertIn("trailing_activated_by_target_progress", order_plan.reason_codes)
        self.assertIn("trailing_lock_r:0.1", order_plan.reason_codes)
        self.assertGreater(order_plan.stop_price, 100)

    def test_micro_grid_stagnation_uses_loss_control_trailing(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self._insert_intent(
            metadata={"strategy_leg": "micro_grid", "regime_label": "RANGE", "route_decision": "allow"},
            reasons=["strategy_leg:micro_grid", "regime_label:RANGE", "route_decision:allow"],
        )
        fake_signed = FakeSignedClient(mark_price="100.05")
        market = FakeMarketClient(
            closes=[100.00, 100.04, 100.02, 100.03, 100.01, 100.04, 100.02, 100.03],
            volumes=[40, 42, 41, 40, 24, 22, 20, 18],
            high_offset=0.05,
            low_offset=0.04,
        )

        report = build_position_sentinel_report(
            self.config(BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=market,
            execute=True,
        )

        self.assertEqual(report.reversal_signals[0].decision, "trail_or_backfill")
        self.assertIn("stagnation_exit_pressure", report.reversal_signals[0].reasons)
        order_plan = report.execution.executions[0].order_plan
        self.assertIn("sentinel_loss_control", order_plan.reason_codes)
        self.assertIn("trailing_activated_by_loss_control", order_plan.reason_codes)
        self.assertGreater(order_plan.stop_price, 96)
        self.assertLess(order_plan.stop_price, 100.05)

    def test_micro_grid_invalidated_small_loss_tightens_stop_without_waiting_for_profit(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self._insert_intent(
            metadata={"strategy_leg": "micro_grid", "regime_label": "RANGE", "route_decision": "allow"},
            reasons=["strategy_leg:micro_grid", "regime_label:RANGE", "route_decision:allow"],
        )
        fake_signed = FakeSignedClient(mark_price="99.2")
        market = FakeMarketClient(
            closes=[100.0, 99.9, 99.75, 99.6, 99.45, 99.35, 99.25, 99.2],
            volumes=[10, 10, 10, 10, 18, 22, 25, 28],
            high_offset=0.08,
            low_offset=0.16,
        )

        report = build_position_sentinel_report(
            self.config(BFA_POSITION_SENTINEL_EXECUTE_ENABLED="true"),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake_signed,
            market_client=market,
            execute=True,
        )

        self.assertEqual(report.reversal_signals[0].decision, "trail_or_backfill")
        self.assertIn("setup_invalidated_exit_pressure", report.reversal_signals[0].reasons)
        order_plan = report.execution.executions[0].order_plan
        self.assertIn("sentinel_loss_control", order_plan.reason_codes)
        self.assertIn("trailing_activated_by_loss_control", order_plan.reason_codes)
        self.assertGreater(order_plan.stop_price, 96)
        self.assertLess(order_plan.stop_price, 99.2)


if __name__ == "__main__":
    unittest.main()
