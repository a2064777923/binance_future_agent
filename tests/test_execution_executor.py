import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def __init__(self, *, available_balance="100"):
        self.calls = []
        self.available_balance = available_balance

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

    def open_algo_orders(self, symbol=None):
        self.calls.append(("open_algo_orders", symbol))
        return []

    def cancel_algo_order(self, **kwargs):
        self.calls.append(("cancel_algo_order", kwargs))
        return {"algoStatus": "CANCELED", **kwargs}

    def test_order(self, **kwargs):
        self.calls.append(("test_order", kwargs))
        return {}

    def account(self):
        self.calls.append(("account",))
        return {"availableBalance": self.available_balance}

    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        return {"status": "FILLED", "executedQty": str(kwargs.get("quantity", "0.2")), "avgPrice": "100"}

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        return {"status": "CANCELED", **kwargs}


class LimitFilledSignedClient(FakeSignedClient):
    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        return {"status": "FILLED", "executedQty": "0.2", "avgPrice": "100"}


class LimitExpiredSignedClient(FakeSignedClient):
    def __init__(self, *, available_balance="100"):
        super().__init__(available_balance=available_balance)
        self.cancelled = False

    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        if self.cancelled:
            return {"status": "CANCELED", "executedQty": "0", "avgPrice": "0"}
        return {"status": "NEW", "executedQty": "0", "avgPrice": "0"}

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        self.cancelled = True
        return {"status": "CANCELED", **kwargs}


class LimitUnknownFilledPositionSignedClient(FakeSignedClient):
    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        raise BinanceSignedError(
            endpoint="/fapi/v1/order",
            params=kwargs,
            status_code=400,
            binance_code=-2013,
            binance_message="Order does not exist.",
            headers={},
        )

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        return [
            {
                "symbol": symbol or "BTCUSDT",
                "positionAmt": "0.2",
                "positionSide": "LONG",
                "entryPrice": "100",
                "markPrice": "100.5",
            }
        ]


class LimitUnknownNoPositionSignedClient(FakeSignedClient):
    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        raise BinanceSignedError(
            endpoint="/fapi/v1/order",
            params=kwargs,
            status_code=400,
            binance_code=-2013,
            binance_message="Order does not exist.",
            headers={},
        )

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        return [
            {
                "symbol": symbol or "BTCUSDT",
                "positionAmt": "0",
                "positionSide": "LONG",
                "entryPrice": "0",
                "markPrice": "100",
            }
        ]


class PostOnlyRejectThenAcceptSignedClient(FakeSignedClient):
    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        if len([call for call in self.calls if call[0] == "new_order"]) == 1:
            raise BinanceSignedError(
                endpoint="/fapi/v1/order",
                params=kwargs,
                status_code=400,
                binance_code=-5022,
                binance_message="Due to the order could not be executed as maker, the Post Only order will be rejected.",
                headers={},
            )
        return {"orderId": 234, "status": "NEW", **kwargs}

    def query_order(self, **kwargs):
        self.calls.append(("query_order", kwargs))
        return {"status": "FILLED", "executedQty": "0.2", "avgPrice": "99.8"}


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


class InvalidHighLeverageSignedClient(FakeSignedClient):
    def __init__(self, *, available_balance="100", accepted_leverage=20):
        super().__init__(available_balance=available_balance)
        self.accepted_leverage = accepted_leverage

    def change_initial_leverage(self, symbol, *, leverage):
        self.calls.append(("leverage", symbol, leverage))
        if leverage > self.accepted_leverage:
            raise BinanceSignedError(
                endpoint="/fapi/v1/leverage",
                params={"symbol": symbol, "leverage": str(leverage)},
                status_code=400,
                binance_code=-4028,
                binance_message=f"Leverage {leverage} is not valid",
                headers={},
            )
        return {"symbol": symbol, "leverage": leverage}


class EntryFailingSignedClient(FakeSignedClient):
    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        raise BinanceSignedError(
            endpoint="/fapi/v1/order",
            params=kwargs,
            status_code=400,
            binance_code=-4061,
            binance_message="Order's position side does not match user's setting.",
            headers={},
        )


class ConflictingProtectiveOrderSignedClient(FakeSignedClient):
    def __init__(self, *, available_balance="100"):
        super().__init__(available_balance=available_balance)
        self._protective_attempts = 0

    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        self._protective_attempts += 1
        if self._protective_attempts == 1:
            raise BinanceSignedError(
                endpoint="/fapi/v1/algoOrder",
                params=kwargs,
                status_code=400,
                binance_code=-4130,
                binance_message="An open stop or take profit order with GTE and closePosition in the direction is existing.",
                headers={},
            )
        return {"algoId": 456 + self._protective_attempts, "status": "NEW", **kwargs}

    def open_algo_orders(self, symbol=None):
        self.calls.append(("open_algo_orders", symbol))
        return [
            {
                "algoId": 111,
                "symbol": symbol or "BTCUSDT",
                "side": "SELL",
                "positionSide": "LONG",
                "orderType": "STOP_MARKET",
                "closePosition": True,
            },
            {
                "algoId": 112,
                "symbol": symbol or "BTCUSDT",
                "side": "SELL",
                "positionSide": "LONG",
                "orderType": "TAKE_PROFIT_MARKET",
                "closePosition": True,
            },
        ]


class ProtectivePlacementNoPositionSignedClient(FakeSignedClient):
    def __init__(self, *, available_balance="100"):
        super().__init__(available_balance=available_balance)
        self.close_attempts = 0

    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        raise BinanceSignedError(
            endpoint="/fapi/v1/algoOrder",
            params=kwargs,
            status_code=400,
            binance_code=-2021,
            binance_message="Order would immediately trigger.",
            headers={},
        )

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        return []

    def open_algo_orders(self, symbol=None):
        self.calls.append(("open_algo_orders", symbol))
        return []


class ProtectivePlacementCloseFailsSignedClient(FakeSignedClient):
    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        raise BinanceSignedError(
            endpoint="/fapi/v1/algoOrder",
            params=kwargs,
            status_code=400,
            binance_code=-2021,
            binance_message="Order would immediately trigger.",
            headers={},
        )

    def position_risk(self, symbol=None):
        self.calls.append(("position_risk", symbol))
        return [
            {
                "symbol": symbol or "BTCUSDT",
                "positionAmt": "0.2",
                "positionSide": "LONG",
                "entryPrice": "100",
                "markPrice": "100",
            }
        ]

    def open_algo_orders(self, symbol=None):
        self.calls.append(("open_algo_orders", symbol))
        return []

    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        if kwargs.get("reduce_only"):
            raise BinanceSignedError(
                endpoint="/fapi/v1/order",
                params=kwargs,
                status_code=400,
                binance_code=-2019,
                binance_message="synthetic emergency close failure",
                headers={},
            )
        return {"orderId": 123, "status": "NEW", **kwargs}


class AccountFailingSignedClient(FakeSignedClient):
    def account(self):
        self.calls.append(("account",))
        raise BinanceSignedError(
            endpoint="/fapi/v3/account",
            params={},
            status_code=400,
            binance_code=-1021,
            binance_message="Timestamp for this request is outside of the recvWindow.",
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
        self.assertEqual(fake_client.calls[0], ("account",))
        self.assertEqual(fake_client.calls[1], ("margin", "BTCUSDT", "ISOLATED"))
        self.assertEqual(fake_client.calls[2], ("leverage", "BTCUSDT", 3))
        self.assertEqual(fake_client.calls[3][0], "new_order")
        self.assertEqual(fake_client.calls[4][0], "new_algo_order")
        self.assertEqual(fake_client.calls[4][1]["order_type"], "STOP_MARKET")
        self.assertEqual(fake_client.calls[4][1]["side"], "SELL")
        self.assertEqual(fake_client.calls[5][0], "new_algo_order")
        self.assertEqual(fake_client.calls[5][1]["order_type"], "TAKE_PROFIT_MARKET")
        self.assertEqual(fake_client.calls[5][1]["side"], "SELL")
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
        self.assertEqual(fake_client.calls[1], ("margin", "BTCUSDT", "CROSSED"))
        self.assertEqual(fake_client.calls[2], ("leverage", "BTCUSDT", 3))

    def test_live_downshifts_invalid_exchange_leverage_before_order(self):
        fake_client = InvalidHighLeverageSignedClient(accepted_leverage=20)
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_MAX_LEVERAGE="30",
                BFA_MAX_POSITION_NOTIONAL_USDT="120",
                BFA_MAX_PORTFOLIO_MARGIN_USDT="12",
                BFA_MAX_PORTFOLIO_NOTIONAL_USDT="320",
                BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT="180",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
            risk_limits=RiskLimits(
                account_capital_usdt=100,
                max_leverage=30,
                max_position_notional_usdt=120,
                max_risk_per_trade_usdt=1,
                max_daily_loss_usdt=3,
                max_open_positions=2,
            ),
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(notional_usdt=20.0, reasons=["entry_order_type:limit"]),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(account_available_balance_usdt=100),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "submitted")
        self.assertTrue(result.submitted)
        self.assertEqual(
            [call for call in fake_client.calls if call[0] == "leverage"],
            [
                ("leverage", "BTCUSDT", 30),
                ("leverage", "BTCUSDT", 25),
                ("leverage", "BTCUSDT", 20),
            ],
        )
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.leverage, 20)
        self.assertIn("exchange_leverage_downshifted:30_to_20", result.intent.reason_codes)
        self.assertEqual(result.intent.metadata["requested_leverage"], 30)
        self.assertEqual(result.intent.metadata["exchange_effective_leverage"], 20)
        self.assertEqual(result.exchange_response["margin_setup"]["leverage"]["effective_leverage"], 20)
        self.assertEqual(result.exchange_response["entry_order"]["order_type"], "LIMIT")

    def test_live_hedge_position_mode_sends_position_side(self):
        fake_client = FakeSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_POSITION_MODE="hedge",
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
        self.assertEqual(fake_client.calls[3][1]["position_side"], "LONG")
        self.assertEqual(fake_client.calls[4][1]["position_side"], "LONG")
        self.assertEqual(fake_client.calls[5][1]["position_side"], "LONG")

    def test_live_insufficient_available_balance_rejects_before_exchange_order_calls(self):
        fake_client = FakeSignedClient(available_balance="0")
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
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

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.submitted)
        self.assertIn("insufficient_available_balance", result.risk.reason_codes)
        self.assertEqual(fake_client.calls, [("account",)])

    def test_live_account_balance_error_rejects_before_exchange_order_calls(self):
        fake_client = AccountFailingSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
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

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.submitted)
        self.assertIn("account_balance_check_failed:-1021", result.risk.reason_codes)
        self.assertEqual(fake_client.calls, [("account",)])

    def test_entry_order_error_fails_closed_before_submission(self):
        fake_client = EntryFailingSignedClient()
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
        self.assertIn("entry_order_failed", result.risk.reason_codes)
        self.assertEqual([call[0] for call in fake_client.calls], ["account", "margin", "leverage", "new_order"])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"],
            1,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM exchange_responses").fetchone()["count"],
            1,
        )

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
        self.assertEqual(fake_client.calls, [("account",), ("margin", "BTCUSDT", "ISOLATED")])
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

    def test_live_limit_entry_uses_post_only_price_and_places_protection_after_fill(self):
        fake_client = LimitFilledSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "entry_order_type:limit",
                    "entry_time_in_force:GTX",
                    "limit_entry_max_wait_seconds:1",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "submitted")
        self.assertTrue(result.submitted)
        self.assertEqual([call[0] for call in fake_client.calls], ["account", "margin", "leverage", "new_order", "query_order", "new_algo_order", "new_algo_order"])
        entry_call = fake_client.calls[3][1]
        self.assertEqual(entry_call["order_type"], "LIMIT")
        self.assertEqual(entry_call["price"], 100.0)
        self.assertEqual(entry_call["time_in_force"], "GTX")
        self.assertEqual(result.intent.quantity, 0.2)
        self.assertEqual(result.intent.entry_price, 100.0)

    def test_intent_metadata_preserves_regime_route_fields(self):
        engine = ExecutionEngine(config=self.config())

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "regime_label:RANGE",
                    "route_decision:allow",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.intent.metadata["strategy_leg"], "micro_grid")
        self.assertEqual(result.intent.metadata["regime_label"], "RANGE")
        self.assertEqual(result.intent.metadata["route_decision"], "allow")

    def test_execution_metadata_preserves_latency_telemetry(self):
        engine = ExecutionEngine(config=self.config())

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "regime_label:RANGE",
                    "route_decision:allow",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
            telemetry={
                "signal_time_ms": 1_700_000_000_000,
                "signal_to_candidate_ms": 1200,
                "ai_latency": {"duration_ms": 0, "bypassed": True},
            },
        )

        self.assertEqual(result.status, "dry_run")
        latency = result.intent.metadata["latency"]
        self.assertEqual(latency["signal_to_candidate_ms"], 1200)
        self.assertEqual(latency["ai_latency"]["bypassed"], True)
        self.assertIn("execution_run_started_at_ms", latency)

    def test_live_limit_entry_cancels_when_not_filled_and_skips_protection(self):
        fake_client = LimitExpiredSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        with patch("bfa.execution.executor.time.monotonic", side_effect=[0.0, 2.0]):
            result = engine.run(
                symbol="BTCUSDT",
                validation=self.validation(
                    reasons=[
                        "strategy_leg:micro_grid",
                        "entry_order_type:limit",
                        "entry_time_in_force:GTX",
                        "limit_entry_max_wait_seconds:1",
                    ]
                ),
                decided_at="2026-06-20T10:00:00Z",
                risk_state=RiskState(),
                filters=self.filters(),
            )

        self.assertEqual(result.status, "entry_order_expired_canceled")
        self.assertFalse(result.submitted)
        self.assertIn("entry_order_expired_canceled", result.risk.reason_codes)
        self.assertEqual([call[0] for call in fake_client.calls], ["account", "margin", "leverage", "new_order", "query_order", "cancel_order", "query_order"])
        self.assertNotIn("new_algo_order", [call[0] for call in fake_client.calls])

    def test_live_limit_entry_unknown_state_reconciles_position_and_places_protection(self):
        fake_client = LimitUnknownFilledPositionSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_POSITION_MODE="hedge",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "entry_order_type:limit",
                    "entry_time_in_force:GTX",
                    "limit_entry_max_wait_seconds:1",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "entry_order_reconciled_from_position")
        self.assertTrue(result.submitted)
        self.assertEqual(
            [call[0] for call in fake_client.calls],
            ["account", "margin", "leverage", "new_order", "query_order", "position_risk", "new_algo_order", "new_algo_order"],
        )
        self.assertEqual(result.intent.quantity, 0.2)
        self.assertEqual(result.intent.entry_price, 100.0)
        self.assertIn("limit_entry_reconciled_from_position", result.intent.reason_codes)
        self.assertEqual(result.exchange_response["limit_entry_position_reconcile"]["status"], "position_found")
        self.assertEqual(result.exchange_response["stop_loss_order"]["order_type"], "STOP_MARKET")
        self.assertEqual(result.exchange_response["take_profit_order"]["order_type"], "TAKE_PROFIT_MARKET")

    def test_live_limit_entry_unknown_state_without_position_cancels_instead_of_leaving_pending(self):
        fake_client = LimitUnknownNoPositionSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_POSITION_MODE="hedge",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "entry_order_type:limit",
                    "entry_time_in_force:GTX",
                    "limit_entry_max_wait_seconds:1",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "entry_order_unknown_canceled")
        self.assertFalse(result.submitted)
        self.assertIn("entry_order_unknown_canceled", result.risk.reason_codes)
        self.assertEqual(
            [call[0] for call in fake_client.calls],
            ["account", "margin", "leverage", "new_order", "query_order", "position_risk", "cancel_order"],
        )
        self.assertNotIn("new_algo_order", [call[0] for call in fake_client.calls])
        self.assertEqual(result.exchange_response["limit_entry_unknown_resolution"], "cancel_attempted_after_query_not_found")

    def test_live_post_only_entry_reprices_after_maker_reject(self):
        fake_client = PostOnlyRejectThenAcceptSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_POST_ONLY_REPRICE_TICKS="2",
                BFA_POST_ONLY_REPRICE_MAX_ATTEMPTS="3",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
            ),
            signed_client=fake_client,
        )

        result = engine.run(
            symbol="BTCUSDT",
            validation=self.validation(
                reasons=[
                    "strategy_leg:micro_grid",
                    "entry_order_type:limit",
                    "entry_time_in_force:GTX",
                    "limit_entry_max_wait_seconds:1",
                ]
            ),
            decided_at="2026-06-20T10:00:00Z",
            risk_state=RiskState(),
            filters=self.filters(),
        )

        self.assertEqual(result.status, "submitted")
        entry_calls = [call[1] for call in fake_client.calls if call[0] == "new_order"]
        self.assertEqual(len(entry_calls), 2)
        self.assertEqual(entry_calls[0]["price"], 100.0)
        self.assertEqual(entry_calls[1]["price"], 99.8)
        self.assertEqual(entry_calls[1]["new_client_order_id"], "bfa-btcusdt-20260620100000-r1")
        self.assertIn("post_only_repriced_attempt:2", result.intent.reason_codes)
        self.assertEqual(result.intent.entry_price, 99.8)
        self.assertIn("micro_grid_reprice_reanchored_protective_prices", result.intent.reason_codes)
        self.assertIn("micro_grid_fill_reanchored_protective_prices", result.intent.reason_codes)
        self.assertAlmostEqual(result.intent.stop_price, 95.808)
        self.assertEqual(result.intent.target_price, 108.0)
        self.assertIn("micro_grid_reprice_reanchor", result.intent.metadata)
        reanchor = result.intent.metadata["micro_grid_fill_reanchor"]
        self.assertEqual(reanchor["fill_quality"], "better_or_equal")
        stop_order = [call[1] for call in fake_client.calls if call[0] == "new_algo_order" and call[1]["order_type"] == "STOP_MARKET"][0]
        target_order = [call[1] for call in fake_client.calls if call[0] == "new_algo_order" and call[1]["order_type"] == "TAKE_PROFIT_MARKET"][0]
        self.assertAlmostEqual(stop_order["stop_price"], 95.808)
        self.assertEqual(target_order["stop_price"], 108.0)
        reprice = result.exchange_response["entry_order"]["post_only_reprice"]
        self.assertTrue(reprice["enabled"])
        self.assertEqual([attempt["status"] for attempt in reprice["attempts"]], ["rejected", "accepted"])

    def test_live_replaces_conflicting_close_position_algo_orders_before_fail_closed(self):
        fake_client = ConflictingProtectiveOrderSignedClient()
        engine = ExecutionEngine(
            config=self.config(
                BFA_MODE="live",
                BFA_POSITION_MODE="hedge",
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
        self.assertTrue(result.submitted)
        self.assertNotIn("kill_switch_activated", result.exchange_response)
        self.assertEqual(result.exchange_response["protective_error"]["code"], -4130)
        self.assertEqual(
            result.exchange_response["protective_recovery"]["reason"],
            "existing_close_position_algo_conflict",
        )
        self.assertEqual(
            [call[0] for call in fake_client.calls],
            [
                "account",
                "margin",
                "leverage",
                "new_order",
                "new_algo_order",
                "open_algo_orders",
                "cancel_algo_order",
                "cancel_algo_order",
                "new_algo_order",
                "new_algo_order",
            ],
        )

    def test_live_protective_failure_without_matching_position_does_not_activate_kill_switch(self):
        fake_client = ProtectivePlacementNoPositionSignedClient()
        with tempfile.TemporaryDirectory() as tmp:
            kill_switch = Path(tmp) / "KILL_SWITCH"
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
                risk_state=RiskState(),
                filters=self.filters(),
            )

            self.assertFalse(kill_switch.exists())

        self.assertEqual(result.status, "protective_order_failed_no_position")
        self.assertTrue(result.submitted)
        self.assertEqual(result.exchange_response["protective_failure_resolution"]["status"], "no_matching_position")
        self.assertNotIn("kill_switch_activated", result.exchange_response)
        self.assertEqual(
            [call[0] for call in fake_client.calls],
            ["account", "margin", "leverage", "new_order", "new_algo_order", "position_risk"],
        )

    def test_live_protective_failure_does_not_activate_kill_switch_even_when_emergency_close_fails(self):
        fake_client = ProtectivePlacementCloseFailsSignedClient()
        with tempfile.TemporaryDirectory() as tmp:
            kill_switch = Path(tmp) / "KILL_SWITCH"
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
                risk_state=RiskState(),
                filters=self.filters(),
            )

            self.assertFalse(kill_switch.exists())

        self.assertEqual(result.status, "protective_order_failed_open")
        self.assertNotIn("kill_switch_activated", result.exchange_response)
        self.assertIn("emergency_close_error", result.exchange_response)
        self.assertEqual(
            [call[0] for call in fake_client.calls],
            [
                "account",
                "margin",
                "leverage",
                "new_order",
                "new_algo_order",
                "position_risk",
                "open_algo_orders",
                "new_algo_order",
                "new_algo_order",
                "new_order",
            ],
        )


if __name__ == "__main__":
    unittest.main()
