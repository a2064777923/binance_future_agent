"""Read-only check for active positions that exceed AI hold-time guidance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import sqlite3
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.live_status import LiveStatusReport, build_live_status_report


@dataclass(frozen=True)
class PositionHoldIntent:
    event_id: int
    occurred_at: str
    symbol: str
    side: str
    quantity: float | None = None
    leverage: int | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    hold_time_minutes: int | None = None
    strategy_leg: str | None = None
    regime_label: str | None = None
    route_decision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "leverage": self.leverage,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "hold_time_minutes": self.hold_time_minutes,
            "strategy_leg": self.strategy_leg,
            "regime_label": self.regime_label,
            "route_decision": self.route_decision,
        }


@dataclass(frozen=True)
class PositionHoldItem:
    symbol: str
    position_side: str | None
    position_amt: float
    entry_price: float | None = None
    mark_price: float | None = None
    unrealized_pnl_usdt: float | None = None
    matching_intent: PositionHoldIntent | None = None
    elapsed_minutes: float | None = None
    overdue: bool = False
    algo_protection_count: int = 0
    algo_orders: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_side": self.position_side,
            "position_amt": self.position_amt,
            "entry_price": self.entry_price,
            "mark_price": self.mark_price,
            "unrealized_pnl_usdt": self.unrealized_pnl_usdt,
            "matching_intent": self.matching_intent.to_dict() if self.matching_intent else None,
            "elapsed_minutes": self.elapsed_minutes,
            "overdue": self.overdue,
            "algo_protection_count": self.algo_protection_count,
            "algo_orders": [dict(order) for order in self.algo_orders],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PositionHoldCheckReport:
    status: str
    action_required: bool
    reasons: list[str] = field(default_factory=list)
    checked_at: str | None = None
    position_count: int = 0
    open_order_count: int = 0
    open_algo_order_count: int = 0
    openai_backoff_active: bool = False
    positions: list[PositionHoldItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action_required": self.action_required,
            "reasons": list(self.reasons),
            "checked_at": self.checked_at,
            "position_count": self.position_count,
            "open_order_count": self.open_order_count,
            "open_algo_order_count": self.open_algo_order_count,
            "openai_backoff_active": self.openai_backoff_active,
            "positions": [item.to_dict() for item in self.positions],
        }


@dataclass(frozen=True)
class TimeExitOrderPlan:
    symbol: str
    side: str
    order_type: str
    quantity: float
    position_side: str | None = None
    reduce_only: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "position_side": self.position_side,
            "reduce_only": self.reduce_only,
        }


@dataclass(frozen=True)
class TimeExitPlanItem:
    position: PositionHoldItem
    exit_allowed: bool
    reasons: list[str] = field(default_factory=list)
    order_plan: TimeExitOrderPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.to_dict(),
            "exit_allowed": self.exit_allowed,
            "reasons": list(self.reasons),
            "order_plan": self.order_plan.to_dict() if self.order_plan else None,
        }


@dataclass(frozen=True)
class TimeExitPlanReport:
    status: str
    exit_allowed: bool
    reasons: list[str] = field(default_factory=list)
    hold_check: PositionHoldCheckReport | None = None
    plans: list[TimeExitPlanItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_allowed": self.exit_allowed,
            "reasons": list(self.reasons),
            "hold_check": self.hold_check.to_dict() if self.hold_check else None,
            "plans": [plan.to_dict() for plan in self.plans],
        }


def build_position_hold_check_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    now: str | None = None,
    live_status_report: LiveStatusReport | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
) -> PositionHoldCheckReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    checked_at = _now_iso(now)
    live_status = live_status_report or build_live_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client,
    )
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        return position_hold_check_from_live_status(
            live_status,
            connection=connection,
            checked_at=checked_at,
        )
    finally:
        connection.close()


def build_time_exit_plan_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    now: str | None = None,
    live_status_report: LiveStatusReport | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
) -> TimeExitPlanReport:
    hold_check = build_position_hold_check_report(
        config,
        db_path=db_path,
        check_binance=check_binance,
        now=now,
        live_status_report=live_status_report,
        signed_client=signed_client,
    )
    return time_exit_plan_from_hold_check(hold_check, position_mode=config.get("BFA_POSITION_MODE"))


def time_exit_plan_from_hold_check(
    hold_check: PositionHoldCheckReport,
    *,
    position_mode: str,
) -> TimeExitPlanReport:
    reasons: list[str] = []
    plans: list[TimeExitPlanItem] = []
    if hold_check.status == "keep_current_profile":
        reasons.append("exchange_evidence_missing")
    if hold_check.open_order_count:
        reasons.append("normal_open_orders_present")
    if hold_check.openai_backoff_active:
        reasons.append("ai_backoff_active")

    for position in hold_check.positions:
        item_reasons = _time_exit_item_reasons(position)
        allowed = not item_reasons
        order_plan = _time_exit_order_plan(position, position_mode=position_mode) if allowed else None
        plans.append(
            TimeExitPlanItem(
                position=position,
                exit_allowed=allowed,
                reasons=item_reasons or ["time_exit_candidate"],
                order_plan=order_plan,
            )
        )

    if not hold_check.positions:
        reasons.append("no_active_position")
    if any(not plan.exit_allowed for plan in plans):
        reasons.append("position_exit_preconditions_failed")
    if plans and all(plan.exit_allowed for plan in plans) and not reasons:
        return TimeExitPlanReport(
            status="exit_plan_ready",
            exit_allowed=True,
            reasons=["time_exit_preconditions_met"],
            hold_check=hold_check,
            plans=plans,
        )
    return TimeExitPlanReport(
        status="exit_plan_blocked",
        exit_allowed=False,
        reasons=_dedupe(reasons),
        hold_check=hold_check,
        plans=plans,
    )


def position_hold_check_from_live_status(
    report: LiveStatusReport,
    *,
    connection: sqlite3.Connection,
    checked_at: str,
) -> PositionHoldCheckReport:
    payload = report.to_dict()
    exchange = _mapping(payload.get("exchange_evidence"))
    if not exchange:
        return PositionHoldCheckReport(
            status="keep_current_profile",
            action_required=True,
            reasons=["exchange_evidence_missing"],
            checked_at=checked_at,
            openai_backoff_active=bool(_mapping(payload.get("openai_backoff")).get("active")),
        )

    positions = _list(exchange.get("positions"))
    open_orders = _list(exchange.get("open_orders"))
    open_algo_orders = _list(exchange.get("open_algo_orders"))
    backoff = _mapping(payload.get("openai_backoff"))
    backoff_active = bool(backoff.get("active"))

    items = [
        _position_item(connection, position, open_algo_orders, checked_at=checked_at)
        for position in positions
    ]

    reasons: list[str] = []
    status = "no_active_position"
    if backoff_active:
        reasons.append("ai_backoff_active")
    if not positions and (open_orders or open_algo_orders):
        reasons.append("open_orders_without_position")
        status = "urgent_attention"
    elif not positions:
        reasons.append("no_active_position_or_open_orders")
    else:
        for item in items:
            reasons.extend(item.reasons)
        if any("active_position_without_confirmed_algo_protection" in item.reasons for item in items):
            status = "urgent_attention"
        elif any(item.overdue or item.matching_intent is None for item in items):
            status = "review_required"
        else:
            status = "within_hold_window"
            if not reasons:
                reasons.append("all_positions_within_hold_time")
    action_required = status in {"urgent_attention", "review_required"} or backoff_active
    return PositionHoldCheckReport(
        status=status,
        action_required=action_required,
        reasons=_dedupe(reasons),
        checked_at=checked_at,
        position_count=len(positions),
        open_order_count=len(open_orders),
        open_algo_order_count=len(open_algo_orders),
        openai_backoff_active=backoff_active,
        positions=items,
    )


def _time_exit_item_reasons(position: PositionHoldItem) -> list[str]:
    reasons: list[str] = []
    if not position.overdue:
        reasons.append("hold_time_not_expired")
    if position.algo_protection_count < 2:
        reasons.append("active_position_without_confirmed_algo_protection")
    if position.matching_intent is None:
        reasons.append("active_position_without_matching_submitted_intent")
    if position.position_amt == 0:
        reasons.append("zero_position_amount")
    return reasons


def _time_exit_order_plan(
    position: PositionHoldItem,
    *,
    position_mode: str,
) -> TimeExitOrderPlan:
    quantity = abs(position.position_amt)
    side = "SELL" if position.position_amt > 0 else "BUY"
    hedge_mode = position_mode.strip().lower() == "hedge"
    return TimeExitOrderPlan(
        symbol=position.symbol,
        side=side,
        order_type="MARKET",
        quantity=quantity,
        position_side=position.position_side if hedge_mode else None,
        reduce_only=False if hedge_mode else True,
    )


def _position_item(
    connection: sqlite3.Connection,
    position: Mapping[str, Any],
    open_algo_orders: list[Any],
    *,
    checked_at: str,
) -> PositionHoldItem:
    symbol = str(position.get("symbol", "")).upper()
    amount = _float_or_zero(position.get("positionAmt"))
    position_side = _position_side(position, amount)
    intent = _latest_unclosed_submitted_intent(connection, symbol=symbol, position_side=position_side)
    matching_algo_orders = _matching_algo_orders(open_algo_orders, symbol=symbol, position_side=position_side)
    protection_count = _protective_order_type_count(matching_algo_orders)
    reasons: list[str] = []
    elapsed: float | None = None
    overdue = False
    if protection_count < 2:
        reasons.append("active_position_without_confirmed_algo_protection")
    if intent is None:
        reasons.append("active_position_without_matching_submitted_intent")
    elif intent.hold_time_minutes is None:
        reasons.append("hold_time_missing")
    else:
        elapsed = round((_parse_iso(checked_at) - _parse_iso(intent.occurred_at)).total_seconds() / 60.0, 2)
        if elapsed > intent.hold_time_minutes:
            overdue = True
            reasons.append("hold_time_expired")
    return PositionHoldItem(
        symbol=symbol,
        position_side=position_side,
        position_amt=amount,
        entry_price=_float_or_none(position.get("entryPrice")),
        mark_price=_float_or_none(position.get("markPrice")),
        unrealized_pnl_usdt=_float_or_none(position.get("unRealizedProfit")),
        matching_intent=intent,
        elapsed_minutes=elapsed,
        overdue=overdue,
        algo_protection_count=protection_count,
        algo_orders=matching_algo_orders,
        reasons=reasons,
    )


def _latest_unclosed_submitted_intent(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    position_side: str | None,
) -> PositionHoldIntent | None:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        WHERE symbol = ?
        ORDER BY occurred_at DESC, id DESC
        """,
        (symbol.upper(),),
    ).fetchall()
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if payload.get("status") not in _OPEN_POSITION_INTENT_STATUSES:
            continue
        event_id = int(row["event_id"])
        if _has_closed_outcome_for_event(connection, event_id):
            continue
        intent = payload.get("intent")
        intent_payload = intent if isinstance(intent, Mapping) else {}
        side = str(intent_payload.get("side", "")).upper()
        if position_side and _side_to_position_side(side) != position_side:
            continue
        metadata = intent_payload.get("metadata")
        metadata_payload = metadata if isinstance(metadata, Mapping) else {}
        reason_codes = _string_list(intent_payload.get("reason_codes"))
        return PositionHoldIntent(
            event_id=event_id,
            occurred_at=str(row["occurred_at"]),
            symbol=str(row["symbol"] or intent_payload.get("symbol", "")).upper(),
            side=side,
            quantity=_float_or_none(intent_payload.get("quantity")),
            leverage=_int_or_none(intent_payload.get("leverage")),
            entry_price=_float_or_none(intent_payload.get("entry_price")),
            stop_price=_float_or_none(intent_payload.get("stop_price")),
            target_price=_float_or_none(intent_payload.get("target_price")),
            hold_time_minutes=_int_or_none(metadata_payload.get("hold_time_minutes")),
            strategy_leg=_first_text(metadata_payload.get("strategy_leg"), _reason_value(reason_codes, "strategy_leg")),
            regime_label=_first_text(metadata_payload.get("regime_label"), _reason_value(reason_codes, "regime_label")),
            route_decision=_first_text(metadata_payload.get("route_decision"), _reason_value(reason_codes, "route_decision")),
        )
    return None


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


_OPEN_POSITION_INTENT_STATUSES = {
    "submitted",
    "entry_order_pending",
    "entry_order_partial_filled_protected",
    "protective_order_failed_open",
}


def _matching_algo_order_count(
    open_algo_orders: list[Any],
    *,
    symbol: str,
    position_side: str | None,
) -> int:
    return _protective_order_type_count(_matching_algo_orders(open_algo_orders, symbol=symbol, position_side=position_side))


def _matching_algo_orders(
    open_algo_orders: list[Any],
    *,
    symbol: str,
    position_side: str | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for order in open_algo_orders:
        if not isinstance(order, Mapping):
            continue
        if str(order.get("symbol", "")).upper() != symbol:
            continue
        order_position_side = str(order.get("positionSide") or "").upper()
        if position_side and order_position_side and order_position_side != position_side:
            continue
        matches.append(dict(order))
    return matches


def _protective_order_type_count(open_algo_orders: list[dict[str, Any]]) -> int:
    types = set()
    for order in open_algo_orders:
        order_type = str(order.get("type") or order.get("orderType") or "").upper()
        if "TAKE_PROFIT" in order_type:
            types.add("TAKE_PROFIT")
        elif "STOP" in order_type:
            types.add("STOP")
    if not types and len(open_algo_orders) >= 2:
        return 2
    return len(types)


def _position_side(position: Mapping[str, Any], amount: float) -> str | None:
    side = str(position.get("positionSide") or "").upper()
    if side and side != "BOTH":
        return side
    if amount > 0:
        return "LONG"
    if amount < 0:
        return "SHORT"
    return None


def _side_to_position_side(side: str) -> str | None:
    if side == "BUY":
        return "LONG"
    if side == "SELL":
        return "SHORT"
    return None


def _now_iso(now: str | None) -> str:
    if now:
        return _parse_iso(now).isoformat().replace("+00:00", "Z")
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _reason_value(reason_codes: list[str], prefix: str) -> str | None:
    marker = f"{prefix}:"
    for reason in reason_codes:
        if reason.startswith(marker):
            return reason.split(":", 1)[1].strip() or None
    return None


def _float_or_zero(value: Any) -> float:
    result = _float_or_none(value)
    return result if result is not None else 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
