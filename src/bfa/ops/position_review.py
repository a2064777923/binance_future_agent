"""Read-only active-position review and adjustment recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.position_hold_check import (
    PositionHoldCheckReport,
    PositionHoldItem,
    build_position_hold_check_report,
)


@dataclass(frozen=True)
class PositionReviewItem:
    symbol: str
    position_side: str | None
    position_amt: float
    recommendation: str
    urgency: str
    reasons: list[str] = field(default_factory=list)
    entry_price: float | None = None
    mark_price: float | None = None
    unrealized_pnl_usdt: float | None = None
    pnl_percent: float | None = None
    stop_r_multiple: float | None = None
    target_progress: float | None = None
    hold_elapsed_fraction: float | None = None
    elapsed_minutes: float | None = None
    hold_time_minutes: int | None = None
    algo_protection_count: int = 0
    matching_intent_event_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_side": self.position_side,
            "position_amt": self.position_amt,
            "recommendation": self.recommendation,
            "urgency": self.urgency,
            "reasons": list(self.reasons),
            "entry_price": self.entry_price,
            "mark_price": self.mark_price,
            "unrealized_pnl_usdt": self.unrealized_pnl_usdt,
            "pnl_percent": self.pnl_percent,
            "stop_r_multiple": self.stop_r_multiple,
            "target_progress": self.target_progress,
            "hold_elapsed_fraction": self.hold_elapsed_fraction,
            "elapsed_minutes": self.elapsed_minutes,
            "hold_time_minutes": self.hold_time_minutes,
            "algo_protection_count": self.algo_protection_count,
            "matching_intent_event_id": self.matching_intent_event_id,
        }


@dataclass(frozen=True)
class PositionReviewReport:
    status: str
    action_required: bool
    reasons: list[str] = field(default_factory=list)
    checked_at: str | None = None
    review_interval_minutes: int = 15
    hold_check: PositionHoldCheckReport | None = None
    positions: list[PositionReviewItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action_required": self.action_required,
            "reasons": list(self.reasons),
            "checked_at": self.checked_at,
            "review_interval_minutes": self.review_interval_minutes,
            "hold_check": self.hold_check.to_dict() if self.hold_check else None,
            "positions": [item.to_dict() for item in self.positions],
        }


def build_position_review_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    now: str | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
) -> PositionReviewReport:
    hold_check = build_position_hold_check_report(
        config,
        db_path=db_path,
        check_binance=check_binance,
        now=now,
        signed_client=signed_client,
    )
    return position_review_from_hold_check(
        hold_check,
        review_interval_minutes=_int_or_default(config.get("BFA_POSITION_REVIEW_INTERVAL_MINUTES"), 15),
    )


def position_review_from_hold_check(
    hold_check: PositionHoldCheckReport,
    *,
    review_interval_minutes: int = 15,
) -> PositionReviewReport:
    items = [_review_item(position) for position in hold_check.positions]
    reasons = _dedupe([reason for item in items for reason in item.reasons])
    if hold_check.status == "keep_current_profile":
        reasons.append("exchange_evidence_missing")
    if hold_check.openai_backoff_active:
        reasons.append("ai_backoff_active")
    if not items and not reasons:
        reasons.append("no_active_position")

    action_required = hold_check.action_required or any(item.urgency in {"high", "urgent"} for item in items)
    if any(item.urgency == "urgent" for item in items):
        status = "urgent_attention"
    elif any(item.urgency == "high" for item in items):
        status = "review_required"
    elif items:
        status = "review_ok"
    else:
        status = "no_active_position"

    return PositionReviewReport(
        status=status,
        action_required=action_required,
        reasons=_dedupe(reasons),
        checked_at=hold_check.checked_at,
        review_interval_minutes=review_interval_minutes,
        hold_check=hold_check,
        positions=items,
    )


def _review_item(position: PositionHoldItem) -> PositionReviewItem:
    metrics = _metrics(position)
    reasons = list(position.reasons)
    recommendation = "hold"
    urgency = "normal"

    if position.algo_protection_count <= 0:
        recommendation = "close_review"
        urgency = "urgent"
        reasons.append("unprotected_position")
    elif position.matching_intent is None:
        recommendation = "close_review"
        urgency = "high"
        reasons.append("missing_trade_plan")
    elif position.overdue:
        recommendation = "close_review"
        urgency = "high"
        reasons.append("hold_time_expired")
    elif metrics["stop_r_multiple"] is not None and metrics["stop_r_multiple"] <= -0.75:
        recommendation = "close_review"
        urgency = "high"
        reasons.append("loss_near_stop_risk")
    elif metrics["target_progress"] is not None and metrics["target_progress"] >= 0.8:
        recommendation = "trail_or_reduce"
        urgency = "normal"
        reasons.append("near_target")
    elif metrics["stop_r_multiple"] is not None and metrics["stop_r_multiple"] >= 1.0:
        recommendation = "trail_or_reduce"
        urgency = "normal"
        reasons.append("profit_above_one_r")
    elif metrics["hold_elapsed_fraction"] is not None and metrics["hold_elapsed_fraction"] >= 0.75:
        recommendation = "watch"
        urgency = "normal"
        reasons.append("late_hold_window")
    else:
        reasons.append("position_review_ok")

    return PositionReviewItem(
        symbol=position.symbol,
        position_side=position.position_side,
        position_amt=position.position_amt,
        recommendation=recommendation,
        urgency=urgency,
        reasons=_dedupe(reasons),
        entry_price=position.entry_price,
        mark_price=position.mark_price,
        unrealized_pnl_usdt=position.unrealized_pnl_usdt,
        pnl_percent=metrics["pnl_percent"],
        stop_r_multiple=metrics["stop_r_multiple"],
        target_progress=metrics["target_progress"],
        hold_elapsed_fraction=metrics["hold_elapsed_fraction"],
        elapsed_minutes=position.elapsed_minutes,
        hold_time_minutes=position.matching_intent.hold_time_minutes if position.matching_intent else None,
        algo_protection_count=position.algo_protection_count,
        matching_intent_event_id=position.matching_intent.event_id if position.matching_intent else None,
    )


def _metrics(position: PositionHoldItem) -> dict[str, float | None]:
    entry = position.entry_price
    mark = position.mark_price
    intent = position.matching_intent
    side = (position.position_side or "").upper()
    pnl_percent = None
    stop_r_multiple = None
    target_progress = None
    hold_elapsed_fraction = None

    if entry and mark:
        signed_move = (mark - entry) / entry
        if side == "SHORT":
            signed_move *= -1
        pnl_percent = round(signed_move * 100.0, 4)

    if intent and entry and mark:
        stop_price = _float_or_none(getattr(intent, "stop_price", None))
        target_price = _float_or_none(getattr(intent, "target_price", None))
        if stop_price and stop_price != entry:
            stop_distance = abs(entry - stop_price)
            signed_move_price = mark - entry if side != "SHORT" else entry - mark
            stop_r_multiple = round(signed_move_price / stop_distance, 4)
        if target_price and target_price != entry:
            target_distance = abs(target_price - entry)
            signed_move_price = mark - entry if side != "SHORT" else entry - mark
            target_progress = round(signed_move_price / target_distance, 4)

    if intent and intent.hold_time_minutes and position.elapsed_minutes is not None:
        hold_elapsed_fraction = round(position.elapsed_minutes / intent.hold_time_minutes, 4)

    return {
        "pnl_percent": pnl_percent,
        "stop_r_multiple": stop_r_multiple,
        "target_progress": target_progress,
        "hold_elapsed_fraction": hold_elapsed_fraction,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
