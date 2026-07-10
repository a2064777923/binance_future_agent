"""Signal-time quality checks for capital tied up in pending limit entries."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
from typing import Any, Mapping, Protocol

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceSignedError
from bfa.execution.models import RiskDecision
from bfa.execution.store import (
    load_pending_limit_entry_rows,
    order_intent_from_mapping,
    persist_exchange_response,
    persist_order_intent,
    resolve_pending_limit_entry,
)


class PendingOrderQualityClient(Protocol):
    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: int | str | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PendingOrderQualityItem:
    intent_event_id: int
    symbol: str
    client_order_id: str
    status: str
    action: str
    reasons: list[str] = field(default_factory=list)
    entry_distance_percent: float | None = None
    micro_momentum_percent: float | None = None
    taker_buy_sell_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_event_id": self.intent_event_id,
            "symbol": self.symbol,
            "client_order_id": self.client_order_id,
            "status": self.status,
            "action": self.action,
            "reasons": list(self.reasons),
            "entry_distance_percent": self.entry_distance_percent,
            "micro_momentum_percent": self.micro_momentum_percent,
            "taker_buy_sell_ratio": self.taker_buy_sell_ratio,
        }


@dataclass(frozen=True)
class PendingOrderQualityReport:
    checked_at: str
    status: str
    execution_enabled: bool
    items: list[PendingOrderQualityItem] = field(default_factory=list)

    @property
    def canceled_client_order_ids(self) -> set[str]:
        return {item.client_order_id for item in self.items if item.status == "quality_canceled"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_pending_order_quality_v1",
            "checked_at": self.checked_at,
            "status": self.status,
            "execution_enabled": self.execution_enabled,
            "checked_count": len(self.items),
            "cancel_ready_count": sum(1 for item in self.items if item.status == "quality_cancel_ready"),
            "canceled_count": len(self.canceled_client_order_ids),
            "cancel_failed_count": sum(1 for item in self.items if item.status == "quality_cancel_failed"),
            "items": [item.to_dict() for item in self.items],
        }


def execute_pending_order_quality_check(
    config: AppConfig,
    *,
    db_path: str,
    signed_client: PendingOrderQualityClient,
    checked_at: str,
    market_context_by_symbol: Mapping[str, Mapping[str, Any]],
    open_orders: list[Mapping[str, Any]],
    signal_sides_by_symbol: Mapping[str, str] | None = None,
    execute: bool = True,
) -> PendingOrderQualityReport:
    if not _truthy(config.get("BFA_PENDING_LIMIT_QUALITY_CHECK_ENABLED", "false")):
        return PendingOrderQualityReport(
            checked_at=checked_at,
            status="quality_check_disabled",
            execution_enabled=False,
        )
    execution_enabled = execute and _truthy(
        config.get("BFA_PENDING_LIMIT_QUALITY_EXECUTE_ENABLED", "false")
    )
    max_items = _positive_int(config.get("BFA_PENDING_LIMIT_QUALITY_MAX_ITEMS", "10"), 10)
    open_by_client_id = {
        str(order.get("clientOrderId") or order.get("origClientOrderId") or ""): order
        for order in open_orders
        if str(order.get("status") or "").upper() in {"NEW", "PARTIALLY_FILLED"}
    }
    connection = connect(db_path)
    try:
        migrate(connection)
        rows = load_pending_limit_entry_rows(connection, max_items=max_items)
        items = [
            _check_item(
                config,
                connection,
                signed_client,
                row,
                checked_at=checked_at,
                context=market_context_by_symbol.get(str(row["symbol"]).upper()),
                open_order=open_by_client_id.get(str(row["client_order_id"])),
                signal_side=(signal_sides_by_symbol or {}).get(str(row["symbol"]).upper()),
                execution_enabled=execution_enabled,
            )
            for row in rows
        ]
    finally:
        connection.close()
    statuses = {item.status for item in items}
    if "quality_cancel_failed" in statuses:
        status = "quality_check_failed"
    elif "quality_canceled" in statuses:
        status = "quality_orders_canceled"
    elif "quality_cancel_ready" in statuses:
        status = "quality_action_ready"
    else:
        status = "quality_checked"
    return PendingOrderQualityReport(
        checked_at=checked_at,
        status=status,
        execution_enabled=execution_enabled,
        items=items,
    )


def _check_item(
    config: AppConfig,
    connection,
    client: PendingOrderQualityClient,
    row,
    *,
    checked_at: str,
    context: Mapping[str, Any] | None,
    open_order: Mapping[str, Any] | None,
    signal_side: str | None,
    execution_enabled: bool,
) -> PendingOrderQualityItem:
    event_id = int(row["intent_event_id"])
    symbol = str(row["symbol"]).upper()
    client_order_id = str(row["client_order_id"])
    intent = order_intent_from_mapping(json.loads(str(row["intent_json"])))
    if open_order is None:
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_evidence_missing",
            action="keep",
            reasons=["open_order_snapshot_missing"],
        )
    if str(open_order.get("status") or "").upper() == "PARTIALLY_FILLED":
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_deferred_partial_fill",
            action="keep",
            reasons=["partial_fill_requires_watchdog_reconciliation"],
        )
    if context is None or _age_seconds(row["occurred_at"], checked_at) < _positive_float(
        config.get("BFA_PENDING_LIMIT_QUALITY_MIN_AGE_SECONDS", "5"),
        5.0,
    ):
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_evidence_missing",
            action="keep",
            reasons=["market_context_missing_or_order_too_fresh"],
        )
    current_price = _positive_float(context.get("reference_price"), 0.0)
    momentum = _float_or_none(context.get("kline_micro_momentum_percent"))
    taker_ratio = _float_or_none(context.get("taker_buy_sell_ratio"))
    if current_price <= 0 or intent.entry_price <= 0:
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_evidence_missing",
            action="keep",
            reasons=["reference_or_entry_price_missing"],
        )
    distance = _entry_distance_percent(intent.side, current_price=current_price, entry_price=intent.entry_price)
    reasons = _quality_reasons(
        config,
        side=intent.side,
        current_price=current_price,
        entry_price=intent.entry_price,
        stop_price=intent.stop_price,
        distance_percent=distance,
        momentum_percent=momentum,
        taker_ratio=taker_ratio,
        signal_side=signal_side,
    )
    metrics = {
        "entry_distance_percent": round(distance, 8),
        "micro_momentum_percent": momentum,
        "taker_buy_sell_ratio": taker_ratio,
    }
    if not reasons:
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_ok",
            action="keep",
            reasons=["pending_order_quality_still_valid"],
            **metrics,
        )
    if not execution_enabled:
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_cancel_ready",
            action="cancel_pending",
            reasons=reasons,
            **metrics,
        )
    response: dict[str, Any] = {
        "response_type": "pending_order_quality",
        "pending_intent_event_id": event_id,
        "client_order_id": client_order_id,
        "quality_reasons": reasons,
        "quality_metrics": metrics,
    }
    try:
        response["entry_order_cancel"] = dict(
            client.cancel_order(symbol=symbol, orig_client_order_id=client_order_id)
        )
    except (AttributeError, TypeError) as exc:
        response["entry_order_cancel_error"] = {"kind": type(exc).__name__, "message": str(exc)}
    except BinanceSignedError as exc:
        response["entry_order_cancel_error"] = {
            "endpoint": exc.endpoint,
            "code": exc.binance_code,
            "message": exc.binance_message,
        }
    if "entry_order_cancel_error" in response:
        store = EventStore(connection)
        persist_exchange_response(
            store,
            intent=replace(intent, decided_at=checked_at),
            response={**response, "quality_status": "cancel_failed"},
            response_type="pending_order_quality",
        )
        return PendingOrderQualityItem(
            intent_event_id=event_id,
            symbol=symbol,
            client_order_id=client_order_id,
            status="quality_cancel_failed",
            action="cancel_failed",
            reasons=[*reasons, "pending_order_kept_unresolved"],
            **metrics,
        )
    resolved_intent = replace(
        intent,
        decided_at=checked_at,
        reason_codes=_dedupe([*intent.reason_codes, *reasons, "pending_order_quality_canceled"]),
        metadata={
            **intent.metadata,
            "pending_intent_event_id": event_id,
            "pending_client_order_id": client_order_id,
            "pending_quality_checked_at": checked_at,
        },
    )
    store = EventStore(connection)
    persist_order_intent(
        store,
        intent=resolved_intent,
        status="entry_order_quality_canceled",
        risk=RiskDecision(True, reasons),
    )
    persist_exchange_response(
        store,
        intent=resolved_intent,
        response={**response, "quality_status": "canceled"},
        response_type="pending_order_quality",
    )
    resolve_pending_limit_entry(
        connection,
        intent_event_id=event_id,
        resolved_at=checked_at,
        resolution_status="entry_order_quality_canceled",
    )
    return PendingOrderQualityItem(
        intent_event_id=event_id,
        symbol=symbol,
        client_order_id=client_order_id,
        status="quality_canceled",
        action="cancel_order",
        reasons=reasons,
        **metrics,
    )


def _quality_reasons(
    config: AppConfig,
    *,
    side: str,
    current_price: float,
    entry_price: float,
    stop_price: float,
    distance_percent: float,
    momentum_percent: float | None,
    taker_ratio: float | None,
    signal_side: str | None,
) -> list[str]:
    buy = side.upper() == "BUY"
    reasons: list[str] = []
    normalized_signal = str(signal_side or "").strip().lower()
    if normalized_signal in {"long", "short"} and normalized_signal != ("long" if buy else "short"):
        reasons.append("fresh_signal_opposes_pending_order")
    if stop_price > 0 and ((buy and current_price <= stop_price) or (not buy and current_price >= stop_price)):
        reasons.append("market_crossed_pending_plan_invalidation")
    momentum_threshold = _positive_float(
        config.get("BFA_PENDING_LIMIT_QUALITY_MOMENTUM_PERCENT", "0.08"),
        0.08,
    )
    max_distance = _positive_float(
        config.get("BFA_PENDING_LIMIT_QUALITY_MAX_DISTANCE_PERCENT", "0.35"),
        0.35,
    )
    moving_away = momentum_percent is not None and (
        (buy and momentum_percent >= momentum_threshold)
        or (not buy and momentum_percent <= -momentum_threshold)
    )
    if distance_percent >= max_distance and moving_away:
        reasons.append("short_term_fill_probability_deteriorated")
    sell_ratio = _positive_float(config.get("BFA_PENDING_LIMIT_QUALITY_TAKER_SELL_RATIO", "0.85"), 0.85)
    buy_ratio = _positive_float(config.get("BFA_PENDING_LIMIT_QUALITY_TAKER_BUY_RATIO", "1.18"), 1.18)
    adverse_momentum = momentum_percent is not None and (
        (buy and momentum_percent <= -momentum_threshold)
        or (not buy and momentum_percent >= momentum_threshold)
    )
    adverse_flow = taker_ratio is not None and ((buy and taker_ratio <= sell_ratio) or (not buy and taker_ratio >= buy_ratio))
    if adverse_momentum and adverse_flow:
        reasons.append("pending_order_trend_and_flow_deteriorated")
    return _dedupe(reasons)


def _entry_distance_percent(side: str, *, current_price: float, entry_price: float) -> float:
    if side.upper() == "BUY":
        distance = max(current_price - entry_price, 0.0)
    else:
        distance = max(entry_price - current_price, 0.0)
    return distance / current_price * 100.0


def _age_seconds(occurred_at: Any, checked_at: str) -> float:
    start = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00")).astimezone(UTC)
    end = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00")).astimezone(UTC)
    return max((end - start).total_seconds(), 0.0)


def _positive_float(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None and parsed > 0 else default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
