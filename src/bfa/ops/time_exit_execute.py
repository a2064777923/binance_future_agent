"""Operator-approved execution for overdue time-exit plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from typing import Any

from bfa.config import AppConfig, RuntimeMode
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError
from bfa.execution.models import OrderIntent
from bfa.execution.store import persist_exchange_response
from bfa.ops.position_hold_check import (
    TimeExitOrderPlan,
    TimeExitPlanItem,
    TimeExitPlanReport,
    build_time_exit_plan_report,
)


@dataclass(frozen=True)
class TimeExitExecution:
    symbol: str
    status: str
    confirmation_token: str
    order_plan: TimeExitOrderPlan
    close_order_response: dict[str, Any] | None = None
    post_close_position_amt: float | None = None
    cancel_algo_response: dict[str, Any] | None = None
    persisted: dict[str, int] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "confirmation_token": self.confirmation_token,
            "order_plan": self.order_plan.to_dict(),
            "close_order_response": dict(self.close_order_response) if self.close_order_response else None,
            "post_close_position_amt": self.post_close_position_amt,
            "cancel_algo_response": dict(self.cancel_algo_response) if self.cancel_algo_response else None,
            "persisted": dict(self.persisted),
            "error": dict(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class TimeExitExecuteReport:
    status: str
    exit_executed: bool
    reasons: list[str] = field(default_factory=list)
    confirmation_required: bool = False
    expected_confirmation_token: str | None = None
    time_exit_plan: TimeExitPlanReport | None = None
    execution: TimeExitExecution | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_executed": self.exit_executed,
            "reasons": list(self.reasons),
            "confirmation_required": self.confirmation_required,
            "expected_confirmation_token": self.expected_confirmation_token,
            "time_exit_plan": self.time_exit_plan.to_dict() if self.time_exit_plan else None,
            "execution": self.execution.to_dict() if self.execution else None,
        }


def build_time_exit_execute_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    confirm_token: str | None = None,
    now: str | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
    service_active: bool = False,
) -> TimeExitExecuteReport:
    if RuntimeMode(config.get("BFA_MODE")) is not RuntimeMode.LIVE:
        return TimeExitExecuteReport(
            status="execution_blocked",
            exit_executed=False,
            reasons=["live_mode_required"],
        )
    if service_active:
        return TimeExitExecuteReport(
            status="execution_blocked",
            exit_executed=False,
            reasons=["live_service_active"],
        )
    if confirm_token and now:
        return TimeExitExecuteReport(
            status="execution_blocked",
            exit_executed=False,
            reasons=["now_override_not_allowed_for_confirmed_execution"],
        )

    client = signed_client or BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    checked_at = _now_iso(now)
    plan_report = build_time_exit_plan_report(
        config,
        db_path=resolved_db_path,
        check_binance=True,
        now=checked_at,
        signed_client=client,
    )
    if not plan_report.exit_allowed:
        return TimeExitExecuteReport(
            status="execution_blocked",
            exit_executed=False,
            reasons=["time_exit_plan_not_ready", *plan_report.reasons],
            time_exit_plan=plan_report,
        )
    if len(plan_report.plans) != 1:
        return TimeExitExecuteReport(
            status="execution_blocked",
            exit_executed=False,
            reasons=["expected_exactly_one_exit_plan"],
            time_exit_plan=plan_report,
        )

    plan_item = plan_report.plans[0]
    token = confirmation_token(plan_item)
    if confirm_token != token:
        return TimeExitExecuteReport(
            status="confirmation_required",
            exit_executed=False,
            reasons=["confirmation_token_missing_or_mismatch"],
            confirmation_required=True,
            expected_confirmation_token=token,
            time_exit_plan=plan_report,
        )

    execution = _execute_plan(
        client,
        config=config,
        db_path=resolved_db_path,
        checked_at=checked_at,
        plan_item=plan_item,
        plan_report=plan_report,
    )
    exit_executed = execution.status in {
        "time_exit_submitted",
        "time_exit_submitted_cleanup_failed",
        "time_exit_submitted_cleanup_deferred",
    }
    return TimeExitExecuteReport(
        status=execution.status,
        exit_executed=exit_executed,
        reasons=[execution.status],
        confirmation_required=False,
        expected_confirmation_token=token,
        time_exit_plan=plan_report,
        execution=execution,
    )


def confirmation_token(plan_item: TimeExitPlanItem) -> str:
    position = plan_item.position
    order_plan = plan_item.order_plan
    if order_plan is None:
        return ""
    intent_id = position.matching_intent.event_id if position.matching_intent else "missing"
    intent_time = position.matching_intent.occurred_at if position.matching_intent else "missing"
    raw = "|".join(
        [
            order_plan.symbol,
            order_plan.side,
            order_plan.order_type,
            _number(order_plan.quantity),
            str(order_plan.position_side or ""),
            str(order_plan.reduce_only),
            str(intent_id),
            intent_time,
            _number(position.position_amt),
            _number(position.entry_price or 0.0),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"TIME-EXIT-{order_plan.symbol}-{digest}"


def _execute_plan(
    client: BinanceFuturesSignedClient,
    *,
    config: AppConfig,
    db_path: str,
    checked_at: str,
    plan_item: TimeExitPlanItem,
    plan_report: TimeExitPlanReport,
) -> TimeExitExecution:
    assert plan_item.order_plan is not None
    order_plan = plan_item.order_plan
    token = confirmation_token(plan_item)
    close_response: dict[str, Any] | None = None
    post_close_amount: float | None = None
    cancel_response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    status = "time_exit_submitted"
    try:
        close_response = client.new_order(
            symbol=order_plan.symbol,
            side=order_plan.side,
            order_type=order_plan.order_type,
            quantity=order_plan.quantity,
            reduce_only=bool(order_plan.reduce_only),
            position_side=order_plan.position_side,
            new_client_order_id=_client_order_id(order_plan.symbol, checked_at),
        )
    except BinanceSignedError as exc:
        status = "time_exit_failed"
        error = {
            "endpoint": exc.endpoint,
            "code": exc.binance_code,
            "message": exc.binance_message,
        }

    if close_response is not None:
        post_close_amount = _matching_position_amount(
            client,
            symbol=order_plan.symbol,
            position_side=order_plan.position_side,
        )
        if post_close_amount is None:
            status = "time_exit_submitted_cleanup_deferred"
            error = {
                "endpoint": "/fapi/v2/positionRisk",
                "code": None,
                "message": "post-close position check failed",
            }
        elif post_close_amount != 0.0:
            status = "time_exit_submitted_cleanup_deferred"
            error = {
                "endpoint": "/fapi/v2/positionRisk",
                "code": None,
                "message": "position still non-zero after close submission",
            }
        else:
            try:
                cancel_response = client.cancel_all_open_algo_orders(order_plan.symbol)
            except BinanceSignedError as exc:
                status = "time_exit_submitted_cleanup_failed"
                error = {
                    "endpoint": exc.endpoint,
                    "code": exc.binance_code,
                    "message": exc.binance_message,
                }

    persisted: dict[str, int] = {}
    connection = connect(db_path)
    try:
        store = EventStore(connection)
        event_id = _matching_event_id(plan_item)
        intent = _execution_intent(
            config,
            checked_at=checked_at,
            order_plan=order_plan,
            event_id=event_id,
        )
        persisted["exchange_response"] = persist_exchange_response(
            store,
            intent=intent,
            response={
                "time_exit_status": status,
                "confirmation_token": token,
                "close_order": close_response,
                "post_close_position_amt": post_close_amount,
                "cancel_algo_orders": cancel_response,
                "error": error,
                "plan": plan_report.to_dict(),
            },
            response_type="time_exit",
        )
    finally:
        connection.close()

    return TimeExitExecution(
        symbol=order_plan.symbol,
        status=status,
        confirmation_token=token,
        order_plan=order_plan,
        close_order_response=close_response,
        post_close_position_amt=post_close_amount,
        cancel_algo_response=cancel_response,
        persisted=persisted,
        error=error,
    )


def _execution_intent(
    config: AppConfig,
    *,
    checked_at: str,
    order_plan: TimeExitOrderPlan,
    event_id: int | None,
) -> OrderIntent:
    return OrderIntent(
        symbol=order_plan.symbol,
        side=order_plan.side,
        quantity=order_plan.quantity,
        notional_usdt=0.0,
        entry_price=0.0,
        stop_price=0.0,
        target_price=0.0,
        leverage=int(float(config.get("BFA_MAX_LEVERAGE"))),
        mode=config.get("BFA_MODE"),
        decided_at=checked_at,
        order_type=order_plan.order_type,
        reduce_only=bool(order_plan.reduce_only),
        reason_codes=["time_exit_hold_window_expired"],
        metadata={
            "time_exit": True,
            "matching_intent_event_id": event_id,
            "position_side": order_plan.position_side,
        },
    )


def _matching_event_id(plan_item: TimeExitPlanItem) -> int | None:
    if plan_item.position.matching_intent is None:
        return None
    return plan_item.position.matching_intent.event_id


def _matching_position_amount(
    client: BinanceFuturesSignedClient,
    *,
    symbol: str,
    position_side: str | None,
) -> float | None:
    try:
        positions = client.position_risk()
    except BinanceSignedError:
        return None
    amount = 0.0
    found = False
    for position in positions:
        if str(position.get("symbol", "")).upper() != symbol.upper():
            continue
        side = str(position.get("positionSide") or "").upper()
        if position_side and side and side != position_side:
            continue
        amount += _float_or_zero(position.get("positionAmt"))
        found = True
    return amount if found else 0.0


def _client_order_id(symbol: str, checked_at: str) -> str:
    cleaned_time = "".join(ch for ch in checked_at if ch.isdigit())
    return f"bfa-exit-{symbol.lower()}-{cleaned_time}"[:36]


def _now_iso(now: str | None) -> str:
    if now:
        return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".")


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
