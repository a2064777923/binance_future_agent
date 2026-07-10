"""Active watchdog for pending limit entries left from previous live cycles."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
import sqlite3
from typing import Any, Mapping, Protocol

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceSignedError
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import (
    load_pending_limit_entry_rows,
    order_intent_from_mapping,
    persist_exchange_response,
    persist_order_intent,
    resolve_pending_limit_entry,
)


class PendingLimitWatchdogClient(Protocol):
    def query_order(
        self,
        *,
        symbol: str,
        order_id: int | str | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        ...

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: int | str | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        ...

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...

    def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...

    def new_algo_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        stop_price: float,
        close_position: bool = True,
        quantity: float | None = None,
        position_side: str | None = None,
        client_algo_id: str | None = None,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class PendingLimitOrderIntent:
    event_id: int
    occurred_at: str
    status: str
    intent: OrderIntent
    client_order_id: str
    expires_at: str
    strategy_leg: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "status": self.status,
            "client_order_id": self.client_order_id,
            "expires_at": self.expires_at,
            "strategy_leg": self.strategy_leg,
            "intent": self.intent.to_dict(),
        }


@dataclass(frozen=True)
class PendingLimitWatchdogItem:
    intent_event_id: int
    symbol: str
    status: str
    action: str
    reasons: list[str] = field(default_factory=list)
    client_order_id: str | None = None
    query_status: str | None = None
    position_side: str | None = None
    exchange_response_event_id: int | None = None
    order_intent_event_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_event_id": self.intent_event_id,
            "symbol": self.symbol,
            "status": self.status,
            "action": self.action,
            "reasons": list(self.reasons),
            "client_order_id": self.client_order_id,
            "query_status": self.query_status,
            "position_side": self.position_side,
            "exchange_response_event_id": self.exchange_response_event_id,
            "order_intent_event_id": self.order_intent_event_id,
        }


@dataclass(frozen=True)
class PendingLimitWatchdogReport:
    checked_at: str
    status: str = "pending_limit_watchdog_checked"
    execution_enabled: bool = True
    reasons: list[str] = field(default_factory=list)
    pending_count: int = 0
    checked_count: int = 0
    protected_count: int = 0
    items: list[PendingLimitWatchdogItem] = field(default_factory=list)

    @property
    def action_taken(self) -> bool:
        return any(item.action in {"place_protective_orders", "mark_resolved", "cancel_order"} for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_pending_limit_watchdog_v1",
            "checked_at": self.checked_at,
            "status": self.status,
            "execution_enabled": self.execution_enabled,
            "reasons": list(self.reasons),
            "pending_count": self.pending_count,
            "checked_count": self.checked_count,
            "protected_count": self.protected_count,
            "action_taken": self.action_taken,
            "items": [item.to_dict() for item in self.items],
        }


def build_pending_limit_watchdog_report(
    config: AppConfig,
    *,
    db_path: str | None,
    signed_client: PendingLimitWatchdogClient | None,
    checked_at: str | None = None,
    max_items: int | None = None,
    execute: bool = False,
) -> PendingLimitWatchdogReport:
    checked = checked_at or _now_iso()
    if config.get("BFA_MODE") not in {"live", "testnet"}:
        return PendingLimitWatchdogReport(
            checked_at=checked,
            status="pending_limit_watchdog_blocked",
            execution_enabled=False,
            reasons=["live_or_testnet_mode_required"],
        )
    if not _truthy(config.get("BFA_PENDING_LIMIT_WATCHDOG_ENABLED", "true")):
        return PendingLimitWatchdogReport(
            checked_at=checked,
            status="pending_limit_watchdog_disabled",
            execution_enabled=False,
            reasons=["pending_limit_watchdog_disabled"],
        )
    if signed_client is None:
        return PendingLimitWatchdogReport(
            checked_at=checked,
            status="pending_limit_watchdog_blocked",
            execution_enabled=False,
            reasons=["signed_client_unavailable"],
        )

    execution_enabled = execute and _truthy(config.get("BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED", "false"))
    reasons = []
    if execute and not execution_enabled:
        reasons.append("execution_not_enabled_by_config")
    report = execute_pending_limit_watchdog(
        config,
        db_path=db_path,
        signed_client=signed_client,
        checked_at=checked,
        max_items=max_items if max_items is not None else _int_or_default(
            config.get("BFA_PENDING_LIMIT_WATCHDOG_MAX_ITEMS", "10"),
            10,
        ),
        execute_protective_orders=execution_enabled,
    )
    return PendingLimitWatchdogReport(
        checked_at=report.checked_at,
        status=report.status,
        execution_enabled=execution_enabled,
        reasons=_dedupe([*reasons, *report.reasons]),
        pending_count=report.pending_count,
        checked_count=report.checked_count,
        protected_count=report.protected_count,
        items=report.items,
    )


def execute_pending_limit_watchdog(
    config: AppConfig,
    *,
    db_path: str | None,
    signed_client: PendingLimitWatchdogClient,
    checked_at: str | None = None,
    max_items: int = 10,
    execute_protective_orders: bool = True,
    position_snapshot: list[dict[str, Any]] | None = None,
) -> PendingLimitWatchdogReport:
    """Reconcile old pending limit entries before the live cycle opens new risk."""

    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    checked = checked_at or _now_iso()
    manual_symbols = {symbol.upper() for symbol in config.get_list("BFA_MANUAL_POSITION_SYMBOLS")}
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        pending = _load_unresolved_pending_limit_intents(
            connection,
            max_items=max_items,
            excluded_symbols=manual_symbols,
        )
        items: list[PendingLimitWatchdogItem] = []
        for pending_intent in pending:
            items.append(
                _check_pending_intent(
                    config,
                    connection,
                    signed_client,
                    pending_intent,
                    checked_at=checked,
                    execute_protective_orders=execute_protective_orders,
                    position_snapshot=position_snapshot,
                )
            )
        return PendingLimitWatchdogReport(
            checked_at=checked,
            status=_report_status(items, pending_count=len(pending), execution_enabled=execute_protective_orders),
            execution_enabled=execute_protective_orders,
            reasons=[] if execute_protective_orders else ["execution_disabled_observe_only"],
            pending_count=len(pending),
            checked_count=len(items),
            protected_count=sum(
                1
                for item in items
                if item.status in {"filled_protected", "position_reconciled_protected", "partial_filled_protected"}
            ),
            items=items,
        )
    finally:
        connection.close()


def _check_pending_intent(
    config: AppConfig,
    connection: sqlite3.Connection,
    client: PendingLimitWatchdogClient,
    pending: PendingLimitOrderIntent,
    *,
    checked_at: str,
    execute_protective_orders: bool,
    position_snapshot: list[dict[str, Any]] | None,
) -> PendingLimitWatchdogItem:
    response: dict[str, Any] = {
        "response_type": "pending_limit_watchdog",
        "pending_intent_event_id": pending.event_id,
        "client_order_id": pending.client_order_id,
    }
    query_status = None
    try:
        query = dict(
            client.query_order(
                symbol=pending.intent.symbol,
                orig_client_order_id=pending.client_order_id,
            )
        )
        response["entry_order_query"] = query
        query_status = _order_status(query)
    except (AttributeError, TypeError) as exc:
        response["entry_order_query_error"] = {"message": str(exc), "kind": type(exc).__name__}
        query = None
    except BinanceSignedError as exc:
        response["entry_order_query_error"] = _signed_error_payload(exc)
        query = None

    query_status = _order_status(query) if query is not None else None
    partial_fill = query_status == "PARTIALLY_FILLED" and _executed_quantity(query or {}) > 0
    if partial_fill:
        if not execute_protective_orders:
            return PendingLimitWatchdogItem(
                intent_event_id=pending.event_id,
                symbol=pending.intent.symbol,
                status="partial_fill_cancel_pending",
                action="cancel_order_pending",
                reasons=["pending_limit_partially_filled", "execution_disabled_observe_only"],
                client_order_id=pending.client_order_id,
                query_status=query_status,
            )
        cancel_item = _cancel_pending_order(
            connection,
            client,
            pending,
            response,
            checked_at=checked_at,
            query_status=query_status,
            failure_status="partial_fill_cancel_failed",
        )
        if cancel_item is not None:
            return cancel_item

    query_active_intent = _active_intent_from_order_query(pending.intent, query) if query is not None else None
    active_intent = None
    position_payload = None
    if query_active_intent is not None:
        active_intent, position_payload = _active_intent_from_position(
            config,
            client,
            query_active_intent,
            position_snapshot=position_snapshot,
        )
        response["position_reconcile"] = position_payload
        if active_intent is None:
            return _handle_filled_without_active_position(
                connection,
                pending,
                response,
                checked_at=checked_at,
                query_status=query_status,
                execute_protective_orders=execute_protective_orders,
                position_payload=position_payload,
            )
    elif query is None:
        active_intent, position_payload = _active_intent_from_position(
            config,
            client,
            pending.intent,
            position_snapshot=position_snapshot,
        )
        response["position_reconcile"] = position_payload

    if active_intent is None:
        if query is not None and _order_status(query) in _CLOSED_ORDER_STATUSES and _executed_quantity(query) <= 0:
            if not execute_protective_orders:
                return PendingLimitWatchdogItem(
                    intent_event_id=pending.event_id,
                    symbol=pending.intent.symbol,
                    status="terminal_no_fill_pending",
                    action="watch",
                    reasons=["pending_limit_terminal_no_fill", "execution_disabled_observe_only"],
                    client_order_id=pending.client_order_id,
                    query_status=query_status,
                )
            return _persist_terminal_no_fill(connection, pending, response, checked_at=checked_at, query_status=query_status)
        if query is None:
            return PendingLimitWatchdogItem(
                intent_event_id=pending.event_id,
                symbol=pending.intent.symbol,
                status="order_query_failed",
                action="watch",
                reasons=["pending_limit_order_query_failed", "pending_limit_kept_unresolved"],
                client_order_id=pending.client_order_id,
                query_status=query_status,
            )
        if _pending_expired(pending, checked_at=checked_at):
            if not execute_protective_orders:
                return PendingLimitWatchdogItem(
                    intent_event_id=pending.event_id,
                    symbol=pending.intent.symbol,
                    status="expired_cancel_pending",
                    action="cancel_order_pending",
                    reasons=["pending_limit_ttl_expired", "execution_disabled_observe_only"],
                    client_order_id=pending.client_order_id,
                    query_status=query_status,
                )
            cancel_item = _cancel_pending_order(
                connection,
                client,
                pending,
                response,
                checked_at=checked_at,
                query_status=query_status,
                failure_status="expired_cancel_failed",
            )
            if cancel_item is not None:
                return cancel_item
            return _persist_terminal_no_fill(
                connection,
                pending,
                {**response, "watchdog_status": "expired_canceled"},
                checked_at=checked_at,
                query_status=query_status,
                item_status="expired_canceled",
                item_action="cancel_order",
                reason_code="pending_limit_ttl_expired",
            )
        return PendingLimitWatchdogItem(
            intent_event_id=pending.event_id,
            symbol=pending.intent.symbol,
            status="still_pending",
            action="watch",
            reasons=["pending_limit_not_filled"],
            client_order_id=pending.client_order_id,
            query_status=query_status,
        )

    if not execute_protective_orders:
        existing_types, _existing_orders = _existing_protective_order_types(
            client,
            symbol=active_intent.symbol,
            position_side=_position_side(active_intent, config),
        )
        protected = {"STOP", "TAKE_PROFIT"}.issubset(existing_types)
        return PendingLimitWatchdogItem(
            intent_event_id=pending.event_id,
            symbol=active_intent.symbol,
            status="filled_already_protected" if protected else "filled_unprotected",
            action="watch" if protected else "place_protective_orders_pending",
            reasons=[
                "pending_limit_filled",
                "protective_orders_already_present" if protected else "execution_disabled_observe_only",
            ],
            client_order_id=pending.client_order_id,
            query_status=query_status,
            position_side=_position_side(active_intent, config),
        )

    protective = _place_missing_protective_orders(config, client, active_intent, checked_at=checked_at)
    response.update(protective["response"])
    status = (
        "partial_filled_protected"
        if partial_fill and protective["complete"]
        else "filled_protected"
        if protective["complete"]
        else "protection_failed"
    )
    response["watchdog_status"] = status
    intent_status = (
        "entry_order_partial_filled_protected"
        if partial_fill and protective["complete"]
        else "submitted"
        if protective["complete"]
        else "protective_order_failed_open"
    )
    persisted_intent = replace(
        active_intent,
        decided_at=checked_at,
        reason_codes=_dedupe([*active_intent.reason_codes, "pending_limit_watchdog_reconciled"]),
        metadata={
            **active_intent.metadata,
            "pending_intent_event_id": pending.event_id,
            "pending_client_order_id": pending.client_order_id,
            "pending_watchdog_checked_at": checked_at,
        },
    )
    persisted = _persist_watchdog_resolution(
        connection,
        intent=persisted_intent,
        intent_status=intent_status,
        response=response,
        risk=RiskDecision(
            protective["complete"],
            ["pending_limit_watchdog_reconciled"] if protective["complete"] else ["pending_limit_watchdog_protection_failed"],
        ),
        pending_intent_event_id=pending.event_id,
        resolved_at=checked_at if protective["complete"] else None,
        resolution_status=intent_status if protective["complete"] else None,
    )
    if (
        not partial_fill
        and position_payload
        and position_payload.get("status") == "position_found"
        and protective["complete"]
    ):
        status = "position_reconciled_protected"
    return PendingLimitWatchdogItem(
        intent_event_id=pending.event_id,
        symbol=active_intent.symbol,
        status=status,
        action="place_protective_orders",
        reasons=["pending_limit_filled", *protective["reason_codes"]],
        client_order_id=pending.client_order_id,
        query_status=query_status,
        position_side=_position_side(active_intent, config),
        exchange_response_event_id=persisted.get("exchange_response"),
        order_intent_event_id=persisted.get("order_intent"),
    )


def _persist_terminal_no_fill(
    connection: sqlite3.Connection,
    pending: PendingLimitOrderIntent,
    response: Mapping[str, Any],
    *,
    checked_at: str,
    query_status: str | None,
    item_status: str = "terminal_no_fill",
    item_action: str = "mark_resolved",
    reason_code: str = "pending_limit_terminal_no_fill",
) -> PendingLimitWatchdogItem:
    response = {**dict(response), "watchdog_status": str(response.get("watchdog_status") or "terminal_no_fill")}
    intent = replace(
        pending.intent,
        decided_at=checked_at,
        reason_codes=_dedupe([*pending.intent.reason_codes, reason_code]),
        metadata={
            **pending.intent.metadata,
            "pending_intent_event_id": pending.event_id,
            "pending_client_order_id": pending.client_order_id,
            "pending_watchdog_checked_at": checked_at,
        },
    )
    persisted = _persist_watchdog_resolution(
        connection,
        intent=intent,
        intent_status="entry_order_expired_canceled",
        response=response,
        risk=RiskDecision(True, [reason_code]),
        pending_intent_event_id=pending.event_id,
        resolved_at=checked_at,
        resolution_status="entry_order_expired_canceled",
    )
    return PendingLimitWatchdogItem(
        intent_event_id=pending.event_id,
        symbol=pending.intent.symbol,
        status=item_status,
        action=item_action,
        reasons=[reason_code],
        client_order_id=pending.client_order_id,
        query_status=query_status,
        exchange_response_event_id=persisted.get("exchange_response"),
        order_intent_event_id=persisted.get("order_intent"),
    )


def _handle_filled_without_active_position(
    connection: sqlite3.Connection,
    pending: PendingLimitOrderIntent,
    response: Mapping[str, Any],
    *,
    checked_at: str,
    query_status: str | None,
    execute_protective_orders: bool,
    position_payload: Mapping[str, Any],
) -> PendingLimitWatchdogItem:
    status = str(position_payload.get("status") or "position_check_failed")
    reasons = ["pending_limit_filled"]
    if status == "no_matching_position":
        reasons.append("no_matching_active_position")
    else:
        reasons.append("active_position_check_failed")
    if not execute_protective_orders or status != "no_matching_position":
        if not execute_protective_orders:
            reasons.append("execution_disabled_observe_only")
        return PendingLimitWatchdogItem(
            intent_event_id=pending.event_id,
            symbol=pending.intent.symbol,
            status="filled_without_active_position" if status == "no_matching_position" else "filled_position_check_failed",
            action="watch",
            reasons=reasons,
            client_order_id=pending.client_order_id,
            query_status=query_status,
        )
    response = {
        **dict(response),
        "watchdog_status": "filled_no_active_position",
    }
    intent = replace(
        pending.intent,
        decided_at=checked_at,
        reason_codes=_dedupe([*pending.intent.reason_codes, "pending_limit_filled_no_active_position"]),
        metadata={
            **pending.intent.metadata,
            "pending_intent_event_id": pending.event_id,
            "pending_client_order_id": pending.client_order_id,
            "pending_watchdog_checked_at": checked_at,
        },
    )
    persisted = _persist_watchdog_resolution(
        connection,
        intent=intent,
        intent_status="entry_order_filled_no_active_position",
        response=response,
        risk=RiskDecision(True, ["pending_limit_filled_no_active_position"]),
        pending_intent_event_id=pending.event_id,
        resolved_at=checked_at,
        resolution_status="entry_order_filled_no_active_position",
    )
    return PendingLimitWatchdogItem(
        intent_event_id=pending.event_id,
        symbol=pending.intent.symbol,
        status="filled_without_active_position",
        action="mark_resolved",
        reasons=reasons,
        client_order_id=pending.client_order_id,
        query_status=query_status,
        exchange_response_event_id=persisted.get("exchange_response"),
        order_intent_event_id=persisted.get("order_intent"),
    )


def _persist_watchdog_resolution(
    connection: sqlite3.Connection,
    *,
    intent: OrderIntent,
    intent_status: str,
    response: Mapping[str, Any],
    risk: RiskDecision,
    pending_intent_event_id: int | None = None,
    resolved_at: str | None = None,
    resolution_status: str | None = None,
) -> dict[str, int]:
    store = EventStore(connection)
    persisted = {
        "order_intent": persist_order_intent(store, intent=intent, status=intent_status, risk=risk),
    }
    persisted["exchange_response"] = persist_exchange_response(
        store,
        intent=intent,
        response=dict(response),
        response_type="pending_limit_watchdog",
    )
    if pending_intent_event_id is not None and resolved_at and resolution_status:
        resolve_pending_limit_entry(
            connection,
            intent_event_id=pending_intent_event_id,
            resolved_at=resolved_at,
            resolution_status=resolution_status,
        )
    return persisted


def _cancel_pending_order(
    connection: sqlite3.Connection,
    client: PendingLimitWatchdogClient,
    pending: PendingLimitOrderIntent,
    response: dict[str, Any],
    *,
    checked_at: str,
    query_status: str | None,
    failure_status: str,
) -> PendingLimitWatchdogItem | None:
    try:
        response["entry_order_cancel"] = dict(
            client.cancel_order(
                symbol=pending.intent.symbol,
                orig_client_order_id=pending.client_order_id,
            )
        )
        return None
    except (AttributeError, TypeError) as exc:
        response["entry_order_cancel_error"] = {"message": str(exc), "kind": type(exc).__name__}
    except BinanceSignedError as exc:
        response["entry_order_cancel_error"] = _signed_error_payload(exc)
    observed_intent = replace(pending.intent, decided_at=checked_at)
    store = EventStore(connection)
    persisted_id = persist_exchange_response(
        store,
        intent=observed_intent,
        response={**response, "watchdog_status": failure_status},
        response_type="pending_limit_watchdog",
    )
    return PendingLimitWatchdogItem(
        intent_event_id=pending.event_id,
        symbol=pending.intent.symbol,
        status=failure_status,
        action="cancel_order_failed",
        reasons=["pending_limit_cancel_failed", "pending_limit_kept_unresolved"],
        client_order_id=pending.client_order_id,
        query_status=query_status,
        exchange_response_event_id=persisted_id,
    )


def _place_missing_protective_orders(
    config: AppConfig,
    client: PendingLimitWatchdogClient,
    intent: OrderIntent,
    *,
    checked_at: str,
) -> dict[str, Any]:
    position_side = _position_side(intent, config)
    existing_types, existing_orders = _existing_protective_order_types(client, symbol=intent.symbol, position_side=position_side)
    missing = [order_type for order_type in ("STOP", "TAKE_PROFIT") if order_type not in existing_types]
    response: dict[str, Any] = {
        "existing_protective_order_types": sorted(existing_types),
        "existing_algo_orders": existing_orders,
        "missing_protective_order_types": missing,
    }
    reason_codes = []
    close_side = _opposite_side(intent.side)
    if "STOP" in missing:
        try:
            response["stop_loss_order"] = client.new_algo_order(
                symbol=intent.symbol,
                side=close_side,
                order_type="STOP_MARKET",
                stop_price=intent.stop_price,
                close_position=True,
                position_side=position_side,
                client_algo_id=_client_order_id(intent, checked_at=checked_at, suffix="wd-sl"),
            )
            reason_codes.append("stop_loss_backfilled")
        except BinanceSignedError as exc:
            response["stop_loss_error"] = _signed_error_payload(exc)
            reason_codes.append("stop_loss_backfill_failed")
    if "TAKE_PROFIT" in missing:
        try:
            response["take_profit_order"] = client.new_algo_order(
                symbol=intent.symbol,
                side=close_side,
                order_type="TAKE_PROFIT_MARKET",
                stop_price=intent.target_price,
                close_position=True,
                position_side=position_side,
                client_algo_id=_client_order_id(intent, checked_at=checked_at, suffix="wd-tp"),
            )
            reason_codes.append("take_profit_backfilled")
        except BinanceSignedError as exc:
            response["take_profit_error"] = _signed_error_payload(exc)
            reason_codes.append("take_profit_backfill_failed")
    complete = _protective_complete(response, existing_types)
    if complete and not reason_codes:
        reason_codes.append("protective_orders_already_present")
    return {"complete": complete, "response": response, "reason_codes": reason_codes}


def _protective_complete(response: Mapping[str, Any], existing_types: set[str]) -> bool:
    types = set(existing_types)
    if isinstance(response.get("stop_loss_order"), Mapping):
        types.add("STOP")
    if isinstance(response.get("take_profit_order"), Mapping):
        types.add("TAKE_PROFIT")
    return {"STOP", "TAKE_PROFIT"}.issubset(types)


def _existing_protective_order_types(
    client: PendingLimitWatchdogClient,
    *,
    symbol: str,
    position_side: str | None,
) -> tuple[set[str], list[dict[str, Any]]]:
    try:
        orders = _call_open_algo_orders(client, symbol)
    except (AttributeError, TypeError, BinanceSignedError):
        return set(), []
    matching = [
        dict(order)
        for order in orders
        if str(order.get("symbol", "")).upper() == symbol.upper()
        and (not position_side or not str(order.get("positionSide") or "").upper() or str(order.get("positionSide") or "").upper() == position_side)
    ]
    types: set[str] = set()
    for order in matching:
        order_type = str(order.get("type") or order.get("orderType") or "").upper()
        if "TAKE_PROFIT" in order_type:
            types.add("TAKE_PROFIT")
        elif "STOP" in order_type:
            types.add("STOP")
    return types, matching


def _active_intent_from_order_query(intent: OrderIntent, query: Mapping[str, Any] | None) -> OrderIntent | None:
    if query is None:
        return None
    status = _order_status(query)
    quantity = _executed_quantity(query)
    if status != "FILLED" and quantity <= 0:
        return None
    return _intent_with_fill(intent, query)


def _active_intent_from_position(
    config: AppConfig,
    client: PendingLimitWatchdogClient,
    intent: OrderIntent,
    *,
    position_snapshot: list[dict[str, Any]] | None = None,
) -> tuple[OrderIntent | None, dict[str, Any]]:
    if position_snapshot is not None:
        positions = position_snapshot
    else:
        try:
            positions = _call_position_risk(client, intent.symbol)
        except (AttributeError, TypeError) as exc:
            return None, {"status": "position_check_failed", "message": str(exc), "kind": type(exc).__name__}
        except BinanceSignedError as exc:
            return None, {"status": "position_check_failed", **_signed_error_payload(exc)}

    intended_side = _position_side(intent, config) or ("LONG" if intent.side.upper() == "BUY" else "SHORT")
    intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
    for position in positions:
        if str(position.get("symbol", "")).upper() != intent.symbol.upper():
            continue
        amount = _float(position.get("positionAmt")) or 0.0
        if amount == 0:
            continue
        position_side = str(position.get("positionSide") or "").upper()
        if position_side and position_side != "BOTH" and position_side != intended_side:
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
                reason_codes=_dedupe([*intent.reason_codes, "pending_limit_position_reconciled"]),
            ),
            {
                "status": "position_found",
                "symbol": intent.symbol,
                "position_side": position_side or intended_side,
                "position_amt": amount,
                "quantity": quantity,
                "entry_price": entry_price,
            },
        )
    return None, {"status": "no_matching_position"}


def _load_unresolved_pending_limit_intents(
    connection: sqlite3.Connection,
    *,
    max_items: int,
    excluded_symbols: set[str] | None = None,
) -> list[PendingLimitOrderIntent]:
    rows = load_pending_limit_entry_rows(
        connection,
        max_items=max_items,
        excluded_symbols=excluded_symbols,
    )
    pending: list[PendingLimitOrderIntent] = []
    for row in rows:
        event_id = int(row["intent_event_id"])
        intent = order_intent_from_mapping(json.loads(str(row["intent_json"])))
        if intent.order_type.upper() != "LIMIT":
            continue
        pending.append(
            PendingLimitOrderIntent(
                event_id=event_id,
                occurred_at=str(row["occurred_at"]),
                status=str(row["status"]),
                intent=intent,
                client_order_id=str(row["client_order_id"]),
                expires_at=str(row["expires_at"]),
                strategy_leg=str(row["strategy_leg"]) if row["strategy_leg"] is not None else None,
            )
        )
    return pending


def _has_closed_outcome_for_event(connection: sqlite3.Connection, event_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM outcomes
        WHERE ref_id = ?
        LIMIT 1
        """,
        (f"outcome:{event_id}:closed",),
    ).fetchone()
    return row is not None


def _intent_client_order_id(intent: OrderIntent) -> str:
    explicit = intent.metadata.get("client_order_id")
    if explicit:
        return str(explicit)
    cleaned_time = "".join(ch for ch in intent.decided_at if ch.isdigit())
    return f"bfa-{intent.symbol.lower()}-{cleaned_time}"[:36]


def _client_order_id(intent: OrderIntent, *, checked_at: str, suffix: str) -> str:
    seed_time = "".join(ch for ch in (checked_at or intent.decided_at) if ch.isdigit())
    base = f"bfa-{intent.symbol.lower()}-{seed_time}"
    suffix_text = f"-{suffix}"
    return f"{base[: 36 - len(suffix_text)]}{suffix_text}"


def _position_side(intent: OrderIntent, config: AppConfig) -> str | None:
    if config.get("BFA_POSITION_MODE", "one_way").strip().lower() != "hedge":
        return None
    return "LONG" if intent.side.upper() == "BUY" else "SHORT"


def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def _call_position_risk(client: PendingLimitWatchdogClient, symbol: str) -> list[dict[str, Any]]:
    try:
        return list(client.position_risk(symbol))
    except TypeError:
        return list(client.position_risk())


def _call_open_algo_orders(client: PendingLimitWatchdogClient, symbol: str) -> list[dict[str, Any]]:
    try:
        return list(client.open_algo_orders(symbol))
    except TypeError:
        return list(client.open_algo_orders())


_CLOSED_ORDER_STATUSES = {
    "CANCELED",
    "REJECTED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
}


def _order_status(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or "").upper()


def _executed_quantity(payload: Mapping[str, Any]) -> float:
    return _float(payload.get("executedQty")) or _float(payload.get("executedQuantity")) or 0.0


def _average_fill_price(payload: Mapping[str, Any], fallback: float) -> float:
    avg_price = _float(payload.get("avgPrice"))
    if avg_price is not None and avg_price > 0:
        return avg_price
    executed = _executed_quantity(payload)
    quote = _float(payload.get("cumQuote")) or _float(payload.get("cumQuoteQty"))
    if executed > 0 and quote is not None and quote > 0:
        return quote / executed
    return fallback


def _intent_with_fill(intent: OrderIntent, payload: Mapping[str, Any]) -> OrderIntent:
    quantity = _executed_quantity(payload)
    if quantity <= 0:
        return intent
    fill_price = _average_fill_price(payload, intent.entry_price)
    return replace(intent, quantity=quantity, notional_usdt=quantity * fill_price, entry_price=fill_price)


def _signed_error_payload(exc: BinanceSignedError) -> dict[str, Any]:
    return {
        "endpoint": exc.endpoint,
        "code": exc.binance_code,
        "message": exc.binance_message,
    }


def _report_status(
    items: list[PendingLimitWatchdogItem],
    *,
    pending_count: int,
    execution_enabled: bool,
) -> str:
    if pending_count <= 0:
        return "pending_limit_watchdog_empty"
    statuses = {item.status for item in items}
    if "protection_failed" in statuses:
        return "pending_limit_watchdog_protection_failed"
    if statuses.intersection({"expired_cancel_failed", "partial_fill_cancel_failed", "order_query_failed"}):
        return "pending_limit_watchdog_check_failed"
    if statuses.intersection({"filled_unprotected", "expired_cancel_pending", "partial_fill_cancel_pending"}):
        return "pending_limit_watchdog_action_ready"
    if "filled_position_check_failed" in statuses:
        return "pending_limit_watchdog_check_failed"
    if any(status in statuses for status in {"filled_protected", "position_reconciled_protected", "partial_filled_protected"}):
        return "pending_limit_watchdog_protected"
    if not execution_enabled and any(status in statuses for status in {"filled_already_protected"}):
        return "pending_limit_watchdog_observing"
    return "pending_limit_watchdog_checked"


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float(value)
    if parsed is None:
        return None
    return int(parsed)


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pending_expired(pending: PendingLimitOrderIntent, *, checked_at: str) -> bool:
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00")).astimezone(UTC)
        expires = datetime.fromisoformat(pending.expires_at.replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return True
    return checked >= expires
