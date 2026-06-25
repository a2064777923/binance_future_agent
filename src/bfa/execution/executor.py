"""Risk-gated execution engine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import time
from typing import Any, Mapping

from bfa.ai.schema import DecisionValidationResult, RiskLimits
from bfa.config import AppConfig, RuntimeMode
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import ExecutionResult, OrderIntent, RiskDecision, RiskState
from bfa.execution.risk import evaluate_risk, intent_from_ai_decision
from bfa.execution.store import persist_exchange_response, persist_order_intent


@dataclass
class LimitEntryResolution:
    status: str
    submitted: bool
    intent: OrderIntent
    response: dict


@dataclass
class MarginSetupResolution:
    intent: OrderIntent
    response: dict


@dataclass
class EntryOrderSubmission:
    intent: OrderIntent
    client_order_id: str
    response: dict


@dataclass
class ExecutionEngine:
    config: AppConfig
    signed_client: BinanceFuturesSignedClient | None = None
    store: EventStore | None = None
    risk_limits: RiskLimits | None = None

    def run(
        self,
        *,
        symbol: str,
        validation: DecisionValidationResult,
        decided_at: str,
        risk_state: RiskState | None = None,
        filters: SymbolExecutionFilters | None = None,
        now: str | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        run_started_at_ms = _epoch_ms()
        mode = RuntimeMode(self.config.get("BFA_MODE"))
        risk_limits = self.risk_limits or RiskLimits.from_config(self.config)
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
        if intent is not None:
            intent = _intent_with_latency(
                intent,
                telemetry,
                execution_run_started_at_ms=run_started_at_ms,
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
                price=_entry_order_price(intent),
                time_in_force=_entry_time_in_force(intent),
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
            margin_setup = self._ensure_live_margin(intent)
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
        intent = margin_setup.intent
        if margin_setup.response.get("leverage_downshifted"):
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
                    exchange_response={"margin_setup": margin_setup.response},
                    exchange_response_type="margin_setup_risk_reject",
                )
            balance_risk = self._check_live_available_balance(intent)
            if not balance_risk.accepted:
                return self._finish(
                    status="rejected",
                    submitted=False,
                    intent=intent,
                    risk=balance_risk,
                    exchange_response={"margin_setup": margin_setup.response},
                    exchange_response_type="margin_setup_balance_reject",
                )
        position_side = _position_side(intent, self.config)
        client_order_id = _client_order_id(intent)
        try:
            entry_submit_started_at_ms = _epoch_ms()
            entry_submission = self._submit_entry_order_with_reprice(
                intent,
                client_order_id=client_order_id,
                position_side=position_side,
                filters=filters,
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
        intent = entry_submission.intent
        intent = _intent_with_latency(
            intent,
            None,
            entry_submit_started_at_ms=entry_submit_started_at_ms,
            entry_submit_finished_at_ms=_epoch_ms(),
            entry_order_latency=entry_submission.response.get("_bfa_latency"),
        )
        client_order_id = entry_submission.client_order_id
        response = {"margin_setup": margin_setup.response, "entry_order": entry_submission.response}
        status = "submitted"
        active_intent = intent
        if _is_limit_order(intent):
            try:
                resolution = self._resolve_limit_entry(intent, client_order_id=client_order_id)
            except BinanceSignedError as exc:
                response["limit_entry_error"] = {
                    "endpoint": exc.endpoint,
                    "code": exc.binance_code,
                    "message": exc.binance_message,
                }
                reconciled_intent, reconcile_response = self._reconcile_unknown_limit_entry_from_position(intent)
                response["limit_entry_position_reconcile"] = reconcile_response
                if reconciled_intent is None:
                    cancel_resolution = self._cancel_unknown_limit_entry(
                        intent,
                        client_order_id=client_order_id,
                        error=exc,
                    )
                    response.update(cancel_resolution.response)
                    return self._finish(
                        status=cancel_resolution.status,
                        submitted=False,
                        intent=cancel_resolution.intent,
                        risk=RiskDecision(True, [*risk.reason_codes, cancel_resolution.status], risk.warnings),
                        exchange_response=response,
                    )
                status = "entry_order_reconciled_from_position"
                active_intent = reconciled_intent
            else:
                response.update(resolution.response)
                status = resolution.status
                active_intent = resolution.intent
                if not resolution.submitted:
                    return self._finish(
                        status=status,
                        submitted=False,
                        intent=intent,
                        risk=RiskDecision(True, [*risk.reason_codes, status], risk.warnings),
                        exchange_response=response,
                    )
        if _protective_orders_required(self.config):
            try:
                response.update(self._place_protective_orders(active_intent))
            except BinanceSignedError as exc:
                response["protective_error"] = {
                    "endpoint": exc.endpoint,
                    "code": exc.binance_code,
                    "message": exc.binance_message,
                }
                if _is_existing_close_position_algo_error(exc):
                    try:
                        recovery = self._replace_conflicting_protective_orders(active_intent)
                    except BinanceSignedError as recovery_exc:
                        response["protective_recovery_error"] = {
                            "endpoint": recovery_exc.endpoint,
                            "code": recovery_exc.binance_code,
                            "message": recovery_exc.binance_message,
                        }
                    else:
                        response.update(recovery)
                        return self._finish(
                            status=status,
                            submitted=True,
                            intent=active_intent,
                            risk=risk,
                            exchange_response=response,
                        )
                failure_resolution = self._resolve_protective_order_failure(
                    active_intent,
                    position_side=position_side,
                )
                response["protective_failure_resolution"] = failure_resolution
                resolution_status = str(failure_resolution.get("status") or "")
                if resolution_status in {
                    "no_matching_position",
                    "existing_protective_orders_present",
                    "fallback_protective_orders_submitted",
                    "fallback_stop_submitted",
                }:
                    return self._finish(
                        status=_status_for_protective_resolution(resolution_status, current_status=status),
                        submitted=True,
                        intent=active_intent,
                        risk=risk,
                        exchange_response=response,
                    )
                if resolution_status == "emergency_closed":
                    response["emergency_close_order"] = failure_resolution.get("emergency_close", {}).get("order")
                    status = "protective_order_failed_closed"
                else:
                    emergency_close = failure_resolution.get("emergency_close")
                    if isinstance(emergency_close, Mapping) and emergency_close.get("status") == "failed":
                        response["emergency_close_error"] = {
                            "endpoint": emergency_close.get("endpoint"),
                            "code": emergency_close.get("code"),
                            "message": emergency_close.get("message"),
                        }
                    status = "protective_order_failed_open"
                return self._finish(
                    status=status,
                    submitted=True,
                    intent=active_intent,
                    risk=risk,
                    exchange_response=response,
                )
        return self._finish(
            status=status,
            submitted=True,
            intent=active_intent,
            risk=risk,
            exchange_response=response,
        )

    def _submit_entry_order_with_reprice(
        self,
        intent: OrderIntent,
        *,
        client_order_id: str,
        position_side: str | None,
        filters: SymbolExecutionFilters | None,
    ) -> EntryOrderSubmission:
        assert self.signed_client is not None
        attempts: list[dict] = []
        last_error: BinanceSignedError | None = None
        current_intent = intent
        current_client_order_id = client_order_id
        max_attempts = _post_only_reprice_max_attempts(self.config, intent, filters)
        for attempt_index in range(max_attempts):
            attempt_started_at_ms = _epoch_ms()
            if attempt_index > 0:
                current_intent = _repriced_post_only_intent(
                    intent,
                    filters=filters,
                    attempt_index=attempt_index,
                    ticks_per_attempt=_post_only_reprice_ticks(self.config),
                )
                current_client_order_id = _client_order_id(intent, suffix=f"r{attempt_index}")
            try:
                response = self.signed_client.new_order(
                    symbol=current_intent.symbol,
                    side=current_intent.side,
                    order_type=current_intent.order_type,
                    quantity=current_intent.quantity,
                    price=_entry_order_price(current_intent),
                    time_in_force=_entry_time_in_force(current_intent),
                    reduce_only=current_intent.reduce_only,
                    position_side=position_side,
                    new_client_order_id=current_client_order_id,
                )
            except BinanceSignedError as exc:
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "client_order_id": current_client_order_id,
                        "price": _entry_order_price(current_intent),
                        "status": "rejected",
                        "code": exc.binance_code,
                        "message": exc.binance_message,
                        "started_at_ms": attempt_started_at_ms,
                        "finished_at_ms": _epoch_ms(),
                    }
                )
                last_error = exc
                if not _is_post_only_repriceable_error(exc) or attempt_index + 1 >= max_attempts:
                    raise
                continue
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "client_order_id": current_client_order_id,
                    "price": _entry_order_price(current_intent),
                    "status": "accepted",
                    "started_at_ms": attempt_started_at_ms,
                    "finished_at_ms": _epoch_ms(),
                }
            )
            latency = _submit_latency(attempts)
            if attempt_index == 0:
                return EntryOrderSubmission(
                    intent=current_intent,
                    client_order_id=current_client_order_id,
                    response={**dict(response), "_bfa_latency": latency},
                )
            return EntryOrderSubmission(
                intent=replace(
                    current_intent,
                    reason_codes=[
                        *current_intent.reason_codes,
                        f"post_only_repriced_attempt:{attempt_index + 1}",
                    ],
                    metadata={
                        **current_intent.metadata,
                        "post_only_reprice": {
                            "enabled": True,
                            "attempts": attempts,
                            "original_entry_price": intent.entry_price,
                            "final_entry_price": current_intent.entry_price,
                        },
                    },
                ),
                client_order_id=current_client_order_id,
                response={
                    **dict(response),
                    "_bfa_latency": latency,
                    "post_only_reprice": {
                        "enabled": True,
                        "attempts": attempts,
                        "original_entry_price": intent.entry_price,
                        "final_entry_price": current_intent.entry_price,
                    },
                },
            )
        if last_error is not None:
            raise last_error
        raise BinanceSignedError(
            endpoint="/fapi/v1/order",
            params={"symbol": intent.symbol},
            status_code=None,
            binance_code=None,
            binance_message="entry order was not submitted",
            headers={},
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
        if exchange_response is not None and intent is not None:
            exchange_response = dict(exchange_response)
            latency = intent.metadata.get("latency") if isinstance(intent.metadata, dict) else None
            if isinstance(latency, dict):
                exchange_response["execution_latency"] = dict(latency)
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

    def _ensure_live_margin(self, intent: OrderIntent) -> MarginSetupResolution:
        assert self.signed_client is not None
        margin_type = _binance_margin_type(self.config)
        response: dict[str, dict] = {}
        try:
            response["margin_type"] = self.signed_client.change_margin_type(intent.symbol, margin_type=margin_type)
        except BinanceSignedError as exc:
            if exc.binance_code != -4046:
                raise
            response["margin_type"] = {
                "status": "already_configured",
                "endpoint": exc.endpoint,
                "code": exc.binance_code,
                "message": exc.binance_message,
            }
        leverage, leverage_response = self._change_initial_leverage_with_fallback(intent.symbol, intent.leverage)
        response["leverage"] = leverage_response
        if leverage == intent.leverage:
            return MarginSetupResolution(intent=intent, response=response)
        response["leverage_downshifted"] = True
        adjusted = replace(
            intent,
            leverage=leverage,
            reason_codes=[
                *intent.reason_codes,
                f"exchange_leverage_downshifted:{intent.leverage}_to_{leverage}",
            ],
            metadata={
                **intent.metadata,
                "requested_leverage": intent.leverage,
                "exchange_effective_leverage": leverage,
            },
        )
        return MarginSetupResolution(intent=adjusted, response=response)

    def _change_initial_leverage_with_fallback(self, symbol: str, requested_leverage: int) -> tuple[int, dict]:
        assert self.signed_client is not None
        requested = max(int(requested_leverage), 1)
        attempts: list[dict] = []
        last_error: BinanceSignedError | None = None
        for leverage in _leverage_fallback_sequence(requested):
            try:
                response = self.signed_client.change_initial_leverage(symbol, leverage=leverage)
            except BinanceSignedError as exc:
                attempts.append(
                    {
                        "leverage": leverage,
                        "status": "rejected",
                        "code": exc.binance_code,
                        "message": exc.binance_message,
                    }
                )
                last_error = exc
                if not _is_invalid_leverage_error(exc):
                    raise
                continue
            effective = _effective_leverage_from_response(response, fallback=leverage)
            attempts.append({"leverage": leverage, "status": "accepted", "effective_leverage": effective})
            return effective, {
                "requested_leverage": requested,
                "effective_leverage": effective,
                "attempts": attempts,
                "response": response,
            }
        if last_error is not None:
            raise last_error
        raise BinanceSignedError(
            endpoint="/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": str(requested)},
            status_code=None,
            binance_code=None,
            binance_message="unable to set leverage",
            headers={},
        )

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

    def _replace_conflicting_protective_orders(self, intent: OrderIntent) -> dict[str, Any]:
        assert self.signed_client is not None
        cancelled = self._cancel_conflicting_protective_orders(intent)
        replacement = self._place_protective_orders(intent)
        return {
            "protective_recovery": {
                "reason": "existing_close_position_algo_conflict",
                "cancelled_algo_orders": cancelled,
            },
            **replacement,
        }

    def _cancel_conflicting_protective_orders(self, intent: OrderIntent) -> list[dict[str, Any]]:
        assert self.signed_client is not None
        close_side = _opposite_side(intent.side)
        position_side = _position_side(intent, self.config)
        cancelled: list[dict[str, Any]] = []
        for order in self.signed_client.open_algo_orders(intent.symbol):
            if not _matching_close_position_algo_order(
                order,
                symbol=intent.symbol,
                side=close_side,
                position_side=position_side,
            ):
                continue
            algo_id = order.get("algoId")
            client_algo_id = order.get("clientAlgoId")
            try:
                cancelled.append(
                    self.signed_client.cancel_algo_order(
                        symbol=intent.symbol,
                        algo_id=algo_id,
                        client_algo_id=client_algo_id if algo_id is None else None,
                    )
                )
            except BinanceSignedError as exc:
                if not _is_stale_unknown_order_error(exc):
                    raise
                cancelled.append(
                    {
                        "status": "stale_missing",
                        "symbol": intent.symbol,
                        "algoId": algo_id,
                        "clientAlgoId": client_algo_id,
                        "warning": _signed_error_payload(exc),
                    }
                )
        return cancelled

    def _resolve_protective_order_failure(
        self,
        intent: OrderIntent,
        *,
        position_side: str | None,
    ) -> dict[str, Any]:
        assert self.signed_client is not None
        position = self._matching_position_snapshot(intent, position_side=position_side)
        response: dict[str, Any] = {"position": position}
        if position.get("status") == "no_matching_position":
            response["status"] = "no_matching_position"
            return response

        existing = self._existing_protective_snapshot(intent, position_side=position_side)
        response["existing_protective_orders"] = existing
        existing_types = set(existing.get("types") or [])
        if {"STOP", "TAKE_PROFIT"}.issubset(existing_types):
            response["status"] = "existing_protective_orders_present"
            return response

        fallback = self._place_fallback_protective_orders(
            intent,
            position=position,
            position_side=position_side,
            existing_types=existing_types,
        )
        response["fallback_protective_orders"] = fallback
        fallback_types = existing_types | set(fallback.get("submitted_types") or [])
        if {"STOP", "TAKE_PROFIT"}.issubset(fallback_types):
            response["status"] = "fallback_protective_orders_submitted"
            return response
        if "STOP" in fallback_types:
            response["status"] = "fallback_stop_submitted"
            return response

        close = self._emergency_close_position(intent, position_side=position_side)
        response["emergency_close"] = close
        response["status"] = "emergency_closed" if close.get("status") == "submitted" else "emergency_close_failed"
        return response

    def _matching_position_snapshot(self, intent: OrderIntent, *, position_side: str | None) -> dict[str, Any]:
        assert self.signed_client is not None
        intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
        try:
            positions = self.signed_client.position_risk(intent.symbol)
        except BinanceSignedError as exc:
            return {"status": "position_check_failed", **_signed_error_payload(exc)}
        for position in positions:
            if str(position.get("symbol", "")).upper() != intent.symbol.upper():
                continue
            side = str(position.get("positionSide") or "").upper()
            if position_side and side and side != position_side.upper():
                continue
            amount = _float(position.get("positionAmt")) or 0.0
            if amount == 0:
                continue
            actual_direction = "LONG" if amount > 0 else "SHORT"
            if actual_direction != intended_direction:
                continue
            return {
                "status": "open_position",
                "symbol": intent.symbol,
                "position_side": side or position_side,
                "position_amt": amount,
                "quantity": abs(amount),
                "entry_price": _float(position.get("entryPrice")) or intent.entry_price,
                "mark_price": _float(position.get("markPrice")) or intent.entry_price,
            }
        return {"status": "no_matching_position", "symbol": intent.symbol, "position_side": position_side}

    def _existing_protective_snapshot(self, intent: OrderIntent, *, position_side: str | None) -> dict[str, Any]:
        assert self.signed_client is not None
        close_side = _opposite_side(intent.side)
        try:
            orders = self.signed_client.open_algo_orders(intent.symbol)
        except BinanceSignedError as exc:
            return {"status": "open_algo_orders_failed", "types": [], **_signed_error_payload(exc)}
        matching = [
            dict(order)
            for order in orders
            if _matching_close_position_algo_order(
                order,
                symbol=intent.symbol,
                side=close_side,
                position_side=position_side,
            )
        ]
        types = sorted({_protective_order_kind(order) for order in matching if _protective_order_kind(order)})
        return {"status": "checked", "types": types, "orders": matching}

    def _place_fallback_protective_orders(
        self,
        intent: OrderIntent,
        *,
        position: Mapping[str, Any],
        position_side: str | None,
        existing_types: set[str],
    ) -> dict[str, Any]:
        assert self.signed_client is not None
        close_side = _opposite_side(intent.side)
        stop_price = _fallback_stop_price(intent, position)
        target_price = _fallback_target_price(intent, position)
        response: dict[str, Any] = {
            "submitted_types": [],
            "stop_price": stop_price,
            "target_price": target_price,
        }
        if "STOP" not in existing_types:
            try:
                response["stop_loss_order"] = self.signed_client.new_algo_order(
                    symbol=intent.symbol,
                    side=close_side,
                    order_type="STOP_MARKET",
                    stop_price=stop_price,
                    close_position=True,
                    position_side=position_side,
                    client_algo_id=_client_order_id(intent, suffix="fbsl"),
                )
                response["submitted_types"].append("STOP")
            except BinanceSignedError as exc:
                response["stop_loss_error"] = _signed_error_payload(exc)
        if "TAKE_PROFIT" not in existing_types:
            try:
                response["take_profit_order"] = self.signed_client.new_algo_order(
                    symbol=intent.symbol,
                    side=close_side,
                    order_type="TAKE_PROFIT_MARKET",
                    stop_price=target_price,
                    close_position=True,
                    position_side=position_side,
                    client_algo_id=_client_order_id(intent, suffix="fbtp"),
                )
                response["submitted_types"].append("TAKE_PROFIT")
            except BinanceSignedError as exc:
                response["take_profit_error"] = _signed_error_payload(exc)
        return response

    def _emergency_close_position(self, intent: OrderIntent, *, position_side: str | None) -> dict[str, Any]:
        assert self.signed_client is not None
        try:
            return {
                "status": "submitted",
                "order": self.signed_client.new_order(
                    symbol=intent.symbol,
                    side=_opposite_side(intent.side),
                    order_type="MARKET",
                    quantity=intent.quantity,
                    reduce_only=_reduce_only_supported(self.config),
                    position_side=position_side,
                    new_client_order_id=_client_order_id(intent, suffix="close"),
                ),
            }
        except BinanceSignedError as exc:
            return {"status": "failed", **_signed_error_payload(exc)}

    def _resolve_limit_entry(self, intent: OrderIntent, *, client_order_id: str) -> LimitEntryResolution:
        assert self.signed_client is not None
        resolution_started_at_ms = _epoch_ms()
        deadline = time.monotonic() + _limit_wait_seconds(intent)
        latest_query = dict(self.signed_client.query_order(symbol=intent.symbol, orig_client_order_id=client_order_id))
        while _order_status(latest_query) not in _TERMINAL_ORDER_STATUSES:
            if _order_status(latest_query) == "FILLED":
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.5, remaining))
            latest_query = dict(self.signed_client.query_order(symbol=intent.symbol, orig_client_order_id=client_order_id))

        status = _order_status(latest_query)
        if status == "FILLED":
            latency = _limit_resolution_latency(resolution_started_at_ms, latest_query)
            return LimitEntryResolution(
                status="submitted",
                submitted=True,
                intent=_intent_with_latency(
                    _intent_with_fill(intent, latest_query),
                    None,
                    limit_entry_resolution=latency,
                ),
                response={"entry_order_final": latest_query, "limit_entry_resolution_latency": latency},
            )

        executed_quantity = _executed_quantity(latest_query)
        cancel_response = None
        if status not in _CLOSED_ORDER_STATUSES:
            cancel_response = self.signed_client.cancel_order(
                symbol=intent.symbol,
                orig_client_order_id=client_order_id,
            )
            latest_query = dict(self.signed_client.query_order(symbol=intent.symbol, orig_client_order_id=client_order_id))
            executed_quantity = max(executed_quantity, _executed_quantity(latest_query))

        response = {"entry_order_final": latest_query}
        latency = _limit_resolution_latency(resolution_started_at_ms, latest_query)
        response["limit_entry_resolution_latency"] = latency
        if cancel_response is not None:
            response["entry_order_cancel"] = cancel_response
        if executed_quantity > 0:
            return LimitEntryResolution(
                status="entry_order_partial_filled_protected",
                submitted=True,
                intent=_intent_with_latency(
                    _intent_with_fill(intent, latest_query),
                    None,
                    limit_entry_resolution=latency,
                ),
                response=response,
            )
        return LimitEntryResolution(
            status="entry_order_expired_canceled",
            submitted=False,
            intent=intent,
            response=response,
        )

    def _cancel_unknown_limit_entry(
        self,
        intent: OrderIntent,
        *,
        client_order_id: str,
        error: BinanceSignedError,
    ) -> LimitEntryResolution:
        assert self.signed_client is not None
        response: dict[str, Any] = {
            "entry_order_query_error": _signed_error_payload(error),
            "entry_order_final": {"status": "UNKNOWN"},
            "limit_entry_unknown_resolution": "cancel_attempted_after_query_not_found",
        }
        status = "entry_order_unknown_canceled"
        try:
            response["entry_order_cancel"] = self.signed_client.cancel_order(
                symbol=intent.symbol,
                orig_client_order_id=client_order_id,
            )
        except BinanceSignedError as exc:
            response["entry_order_cancel_error"] = _signed_error_payload(exc)
            response["limit_entry_unknown_resolution"] = "cancel_failed_after_query_not_found"
            status = "entry_order_unknown_cancel_failed"
        return LimitEntryResolution(
            status=status,
            submitted=False,
            intent=intent,
            response=response,
        )

    def _reconcile_unknown_limit_entry_from_position(
        self,
        intent: OrderIntent,
    ) -> tuple[OrderIntent | None, dict]:
        assert self.signed_client is not None
        position_side = _position_side(intent, self.config)
        try:
            positions = self.signed_client.position_risk(intent.symbol)
        except BinanceSignedError as exc:
            return None, {
                "status": "position_check_failed",
                "endpoint": exc.endpoint,
                "code": exc.binance_code,
                "message": exc.binance_message,
            }
        intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
        for position in positions:
            if str(position.get("symbol", "")).upper() != intent.symbol.upper():
                continue
            side = str(position.get("positionSide") or "").upper()
            if position_side and side and side != position_side:
                continue
            amount = _float(position.get("positionAmt")) or 0.0
            if amount == 0:
                continue
            actual_direction = "LONG" if amount > 0 else "SHORT"
            if actual_direction != intended_direction:
                continue
            quantity = abs(amount)
            entry_price = _float(position.get("entryPrice")) or intent.entry_price
            return (
                replace(
                    intent,
                    quantity=quantity,
                    notional_usdt=quantity * entry_price,
                    entry_price=entry_price,
                    reason_codes=[*intent.reason_codes, "limit_entry_reconciled_from_position"],
                ),
                {
                    "status": "position_found",
                    "symbol": intent.symbol,
                    "position_side": side or position_side,
                    "position_amt": amount,
                    "quantity": quantity,
                    "entry_price": entry_price,
                },
            )
        return None, {"status": "no_matching_position"}


def _intent_with_latency(
    intent: OrderIntent,
    telemetry: Mapping[str, Any] | None,
    **updates: Any,
) -> OrderIntent:
    metadata = dict(intent.metadata)
    latency = dict(metadata.get("latency") if isinstance(metadata.get("latency"), dict) else {})
    if telemetry:
        latency.update(dict(telemetry))
    for key, value in updates.items():
        if value is not None:
            latency[key] = value
    start = _int_or_none(latency.get("entry_submit_started_at_ms"))
    end = _int_or_none(latency.get("entry_submit_finished_at_ms"))
    if start is not None and end is not None:
        latency["entry_submit_duration_ms"] = max(end - start, 0)
    signal = _int_or_none(latency.get("signal_time_ms"))
    if signal is not None and end is not None:
        latency["signal_to_entry_submit_finished_ms"] = max(end - signal, 0)
    metadata["latency"] = latency
    return replace(intent, metadata=metadata)


def _submit_latency(attempts: list[dict]) -> dict[str, Any]:
    started_values = [_int_or_none(item.get("started_at_ms")) for item in attempts]
    finished_values = [_int_or_none(item.get("finished_at_ms")) for item in attempts]
    started = min(value for value in started_values if value is not None) if any(value is not None for value in started_values) else None
    finished = max(value for value in finished_values if value is not None) if any(value is not None for value in finished_values) else None
    return {
        "attempt_count": len(attempts),
        "entry_submit_started_at_ms": started,
        "entry_submit_finished_at_ms": finished,
        "entry_submit_duration_ms": max(finished - started, 0) if started is not None and finished is not None else None,
        "attempts": [dict(item) for item in attempts],
    }


def _limit_resolution_latency(started_at_ms: int, query: Mapping[str, Any]) -> dict[str, Any]:
    finished_at_ms = _epoch_ms()
    exchange_update_time = _int_or_none(query.get("updateTime"))
    return {
        "started_at_ms": started_at_ms,
        "finished_at_ms": finished_at_ms,
        "duration_ms": max(finished_at_ms - started_at_ms, 0),
        "exchange_update_time_ms": exchange_update_time,
        "local_finished_minus_exchange_update_ms": (
            finished_at_ms - exchange_update_time if exchange_update_time is not None else None
        ),
        "final_status": _order_status(query),
        "executed_quantity": _executed_quantity(query),
    }


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _client_order_id(intent: OrderIntent, *, suffix: str | None = None) -> str:
    cleaned_time = "".join(ch for ch in intent.decided_at if ch.isdigit())
    base = f"bfa-{intent.symbol.lower()}-{cleaned_time}"
    if suffix:
        suffix_text = f"-{suffix}"
        return f"{base[: 36 - len(suffix_text)]}{suffix_text}"
    return base[:36]


_TERMINAL_ORDER_STATUSES = {
    "FILLED",
    "CANCELED",
    "REJECTED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
}

_CLOSED_ORDER_STATUSES = {
    "CANCELED",
    "REJECTED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
}


def _is_limit_order(intent: OrderIntent) -> bool:
    return intent.order_type.upper() == "LIMIT"


def _entry_order_price(intent: OrderIntent) -> float | None:
    return intent.entry_price if _is_limit_order(intent) else None


def _entry_time_in_force(intent: OrderIntent) -> str | None:
    if not _is_limit_order(intent):
        return None
    return (intent.time_in_force or "GTX").upper()


def _post_only_reprice_enabled(config: AppConfig, intent: OrderIntent) -> bool:
    if not _is_limit_order(intent) or _entry_time_in_force(intent) != "GTX":
        return False
    return config.get("BFA_POST_ONLY_REPRICE_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _post_only_reprice_ticks(config: AppConfig) -> int:
    try:
        parsed = int(float(config.get("BFA_POST_ONLY_REPRICE_TICKS", "2")))
    except (TypeError, ValueError):
        parsed = 2
    return max(1, min(parsed, 20))


def _post_only_reprice_max_attempts(
    config: AppConfig,
    intent: OrderIntent,
    filters: SymbolExecutionFilters | None,
) -> int:
    if not _post_only_reprice_enabled(config, intent) or filters is None or filters.tick_size is None:
        return 1
    try:
        parsed = int(float(config.get("BFA_POST_ONLY_REPRICE_MAX_ATTEMPTS", "3")))
    except (TypeError, ValueError):
        parsed = 3
    return max(1, min(parsed, 6))


def _is_post_only_repriceable_error(exc: BinanceSignedError) -> bool:
    message = (exc.binance_message or "").lower()
    return exc.binance_code == -5022 or "post only" in message or "gtx" in message


def _repriced_post_only_intent(
    intent: OrderIntent,
    *,
    filters: SymbolExecutionFilters | None,
    attempt_index: int,
    ticks_per_attempt: int,
) -> OrderIntent:
    if filters is None or filters.tick_size is None:
        return intent
    tick_size = filters.tick_size
    ticks = max(attempt_index, 1) * max(ticks_per_attempt, 1)
    price = Decimal(str(intent.entry_price))
    offset = tick_size * Decimal(ticks)
    if intent.side.upper() == "BUY":
        adjusted = _round_decimal(price - offset, tick_size, up=False)
    else:
        adjusted = _round_decimal(price + offset, tick_size, up=True)
    if adjusted <= 0:
        return intent
    stop_price = intent.stop_price
    target_price = intent.target_price
    reason_codes = list(intent.reason_codes)
    metadata = dict(intent.metadata)
    if _is_micro_grid_intent(intent):
        stop_price, target_price, reanchor = _micro_grid_fill_reanchored_protective_prices(intent, float(adjusted))
        if reanchor:
            reason_codes.append("micro_grid_reprice_reanchored_protective_prices")
            metadata["micro_grid_reprice_reanchor"] = {
                **reanchor,
                "model": "micro_grid_reprice_reanchor_v1",
            }
    return replace(
        intent,
        entry_price=float(adjusted),
        notional_usdt=float(Decimal(str(intent.quantity)) * adjusted),
        stop_price=stop_price,
        target_price=target_price,
        reason_codes=reason_codes,
        metadata=metadata,
    )


def _round_decimal(value: Decimal, increment: Decimal, *, up: bool) -> Decimal:
    if increment <= 0:
        return value
    rounding = ROUND_UP if up else ROUND_DOWN
    units = (value / increment).to_integral_value(rounding=rounding)
    return units * increment


def _limit_wait_seconds(intent: OrderIntent) -> float:
    try:
        parsed = float(intent.limit_wait_seconds or 45)
    except (TypeError, ValueError):
        parsed = 45.0
    return max(1.0, min(parsed, 90.0))


def _leverage_fallback_sequence(requested: int) -> list[int]:
    anchors = [requested, 25, 20, 15, 12, 10, 8, 5, 3, 2, 1]
    return sorted({max(int(value), 1) for value in anchors if int(value) <= requested}, reverse=True)


def _is_invalid_leverage_error(exc: BinanceSignedError) -> bool:
    message = (exc.binance_message or "").lower()
    return exc.binance_code == -4028 or "leverage" in message and "not valid" in message


def _effective_leverage_from_response(response: dict, *, fallback: int) -> int:
    try:
        parsed = int(float(response.get("leverage")))
    except (AttributeError, TypeError, ValueError):
        parsed = fallback
    return max(parsed, 1)


def _order_status(payload: dict) -> str:
    return str(payload.get("status") or "").upper()


def _executed_quantity(payload: dict) -> float:
    return _float(payload.get("executedQty")) or _float(payload.get("executedQuantity")) or 0.0


def _average_fill_price(payload: dict, fallback: float) -> float:
    avg_price = _float(payload.get("avgPrice"))
    if avg_price is not None and avg_price > 0:
        return avg_price
    executed = _executed_quantity(payload)
    quote = _float(payload.get("cumQuote")) or _float(payload.get("cumQuoteQty"))
    if executed > 0 and quote is not None and quote > 0:
        return quote / executed
    return fallback


def _intent_with_fill(intent: OrderIntent, payload: dict) -> OrderIntent:
    quantity = _executed_quantity(payload)
    if quantity <= 0:
        return intent
    fill_price = _average_fill_price(payload, intent.entry_price)
    stop_price = intent.stop_price
    target_price = intent.target_price
    reason_codes = list(intent.reason_codes)
    metadata = dict(intent.metadata)
    if _is_micro_grid_intent(intent):
        stop_price, target_price, reanchor = _micro_grid_fill_reanchored_protective_prices(intent, fill_price)
        if reanchor:
            reason_codes.append("micro_grid_fill_reanchored_protective_prices")
            metadata["micro_grid_fill_reanchor"] = reanchor
    return replace(
        intent,
        quantity=quantity,
        notional_usdt=quantity * fill_price,
        entry_price=fill_price,
        stop_price=stop_price,
        target_price=target_price,
        reason_codes=reason_codes,
        metadata=metadata,
    )


def _is_micro_grid_intent(intent: OrderIntent) -> bool:
    metadata = intent.metadata if isinstance(intent.metadata, Mapping) else {}
    if str(metadata.get("strategy_leg") or "").strip().lower() == "micro_grid":
        return True
    return any(str(reason).strip().lower() == "strategy_leg:micro_grid" for reason in intent.reason_codes)


def _micro_grid_fill_reanchored_protective_prices(intent: OrderIntent, fill_price: float) -> tuple[float, float, dict[str, Any] | None]:
    old_entry = intent.entry_price
    if old_entry <= 0 or fill_price <= 0:
        return intent.stop_price, intent.target_price, None
    risk_fraction = abs(old_entry - intent.stop_price) / old_entry
    reward_fraction = abs(intent.target_price - old_entry) / old_entry
    if risk_fraction <= 0 or reward_fraction <= 0:
        return intent.stop_price, intent.target_price, None

    if intent.side.upper() == "BUY":
        reanchored_stop = fill_price * (1.0 - risk_fraction)
        reanchored_target = fill_price * (1.0 + reward_fraction)
        stop_price = min(intent.stop_price, reanchored_stop)
        target_price = intent.target_price if fill_price <= old_entry else max(intent.target_price, reanchored_target)
        fill_quality = "better_or_equal" if fill_price <= old_entry else "worse"
    else:
        reanchored_stop = fill_price * (1.0 + risk_fraction)
        reanchored_target = fill_price * (1.0 - reward_fraction)
        stop_price = max(intent.stop_price, reanchored_stop)
        target_price = intent.target_price if fill_price >= old_entry else min(intent.target_price, reanchored_target)
        fill_quality = "better_or_equal" if fill_price >= old_entry else "worse"
    return stop_price, target_price, {
        "model": "micro_grid_fill_reanchor_v1",
        "fill_quality": fill_quality,
        "original_entry_price": old_entry,
        "fill_price": fill_price,
        "original_stop_price": intent.stop_price,
        "original_target_price": intent.target_price,
        "reanchored_stop_price": stop_price,
        "reanchored_target_price": target_price,
        "risk_fraction": risk_fraction,
        "reward_fraction": reward_fraction,
    }


def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def _protective_orders_required(config: AppConfig) -> bool:
    return config.get("BFA_REQUIRE_PROTECTIVE_ORDERS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_existing_close_position_algo_error(exc: BinanceSignedError) -> bool:
    message = exc.binance_message.lower()
    return exc.binance_code == -4130 and "closeposition" in message and "existing" in message


def _is_stale_unknown_order_error(exc: BinanceSignedError) -> bool:
    message = (exc.binance_message or "").lower()
    return exc.binance_code == -2011 and (
        "unknown order" in message
        or "does not exist" in message
        or "not found" in message
    )


def _signed_error_payload(exc: BinanceSignedError) -> dict[str, Any]:
    return {
        "endpoint": exc.endpoint,
        "code": exc.binance_code,
        "message": exc.binance_message,
    }


def _matching_close_position_algo_order(
    order: dict[str, Any],
    *,
    symbol: str,
    side: str,
    position_side: str | None,
) -> bool:
    if str(order.get("symbol") or "").upper() != symbol.upper():
        return False
    if str(order.get("side") or "").upper() != side.upper():
        return False
    if position_side and str(order.get("positionSide") or "").upper() != position_side.upper():
        return False
    order_type = str(order.get("orderType") or order.get("type") or "").upper()
    if order_type not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
        return False
    raw_close_position = order.get("closePosition")
    if isinstance(raw_close_position, bool):
        return raw_close_position
    return str(raw_close_position).strip().lower() in {"1", "true", "yes", "on"}


def _protective_order_kind(order: Mapping[str, Any]) -> str | None:
    order_type = str(order.get("orderType") or order.get("type") or "").upper()
    if order_type == "STOP_MARKET" or order_type.startswith("STOP"):
        return "STOP"
    if order_type == "TAKE_PROFIT_MARKET" or order_type.startswith("TAKE_PROFIT"):
        return "TAKE_PROFIT"
    return None


def _fallback_stop_price(intent: OrderIntent, position: Mapping[str, Any]) -> float:
    entry = _float(position.get("entry_price")) or intent.entry_price
    mark = _float(position.get("mark_price")) or entry
    planned_stop = intent.stop_price
    planned_risk = abs(entry - planned_stop)
    emergency_risk = max(planned_risk * 1.35, abs(entry) * 0.006, abs(mark) * 0.004)
    if intent.side.upper() == "BUY":
        return min(planned_stop, mark - emergency_risk)
    return max(planned_stop, mark + emergency_risk)


def _fallback_target_price(intent: OrderIntent, position: Mapping[str, Any]) -> float:
    entry = _float(position.get("entry_price")) or intent.entry_price
    mark = _float(position.get("mark_price")) or entry
    planned_target = intent.target_price
    planned_reward = abs(planned_target - entry)
    fallback_reward = max(planned_reward * 0.75, abs(entry) * 0.006, abs(mark) * 0.004)
    if intent.side.upper() == "BUY":
        return max(planned_target, mark + fallback_reward)
    return min(planned_target, mark - fallback_reward)


def _status_for_protective_resolution(resolution_status: str, *, current_status: str) -> str:
    if resolution_status == "no_matching_position":
        return "protective_order_failed_no_position"
    if resolution_status == "fallback_stop_submitted":
        return "protective_order_degraded_stop_only"
    return current_status


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


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
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
