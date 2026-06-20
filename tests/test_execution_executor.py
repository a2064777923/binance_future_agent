import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.ai.decision import validate_decision_payload
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceSignedError
from bfa.execution.executor import ExecutionEngine
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState


EXCHANGE_INFO = Path(__file__).parent / "fixtures" / "binance_market" / "exchange_info.json"


class FakeSignedClient:
    def __init__(self):
        self.calls = []

    def change_margin_type(self, symbol, *, margin_type="ISOLATED"):
        self.calls.append(("margin", symbol, margin_type))
        return {"code": 200, "msg": "success"}

    def change_initial_leverage(self, symbol, *, leverage):
        self.calls.append(("leverage", symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        return {"orderId": 123, "status": "NEW", **kwargs}

    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        return {"algoId": 456, "status": "NEW", **kwargs}

    def test_order(self, **kwargs):
        self.calls.append(("test_order", kwargs))
        return {}


class MarginFailingSignedClient(FakeSignedClient):
    def change_margin_type(self, symbol, *, margin_type="ISOLATED"):
        self.calls.append(("margin", symbol, margin_type))
        raise BinanceSignedError(
            endpoint="/fapi/v1/marginType",
            params={"symbol": symbol, "marginType": margin_type},
            status_code=400,
            binance_code=-4167,
            binance_message="Unable to adjust to isolated-margin mode under the Multi-Assets mode.",
            headers={},
        )


class ExecutionEngineTests(unittest.TestCase):
    def validation(self, **overrides):
        payload = {
            "decision": "trade",
            "side": "long",
            "confidence": 0.75,
            "entry_price": 100.0,
            "stop_price": 96.0,
            "target_price": 108.0,
            "notional_usdt": 20.0,
            "hold_time_minutes": 30,
            "reasons": ["narrative and market confirmation"],
        }
        payload.update(overrides)
        context = context_from_candidate(
            {"symbol": "BTCUSDT", "score": 42},
            risk_limits=RiskLimits(
                account_capital_usdt=100,
                max_leverage=3,
                max_position_notional_usdt=20,
                max_risk_per_trade_usdt=1,
                max_daily_loss_usdt=3,
                max_open_positions=2,
            ),
            decided_at="2026-06-20T10:00:00Z",
        )
        return validate_decision_payload(payload, context)

    def filters(self):
        return SymbolExecutionFilters.from_exchange_info(
            json.loads(EXCHANGE_INFO.read_text(encoding="utf-8")),
            "BTCUSDT",
        )

    def config(self, **overrides):
        env = {
            "BFA_MODE": "dry_run",
            "BFA_ACCOUNT_CAPITAL_USDT": "100",
            "BFA_MAX_LEVERAGE": "3",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
            "BFA_MAX_RISK_PER_TRADE_USDT": "1",
            "BFA_MAX_DAILY_LOSS_USDT": "3",
            "BFA_MAX_OPEN_POSITIONS": "2",
            "BFA_KILL_SWITCH_FILE": "",
            "BINANCE_FUTURES_BASE_URL": "https://fapi.binance.com",
        }
        env.update(overrides)
        return load_config(env)

    def test_dry_run_persists_intent_without_exchange_calls(self):
        fake_client = FakeSignedClient()
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        engine = ExecutionEngine(
            config=self.config(),
            signed_client=fake_client,
            store=store,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(),
            decided_at="2026-06-20T10:00:00Z",
            filters=self.filters(),
        )

        self.assertEqual(result.status, "dry_run")
        self.assertFalse(result.submitted)
        self.assertEqual(fake_client.calls, [])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"],
            1,
        )

    def test_live_kill_switch_rejects_before_exchange_calls(self):
        fake_client = FakeSignedClient()
        with tempfile.TemporaryDirectory() as tmp:
            kill_switch = Path(tmp) / "KILL_SWITCH"
            kill_switch.write_text("stop", encoding="utf-8")
            engine = ExecutionEngine(
                config=self.config(
                    BFA_MODE="live",
                    BFA_KILL_SWITCH_FILE=str(kill_switch),
                    BINANCE_API_KEY="synthetic-binance-key-abcdef",
                    BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
                ),
                signed_client=fake_client,
            )

            result = engine.run(
                symbol="BTCUSDT",
                validation=self.validation(),
                decided_at="2026-06-20T10:00:00Z",
                filters=self.filters(),
            )

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.submitted)
        self.assertIn("kill_switch_active", result.risk.reason_codes)
        self.assertEqual(fake_client.calls, [])

    def test_live_accepted_path_sets_margin_leverage_and_order(self):
        fake_client = FakeSignedClient()
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
            store=store,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "submitted")
        self.assertTrue(result.submitted)
        self.assertEqual(fake_client.calls[0], ("margin", "BTCUSDT", "ISOLATED"))
        self.assertEqual(fake_client.calls[1], ("leverage", "BTCUSDT", 3))
        self.assertEqual(fake_client.calls[2][0], "new_order")
        self.assertEqual(fake_client.calls[3][0], "new_algo_order")
        self.assertEqual(fake_client.calls[3][1]["order_type"], "STOP_MARKET")
        self.assertEqual(fake_client.calls[3][1]["side"], "SELL")
        self.assertEqual(fake_client.calls[4][0], "new_algo_order")
        self.assertEqual(fake_client.calls[4][1]["order_type"], "TAKE_PROFIT_MARKET")
        self.assertEqual(fake_client.calls[4][1]["side"], "SELL")
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM exchange_responses").fetchone()["count"],
            1,
        )

    def test_live_cross_margin_mode_uses_crossed_margin_type(self):
        fake_client = FakeSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_MARGIN_MODE="cross",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(fake_client.calls[0], ("margin", "BTCUSDT", "CROSSED"))
        self.assertEqual(fake_client.calls[1], ("leverage", "BTCUSDT", 3))

    def test_live_margin_setup_error_fails_closed_before_entry_order(self):
        fake_client = MarginFailingSignedClient()
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
            store=store,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.submitted)
        self.assertIn("margin_setup_failed", result.risk.reason_codes)
        self.assertEqual(fake_client.calls, [("margin", "BTCUSDT", "ISOLATED")])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"],
            1,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM exchange_responses").fetchone()["count"],
            1,
        )

    def test_filter_rejection_persists_rejected_intent_without_exchange_calls(self):
        fake_client = FakeSignedClient()
        engine = ExecutionEngine(
            config=self.config(),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(notional_usdt=0.1),
            decided_at="2026-06-20T10:00:00Z",
            filters=self.filters(),
        )

        self.assertEqual(result.status, "rejected")
        self.assertIn("notional_below_min", result.risk.reason_codes)
        self.assertEqual(fake_client.calls, [])


if __name__ == "__main__":
    unittest.main()
