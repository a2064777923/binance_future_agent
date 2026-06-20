"""Read-only exposure clearance packet before live resume."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.exposure_status import build_exposure_status_report
from bfa.ops.live_status import build_live_status_report


BLOCKING_CLASSIFICATIONS = {"manual", "unknown", "stale_attributed"}


@dataclass(frozen=True)
class ExposureClearanceReport:
    status: str
    clearance_allowed: bool
    reasons: list[str]
    positions: list[dict[str, Any]] = field(default_factory=list)
    open_orders: list[dict[str, Any]] = field(default_factory=list)
    open_algo_orders: list[dict[str, Any]] = field(default_factory=list)
    local_intents: list[dict[str, Any]] = field(default_factory=list)
    exchange_summary: dict[str, Any] = field(default_factory=dict)
    read_only: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_exposure_clearance_v1",
            "status": self.status,
            "clearance_allowed": self.clearance_allowed,
            "reasons": list(self.reasons),
            "positions": [dict(item) for item in self.positions],
            "open_orders": [dict(item) for item in self.open_orders],
            "open_algo_orders": [dict(item) for item in self.open_algo_orders],
            "local_intents": [dict(item) for item in self.local_intents],
            "exchange_summary": dict(self.exchange_summary),
            "read_only": dict(self.read_only),
        }


def build_exposure_clearance_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    signed_client: BinanceFuturesSignedClient | None = None,
    manual_exposure_symbols: Sequence[str] | None = None,
    target_profile: str | None = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
) -> ExposureClearanceReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    manual_symbols = _normalize_symbols(manual_exposure_symbols)
    live_status = build_live_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client,
    )
    exposure_status = build_exposure_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client if check_binance else None,
        target_profile=target_profile,
        allow_two_positions=allow_two_positions,
    )
    exposure_payload = exposure_status.to_dict()
    live_payload = live_status.to_dict()
    exchange = _mapping(live_payload.get("exchange_evidence"))
    active_positions = [_mapping(item) for item in _list(exchange.get("positions"))]
    open_orders = [_order_blocker(item, orphan=False) for item in _list(exchange.get("open_orders"))]
    local_intents = [
        _mapping(item)
        for item in _list(_mapping(exposure_payload.get("risk_change")).get("unreconciled_submitted_intents"))
    ]
    open_algo_orders = _algo_order_items(
        _list(exchange.get("open_algo_orders")),
        active_symbols={str(item.get("symbol") or "").upper() for item in active_positions},
    )
    positions = [
        _position_item(position, manual_symbols=manual_symbols, local_intents=local_intents, algo_orders=open_algo_orders)
        for position in active_positions
    ]
    reasons = _reasons(positions=positions, open_orders=open_orders, open_algo_orders=open_algo_orders, exchange=exchange)
    return ExposureClearanceReport(
        status=_status(reasons),
        clearance_allowed=not reasons,
        reasons=reasons or ["exposure_clear"],
        positions=positions,
        open_orders=open_orders,
        open_algo_orders=open_algo_orders,
        local_intents=local_intents,
        exchange_summary=_mapping(exposure_payload.get("exchange_summary")),
        read_only={
            "places_orders": False,
            "cancels_orders": False,
            "applies_risk_profiles": False,
            "writes_env_files": False,
            "changes_systemd_state": False,
            "mutates_exchange_state": False,
            "creates_order_intents": False,
            "restores_live_timer": False,
        },
    )


def exposure_clearance_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    positions = [_mapping(item) for item in _list(payload.get("positions"))]
    open_orders = [_mapping(item) for item in _list(payload.get("open_orders"))]
    open_algo_orders = [_mapping(item) for item in _list(payload.get("open_algo_orders"))]
    blockers = [
        item
        for item in positions
        if str(item.get("classification") or "") in BLOCKING_CLASSIFICATIONS
    ]
    blockers.extend(item for item in open_orders if bool(item.get("blocks_live_resume")))
    blockers.extend(item for item in open_algo_orders if bool(item.get("orphan")))
    return {
        "status": str(payload.get("status") or "unknown"),
        "clearance_allowed": bool(payload.get("clearance_allowed")) and not blockers,
        "blocking_classifications": _dedupe(
            [str(item.get("classification") or item.get("classification_reason") or "unknown") for item in blockers]
        ),
        "blocking_symbols": _dedupe([str(item.get("symbol") or "").upper() for item in blockers if item.get("symbol")]),
        "blocking_count": len(blockers),
    }


def _position_item(
    position: Mapping[str, Any],
    *,
    manual_symbols: list[str],
    local_intents: list[Mapping[str, Any]],
    algo_orders: list[Mapping[str, Any]],
) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "").upper()
    direction = _position_direction(position)
    quantity = abs(_float_or_zero(position.get("positionAmt")))
    matching_intents = [item for item in local_intents if str(item.get("symbol") or "").upper() == symbol]
    exact_intents = [item for item in matching_intents if _intent_matches_position(item, direction=direction, quantity=quantity)]
    if symbol in manual_symbols:
        classification = "manual"
        reason = "operator_marked_manual"
        next_action = "close_or_keep_manual_outside_bot_then_rerun_clearance"
    elif exact_intents:
        classification = "agent_managed"
        reason = "active_position_matches_unreconciled_submitted_intent"
        next_action = "manage_with_position_review_or_wait_for_reconciliation"
    elif matching_intents:
        classification = "stale_attributed"
        reason = "symbol_matches_local_intent_but_side_or_quantity_differs"
        next_action = "reconcile_or_classify_stale_attribution_before_resume"
    else:
        classification = "unknown"
        reason = "active_exchange_position_has_no_matching_local_submitted_intent"
        next_action = "inspect_exchange_position_and_local_history_before_resume"

    protection_count = _matching_algo_count(algo_orders, symbol=symbol, direction=direction)
    return {
        "symbol": symbol,
        "direction": direction,
        "position_amt": _float_or_none(position.get("positionAmt")),
        "entry_price": _float_or_none(position.get("entryPrice")),
        "mark_price": _float_or_none(position.get("markPrice")),
        "notional_usdt": _position_notional(position),
        "initial_margin_usdt": _float_or_none(position.get("initialMargin")),
        "leverage": _float_or_none(position.get("leverage")),
        "unrealized_pnl_usdt": _float_or_none(position.get("unRealizedProfit")),
        "classification": classification,
        "classification_reason": reason,
        "matching_intent_event_ids": [item.get("event_id") for item in matching_intents if item.get("event_id")],
        "protection_count": protection_count,
        "protected": protection_count >= 2,
        "blocks_live_resume": classification in BLOCKING_CLASSIFICATIONS,
        "suggested_next_action": next_action,
    }


def _order_blocker(order: Any, *, orphan: bool) -> dict[str, Any]:
    data = _mapping(order)
    return {
        "symbol": str(data.get("symbol") or "").upper(),
        "order_id": data.get("orderId") or data.get("order_id"),
        "client_order_id": data.get("clientOrderId") or data.get("client_order_id"),
        "side": data.get("side"),
        "position_side": data.get("positionSide"),
        "type": data.get("type") or data.get("origType"),
        "status": data.get("status"),
        "orphan": orphan,
        "blocks_live_resume": True,
        "classification_reason": "normal_open_order_present",
        "suggested_next_action": "cancel_or_classify_open_order_outside_this_command_then_rerun_clearance",
    }


def _algo_order_items(orders: list[Any], *, active_symbols: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for order in orders:
        data = _mapping(order)
        symbol = str(data.get("symbol") or "").upper()
        orphan = symbol not in active_symbols
        items.append(
            {
                "symbol": symbol,
                "algo_id": data.get("algoId") or data.get("algo_id"),
                "client_algo_id": data.get("clientAlgoId") or data.get("client_algo_id"),
                "side": data.get("side"),
                "position_side": data.get("positionSide"),
                "type": data.get("type") or data.get("origType"),
                "status": data.get("status"),
                "orphan": orphan,
                "blocks_live_resume": orphan,
                "classification_reason": "orphan_algo_order_present" if orphan else "position_protection_order",
                "suggested_next_action": "cancel_or_classify_orphan_algo_order_outside_this_command_then_rerun_clearance"
                if orphan
                else "keep_as_position_protection",
            }
        )
    return items


def _reasons(
    *,
    positions: list[Mapping[str, Any]],
    open_orders: list[Mapping[str, Any]],
    open_algo_orders: list[Mapping[str, Any]],
    exchange: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not exchange:
        reasons.append("exchange_evidence_missing")
    if any(item.get("classification") == "manual" for item in positions):
        reasons.append("manual_exchange_exposure_present")
    if any(item.get("classification") == "unknown" for item in positions):
        reasons.append("unknown_exchange_exposure_present")
    if any(item.get("classification") == "stale_attributed" for item in positions):
        reasons.append("stale_attributed_exchange_exposure_present")
    if open_orders:
        reasons.append("normal_open_orders_present")
    if any(bool(item.get("orphan")) for item in open_algo_orders):
        reasons.append("orphan_algo_orders_present")
    return _dedupe(reasons)


def _status(reasons: list[str]) -> str:
    if "exchange_evidence_missing" in reasons:
        return "exchange_evidence_missing"
    if reasons:
        return "resolve_exposure"
    return "clear"


def _intent_matches_position(intent: Mapping[str, Any], *, direction: str, quantity: float) -> bool:
    intent_side = str(intent.get("side") or "").upper()
    expected_side = "BUY" if direction == "LONG" else "SELL"
    intent_quantity = _float_or_none(intent.get("quantity"))
    side_matches = not intent_side or intent_side == expected_side
    quantity_matches = intent_quantity is None or abs(abs(intent_quantity) - quantity) <= 1e-8
    return side_matches and quantity_matches


def _matching_algo_count(orders: list[Mapping[str, Any]], *, symbol: str, direction: str) -> int:
    count = 0
    for order in orders:
        if str(order.get("symbol") or "").upper() != symbol:
            continue
        position_side = str(order.get("position_side") or "").upper()
        if position_side in {"", direction}:
            count += 1
    return count


def _position_direction(position: Mapping[str, Any]) -> str:
    position_side = str(position.get("positionSide") or "").upper()
    if position_side in {"LONG", "SHORT"}:
        return position_side
    return "LONG" if _float_or_zero(position.get("positionAmt")) > 0 else "SHORT"


def _position_notional(position: Mapping[str, Any]) -> float:
    notional = _float_or_none(position.get("notional"))
    if notional is not None:
        return abs(notional)
    amount = abs(_float_or_zero(position.get("positionAmt")))
    mark = _float_or_none(position.get("markPrice")) or _float_or_none(position.get("entryPrice")) or 0.0
    return round(amount * mark, 8)


def _normalize_symbols(symbols: Sequence[str] | None) -> list[str]:
    return _dedupe([str(item).strip().upper() for item in symbols or [] if str(item).strip()])


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    return _float_or_none(value) or 0.0


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
