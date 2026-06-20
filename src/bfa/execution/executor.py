"""Risk-gated execution engine."""

from __future__ import annotations

from dataclasses import dataclass

from bfa.ai.schema import DecisionValidationResult, RiskLimits
from bfa.config import AppConfig, RuntimeMode
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import ExecutionResult, OrderIntent, RiskDecision, RiskState
from bfa.execution.risk import evaluate_risk, intent_from_ai_decision
from bfa.execution.store import persist_exchange_response, persist_order_intent


@dataclass
class ExecutionEngine:
    config: AppConfig
    signed_client: BinanceFuturesSignedClient | None = None
    store: EventStore | None = None

    def run(
        self,
        *,
        symbol: str,
        validation: DecisionValidationResult,
        decided_at: str,
        risk_state: RiskState | None = None,
        filters: SymbolExecutionFilters | None = None,
        now: str | None = None,
    ) -> ExecutionResult:
        mode = RuntimeMode(self.config.get("BFA_MODE"))
        risk_limits = RiskLimits.from_config(self.config)
        state = risk_state or RiskState()
        current_time = now or decided_at
        intent, intent_risk = intent_from_ai_decision(
            symbol=symbol,
            validation=validation,
            risk_limits=risk_limits,
            mode=mode,
            decided_at=decided_at,
            filters=filters,
        )
        if not intent_risk.accepted:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=intent_risk,
            )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=risk_limits,
            risk_state=state,
            mode=mode,
            config=self.config,
            now=current_time,
        )
        if not risk.accepted:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=risk,
            )

        assert intent is not None
        if mode is RuntimeMode.DRY_RUN:
            return self._finish(
                status="dry_run",
                submitted=False,
                intent=intent,
                risk=risk,
            )

        if self.signed_client is None:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=RiskDecision(False, ["missing_signed_client"]),
            )

        if mode is RuntimeMode.TESTNET:
            response = self.signed_client.test_order(
                symbol=intent.symbol,
                side=intent.side,
                order_type=intent.order_type,
                quantity=intent.quantity,
                position_side=_position_side(intent, self.config),
            )
            return self._finish(
                status="test_order_checked",
                submitted=False,
                intent=intent,
                risk=risk,
                exchange_response=response,
                exchange_response_type="test_order",
            )

        balance_risk = self._check_live_available_balance(intent)
        if not balance_risk.accepted:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=balance_risk,
            )
        try:
            self._ensure_live_margin(intent)
        except BinanceSignedError as exc:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=RiskDecision(False, ["margin_setup_failed"]),
                exchange_response={
                    "margin_error": {
                        "endpoint": exc.endpoint,
                        "code": exc.binance_code,
                        "message": exc.binance_message,
                    }
                },
                exchange_response_type="margin_setup_error",
            )
        position_side = _position_side(intent, self.config)
        try:
            entry_response = self.signed_client.new_order(
                symbol=intent.symbol,
                side=intent.side,
                order_type=intent.order_type,
                quantity=intent.quantity,
                reduce_only=intent.reduce_only,
                position_side=position_side,
                new_client_order_id=_client_order_id(intent),
            )
        except BinanceSignedError as exc:
            return self._finish(
                status="rejected",
                submitted=False,
                intent=intent,
                risk=RiskDecision(False, ["entry_order_failed"]),
                exchange_response={
                    "entry_error": {
                        "endpoint": exc.endpoint,
                        "code": exc.binance_code,
                        "message": exc.binance_message,
                    }
                },
                exchange_response_type="entry_order_error",
            )
        response = {"entry_order": entry_response}
        if _protective_orders_required(self.config):
            try:
                response.update(self._place_protective_orders(intent))
            except BinanceSignedError as exc:
                response["protective_error"] = {
                    "endpoint": exc.endpoint,
                    "code": exc.binance_code,
                    "message": exc.binance_message,
                }
                response["kill_switch_activated"] = _activate_kill_switch(self.config)
                try:
                    response["emergency_close_order"] = self.signed_client.new_order(
                        symbol=intent.symbol,
                        side=_opposite_side(intent.side),
                        order_type="MARKET",
                        quantity=intent.quantity,
                        reduce_only=_reduce_only_supported(self.config),
                        position_side=position_side,
                        new_client_order_id=_client_order_id(intent, suffix="close"),
                    )
                    status = "protective_order_failed_closed"
                except BinanceSignedError as close_exc:
                    response["emergency_close_error"] = {
                        "endpoint": close_exc.endpoint,
                        "code": close_exc.binance_code,
                        "message": close_exc.binance_message,
                    }
                    status = "protective_order_failed_open"
                return self._finish(
                    status=status,
                    submitted=True,
                    intent=intent,
                    risk=risk,
                    exchange_response=response,
                )
        return self._finish(
            status="submitted",
            submitted=True,
            intent=intent,
            risk=risk,
            exchange_response=response,
        )

    def _check_live_available_balance(self, intent: OrderIntent) -> RiskDecision:
        assert self.signed_client is not None
        try:
            account = self.signed_client.account()
        except BinanceSignedError as exc:
            return RiskDecision(False, [f"account_balance_check_failed:{exc.binance_code or 'unknown'}"])
        available = _float(account.get("availableBalance"))
        required = intent.estimated_initial_margin_usdt
        if available is None:
            return RiskDecision(False, ["account_available_balance_unknown"])
        if available < required:
            return RiskDecision(
                False,
                ["insufficient_available_balance"],
                [f"available_balance:{available:.8f}", f"required_initial_margin:{required:.8f}"],
            )
        return RiskDecision(True, ["available_balance_ok"])

    def _finish(
        self,
        *,
        status: str,
        submitted: bool,
        intent: OrderIntent | None,
        risk: RiskDecision,
        exchange_response: dict | None = None,
        exchange_response_type: str = "new_order",
    ) -> ExecutionResult:
        persisted: dict[str, int] = {}
        if self.store is not None and intent is not None:
            persisted["order_intent"] = persist_order_intent(
                self.store,
                intent=intent,
                status=status,
                risk=risk,
            )
            if exchange_response is not None:
                persisted["exchange_response"] = persist_exchange_response(
                    self.store,
                    intent=intent,
                    response=exchange_response,
                    response_type=exchange_response_type,
                )
        return ExecutionResult(
            status=status,
            submitted=submitted,
            intent=intent,
            risk=risk,
            exchange_response=exchange_response,
            persisted=persisted,
        )

    def _ensure_live_margin(self, intent: OrderIntent) -> None:
        assert self.signed_client is not None
        margin_type = _binance_margin_type(self.config)
        try:
            self.signed_client.change_margin_type(intent.symbol, margin_type=margin_type)
        except BinanceSignedError as exc:
            if exc.binance_code != -4046:
                raise
        self.signed_client.change_initial_leverage(intent.symbol, leverage=intent.leverage)

    def _place_protective_orders(self, intent: OrderIntent) -> dict[str, dict]:
        assert self.signed_client is not None
        close_side = _opposite_side(intent.side)
        position_side = _position_side(intent, self.config)
        return {
            "stop_loss_order": self.signed_client.new_algo_order(
                symbol=intent.symbol,
                side=close_side,
                order_type="STOP_MARKET",
                stop_price=intent.stop_price,
                close_position=True,
                position_side=position_side,
                client_algo_id=_client_order_id(intent, suffix="sl"),
            ),
            "take_profit_order": self.signed_client.new_algo_order(
                symbol=intent.symbol,
                side=close_side,
                order_type="TAKE_PROFIT_MARKET",
                stop_price=intent.target_price,
                close_position=True,
                position_side=position_side,
                client_algo_id=_client_order_id(intent, suffix="tp"),
            ),
        }


def _client_order_id(intent: OrderIntent, *, suffix: str | None = None) -> str:
    cleaned_time = "".join(ch for ch in intent.decided_at if ch.isdigit())
    base = f"bfa-{intent.symbol.lower()}-{cleaned_time}"
    if suffix:
        suffix_text = f"-{suffix}"
        return f"{base[: 36 - len(suffix_text)]}{suffix_text}"
    return base[:36]


def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def _protective_orders_required(config: AppConfig) -> bool:
    return config.get("BFA_REQUIRE_PROTECTIVE_ORDERS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _binance_margin_type(config: AppConfig) -> str:
    margin_mode = config.get("BFA_MARGIN_MODE", "isolated").strip().lower()
    if margin_mode == "cross":
        return "CROSSED"
    return "ISOLATED"


def _position_side(intent: OrderIntent, config: AppConfig) -> str | None:
    if config.get("BFA_POSITION_MODE", "one_way").strip().lower() != "hedge":
        return None
    return "LONG" if intent.side.upper() == "BUY" else "SHORT"


def _reduce_only_supported(config: AppConfig) -> bool:
    return config.get("BFA_POSITION_MODE", "one_way").strip().lower() != "hedge"


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _activate_kill_switch(config: AppConfig) -> bool:
    path = config.get("BFA_KILL_SWITCH_FILE")
    if not path:
        return False
    from pathlib import Path

    kill_switch = Path(path)
    kill_switch.parent.mkdir(parents=True, exist_ok=True)
    kill_switch.write_text("protective order failure\n", encoding="utf-8")
    return True
