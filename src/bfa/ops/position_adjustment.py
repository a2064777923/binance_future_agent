"""Confirmation-gated active-position adjustment plans and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
import hashlib
from typing import Any, Mapping

from bfa.config import AppConfig, RuntimeMode
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.ops.position_review import (
    PositionReviewItem,
    PositionReviewReport,
    build_position_review_report,
)


@dataclass(frozen=True)
class PositionAdjustmentOrderPlan:
    symbol: str
    action: str
    side: str
    order_type: str
    quantity: float
    position_side: str | None = None
    reduce_only: bool | None = None
    reason_codes: list[str] = field(default_factory=list)
    source_recommendation: str | None = None
    expected_remaining_position_amt: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "position_side": self.position_side,
            "reduce_only": self.reduce_only,
            "reason_codes": list(self.reason_codes),
            "source_recommendation": self.source_recommendation,
            "expected_remaining_position_amt": self.expected_remaining_position_amt,
        }


@dataclass(frozen=True)
class PositionAdjustmentPlanItem:
    review_item: PositionReviewItem
    adjustment_allowed: bool
    reasons: list[str] = field(default_factory=list)
    order_plan: PositionAdjustmentOrderPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_item": self.review_item.to_dict(),
            "adjustment_allowed": self.adjustment_allowed,
            "reasons": list(self.reasons),
            "order_plan": self.order_plan.to_dict() if self.order_plan else None,
        }


@dataclass(frozen=True)
class PositionLifecycleDiagnostic:
    symbol: str
    position_side: str | None
    source_recommendation: str
    lifecycle_decision: str
    urgency: str
    manual_symbol: bool
    protection_state: str
    matching_intent_state: str
    exchange_filter_state: str
    reasons: list[str] = field(default_factory=list)
    failed_preconditions: list[str] = field(default_factory=list)
    passed_preconditions: list[str] = field(default_factory=list)
    candidate_action: str | None = None
    order_plan: PositionAdjustmentOrderPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_side": self.position_side,
            "source_recommendation": self.source_recommendation,
            "lifecycle_decision": self.lifecycle_decision,
            "urgency": self.urgency,
            "manual_symbol": self.manual_symbol,
            "protection_state": self.protection_state,
            "matching_intent_state": self.matching_intent_state,
            "exchange_filter_state": self.exchange_filter_state,
            "reasons": list(self.reasons),
            "failed_preconditions": list(self.failed_preconditions),
            "passed_preconditions": list(self.passed_preconditions),
            "candidate_action": self.candidate_action,
            "order_plan": self.order_plan.to_dict() if self.order_plan else None,
        }


@dataclass(frozen=True)
class PositionAdjustmentPlanReport:
    status: str
    adjustment_allowed: bool
    reasons: list[str] = field(default_factory=list)
    position_review: PositionReviewReport | None = None
    plans: list[PositionAdjustmentPlanItem] = field(default_factory=list)
    diagnostics: list[PositionLifecycleDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "adjustment_allowed": self.adjustment_allowed,
            "reasons": list(self.reasons),
            "position_review": self.position_review.to_dict() if self.position_review else None,
            "plans": [plan.to_dict() for plan in self.plans],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True)
class PositionAdjustmentExecution:
    symbol: str
    status: str
    order_plan: PositionAdjustmentOrderPlan
    order_response: dict[str, Any] | None = None
    post_order_position_amt: float | None = None
    cancel_algo_response: dict[str, Any] | None = None
    persisted: dict[str, int] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "order_plan": self.order_plan.to_dict(),
            "order_response": dict(self.order_response) if self.order_response else None,
            "post_order_position_amt": self.post_order_position_amt,
            "cancel_algo_response": dict(self.cancel_algo_response) if self.cancel_algo_response else None,
            "persisted": dict(self.persisted),
            "error": dict(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class PositionAdjustmentExecuteReport:
    status: str
    adjustment_executed: bool
    reasons: list[str] = field(default_factory=list)
    confirmation_required: bool = False
    expected_confirmation_token: str | None = None
    adjustment_plan: PositionAdjustmentPlanReport | None = None
    executions: list[PositionAdjustmentExecution] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "adjustment_executed": self.adjustment_executed,
            "reasons": list(self.reasons),
            "confirmation_required": self.confirmation_required,
            "expected_confirmation_token": self.expected_confirmation_token,
            "adjustment_plan": self.adjustment_plan.to_dict() if self.adjustment_plan else None,
            "executions": [execution.to_dict() for execution in self.executions],
        }


def build_position_adjustment_plan_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    now: str | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
    market_client=None,
    exchange_info: Mapping[str, Any] | None = None,
    require_filters: bool = True,
) -> PositionAdjustmentPlanReport:
    if not _truthy(config.get("BFA_POSITION_ADJUSTMENT_ENABLED", "true")):
        return PositionAdjustmentPlanReport(
            status="adjustment_disabled",
            adjustment_allowed=False,
            reasons=["position_adjustment_disabled"],
        )
    review = build_position_review_report(
        config,
        db_path=db_path,
        check_binance=check_binance,
        now=now,
        signed_client=signed_client,
    )
    return position_adjustment_plan_from_review(
        review,
        position_mode=config.get("BFA_POSITION_MODE"),
        partial_take_profit_fraction=_float_or_default(config.get("BFA_PARTIAL_TAKE_PROFIT_FRACTION"), 0.5),
        filters_by_symbol=_filters_by_symbol(
            _exchange_info_payload(config, market_client=market_client, exchange_info=exchange_info),
            review,
        ),
        require_filters=require_filters,
    )


def position_adjustment_plan_from_review(
    review: PositionReviewReport,
    *,
    position_mode: str,
    partial_take_profit_fraction: float = 0.5,
    filters_by_symbol: Mapping[str, SymbolExecutionFilters] | None = None,
    require_filters: bool = False,
) -> PositionAdjustmentPlanReport:
    reasons: list[str] = []
    report_blockers: list[str] = []
    plans: list[PositionAdjustmentPlanItem] = []
    hold_check = review.hold_check
    if review.status == "no_active_position":
        reasons.append("no_active_position")
    if "exchange_evidence_missing" in review.reasons:
        reasons.append("exchange_evidence_missing")
        report_blockers.append("exchange_evidence_missing")
    if hold_check and hold_check.open_order_count:
        reasons.append("normal_open_orders_present")
        report_blockers.append("normal_open_orders_present")
    if hold_check and hold_check.openai_backoff_active:
        reasons.append("ai_backoff_active")

    for item in review.positions:
        plan = _plan_for_item(
            item,
            position_mode=position_mode,
            partial_take_profit_fraction=partial_take_profit_fraction,
            filters=filters_by_symbol.get(item.symbol.upper()) if filters_by_symbol else None,
            require_filters=require_filters,
        )
        if plan is not None:
            plans.append(plan)
            if not plan.adjustment_allowed:
                reasons.extend(plan.reasons)

    diagnostics = _diagnostics_for_review(
        review,
        plans,
        global_blockers=report_blockers,
        filters_by_symbol=filters_by_symbol,
        require_filters=require_filters,
    )
    if not plans and not reasons:
        reasons.append("no_adjustment_candidate")
    if any(not item.adjustment_allowed for item in plans):
        reasons.append("position_adjustment_preconditions_failed")

    allowed_plans = [item for item in plans if item.adjustment_allowed]
    if allowed_plans and not reasons:
        return PositionAdjustmentPlanReport(
            status="adjustment_plan_ready",
            adjustment_allowed=True,
            reasons=["position_adjustment_preconditions_met"],
            position_review=review,
            plans=plans,
            diagnostics=diagnostics,
        )
    if allowed_plans and all(reason in {"ai_backoff_active"} for reason in reasons):
        return PositionAdjustmentPlanReport(
            status="adjustment_plan_ready",
            adjustment_allowed=True,
            reasons=["position_adjustment_preconditions_met", *reasons],
            position_review=review,
            plans=plans,
            diagnostics=diagnostics,
        )
    return PositionAdjustmentPlanReport(
        status="adjustment_plan_blocked" if plans else "adjustment_plan_empty",
        adjustment_allowed=False,
        reasons=_dedupe(reasons),
        position_review=review,
        plans=plans,
        diagnostics=diagnostics,
    )


def build_position_adjustment_execute_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    confirm_token: str | None = None,
    now: str | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
    market_client=None,
    exchange_info: Mapping[str, Any] | None = None,
    service_active: bool = False,
) -> PositionAdjustmentExecuteReport:
    if RuntimeMode(config.get("BFA_MODE")) is not RuntimeMode.LIVE:
        return PositionAdjustmentExecuteReport(
            status="execution_blocked",
            adjustment_executed=False,
            reasons=["live_mode_required"],
        )
    if service_active:
        return PositionAdjustmentExecuteReport(
            status="execution_blocked",
            adjustment_executed=False,
            reasons=["live_service_active"],
        )
    if confirm_token and now:
        return PositionAdjustmentExecuteReport(
            status="execution_blocked",
            adjustment_executed=False,
            reasons=["now_override_not_allowed_for_confirmed_execution"],
        )

    client = signed_client or BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    checked_at = _now_iso(now)
    plan_report = build_position_adjustment_plan_report(
        config,
        db_path=resolved_db_path,
        check_binance=True,
        now=checked_at,
        signed_client=client,
        market_client=market_client,
        exchange_info=exchange_info,
        require_filters=True,
    )
    if not plan_report.adjustment_allowed:
        return PositionAdjustmentExecuteReport(
            status="execution_blocked",
            adjustment_executed=False,
            reasons=["position_adjustment_plan_not_ready", *plan_report.reasons],
            adjustment_plan=plan_report,
        )

    token = confirmation_token(plan_report)
    if confirm_token != token:
        return PositionAdjustmentExecuteReport(
            status="confirmation_required",
            adjustment_executed=False,
            reasons=["confirmation_token_missing_or_mismatch"],
            confirmation_required=True,
            expected_confirmation_token=token,
            adjustment_plan=plan_report,
        )

    executions = [
        _execute_plan_item(
            client,
            config=config,
            db_path=resolved_db_path,
            checked_at=checked_at,
            item=item,
        )
        for item in plan_report.plans
        if item.adjustment_allowed and item.order_plan is not None
    ]
    statuses = [execution.status for execution in executions]
    adjustment_executed = any(status.startswith("position_adjustment_submitted") for status in statuses)
    status = "position_adjustment_submitted" if adjustment_executed else "position_adjustment_failed"
    if any(status.endswith("_failed") for status in statuses):
        status = "position_adjustment_partial_failure" if adjustment_executed else "position_adjustment_failed"
    return PositionAdjustmentExecuteReport(
        status=status,
        adjustment_executed=adjustment_executed,
        reasons=_dedupe(statuses or [status]),
        confirmation_required=False,
        expected_confirmation_token=token,
        adjustment_plan=plan_report,
        executions=executions,
    )


def confirmation_token(plan_report: PositionAdjustmentPlanReport) -> str:
    actions = [
        item.order_plan
        for item in plan_report.plans
        if item.adjustment_allowed and item.order_plan is not None
    ]
    if not actions:
        return ""
    raw = "|".join(
        [
            *[
                ":".join(
                    [
                        action.symbol,
                        action.action,
                        action.side,
                        action.order_type,
                        _number(action.quantity),
                        str(action.position_side or ""),
                        str(action.reduce_only),
                        ",".join(action.reason_codes),
                        str(item.review_item.matching_intent_event_id or ""),
                        _number(item.review_item.position_amt),
                        _number(item.review_item.entry_price or 0.0),
                    ]
                )
                for item in plan_report.plans
                for action in [item.order_plan]
                if item.adjustment_allowed and action is not None
            ],
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    symbols = "-".join(_dedupe([action.symbol for action in actions]))[:20]
    return f"POSITION-ADJUST-{symbols}-{digest}"


def _diagnostics_for_review(
    review: PositionReviewReport,
    plans: list[PositionAdjustmentPlanItem],
    *,
    global_blockers: list[str],
    filters_by_symbol: Mapping[str, SymbolExecutionFilters] | None,
    require_filters: bool,
) -> list[PositionLifecycleDiagnostic]:
    plans_by_position = {_position_key(plan.review_item): plan for plan in plans}
    return [
        _diagnostic_for_item(
            item,
            plan=plans_by_position.get(_position_key(item)),
            global_blockers=global_blockers,
            filters=filters_by_symbol.get(item.symbol.upper()) if filters_by_symbol else None,
            require_filters=require_filters,
        )
        for item in review.positions
    ]


def _diagnostic_for_item(
    item: PositionReviewItem,
    *,
    plan: PositionAdjustmentPlanItem | None,
    global_blockers: list[str],
    filters: SymbolExecutionFilters | None,
    require_filters: bool,
) -> PositionLifecycleDiagnostic:
    manual_symbol = item.recommendation == "manual_hold" or "manual_position_ignored" in item.reasons
    order_plan = plan.order_plan if plan else None
    failed = _diagnostic_failed_preconditions(item, plan=plan, global_blockers=global_blockers)
    passed = _diagnostic_passed_preconditions(item, plan=plan)
    lifecycle_decision = _lifecycle_decision(item, plan=plan, failed_preconditions=failed)
    if manual_symbol:
        lifecycle_decision = "manual_hold"
        failed = _dedupe([*failed, "manual_position_ignored"])
        order_plan = None
    return PositionLifecycleDiagnostic(
        symbol=item.symbol,
        position_side=item.position_side,
        source_recommendation=item.recommendation,
        lifecycle_decision=lifecycle_decision,
        urgency=item.urgency,
        manual_symbol=manual_symbol,
        protection_state="protected" if item.algo_protection_count > 0 else "unprotected",
        matching_intent_state="present" if item.matching_intent_event_id is not None else "missing",
        exchange_filter_state=_exchange_filter_state(
            item,
            plan=plan,
            filters=filters,
            require_filters=require_filters,
        ),
        reasons=_dedupe([*item.reasons, *(plan.reasons if plan else [])]),
        failed_preconditions=failed,
        passed_preconditions=passed,
        candidate_action=order_plan.action if order_plan else None,
        order_plan=order_plan,
    )


def _position_key(item: PositionReviewItem) -> tuple[str, str | None]:
    return (item.symbol.upper(), item.position_side)


def _diagnostic_failed_preconditions(
    item: PositionReviewItem,
    *,
    plan: PositionAdjustmentPlanItem | None,
    global_blockers: list[str],
) -> list[str]:
    failures: list[str] = list(global_blockers)
    if item.recommendation == "manual_hold":
        failures.append("manual_position_ignored")
    elif plan is not None and not plan.adjustment_allowed:
        failures.extend(plan.reasons)
    elif plan is None and item.recommendation in {"close_review", "trail_or_reduce"}:
        failures.append("adjustment_candidate_missing")
    return _dedupe(failures)


def _diagnostic_passed_preconditions(
    item: PositionReviewItem,
    *,
    plan: PositionAdjustmentPlanItem | None,
) -> list[str]:
    passed: list[str] = []
    if item.position_amt != 0:
        passed.append("non_zero_position")
    if item.algo_protection_count > 0:
        passed.append("algo_protection_present")
    if item.matching_intent_event_id is not None:
        passed.append("matching_intent_present")
    if item.recommendation in {"close_review", "trail_or_reduce"}:
        passed.append("actionable_review_recommendation")
    if plan and plan.order_plan is not None:
        passed.append("order_plan_candidate_built")
        if "quantity_filter_checked" in plan.order_plan.reason_codes:
            passed.append("exchange_quantity_filters_passed")
    return _dedupe(passed)


def _lifecycle_decision(
    item: PositionReviewItem,
    *,
    plan: PositionAdjustmentPlanItem | None,
    failed_preconditions: list[str],
) -> str:
    if item.recommendation == "manual_hold":
        return "manual_hold"
    if item.recommendation == "watch":
        return "watch"
    if item.recommendation == "hold":
        return "hold"
    if failed_preconditions:
        return "blocked"
    if plan and plan.adjustment_allowed and plan.order_plan is not None:
        if plan.order_plan.action == "full_close":
            return "close_ready"
        if plan.order_plan.action == "partial_take_profit":
            return "reduce"
    return "blocked"


def _exchange_filter_state(
    item: PositionReviewItem,
    *,
    plan: PositionAdjustmentPlanItem | None,
    filters: SymbolExecutionFilters | None,
    require_filters: bool,
) -> str:
    if item.recommendation not in {"close_review", "trail_or_reduce"}:
        return "not_applicable"
    if plan and "symbol_filters_missing" in plan.reasons:
        return "missing"
    if filters is None and require_filters:
        return "missing"
    if plan and any(
        reason
        in {
            "quantity_not_positive_after_step",
            "quantity_below_min",
            "quantity_above_max",
            "notional_below_min",
            "full_close_quantity_not_step_aligned",
        }
        for reason in plan.reasons
    ):
        return "failed"
    if plan and plan.order_plan and "quantity_filter_checked" in plan.order_plan.reason_codes:
        return "checked"
    if filters is not None:
        return "checked"
    return "not_required"


def _plan_for_item(
    item: PositionReviewItem,
    *,
    position_mode: str,
    partial_take_profit_fraction: float,
    filters: SymbolExecutionFilters | None,
    require_filters: bool,
) -> PositionAdjustmentPlanItem | None:
    if item.position_amt == 0:
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=["zero_position_amount"],
        )
    if item.recommendation == "trail_or_reduce":
        return _partial_reduce_plan(
            item,
            position_mode=position_mode,
            fraction=partial_take_profit_fraction,
            filters=filters,
            require_filters=require_filters,
        )
    if item.recommendation == "close_review":
        return _full_close_plan(
            item,
            position_mode=position_mode,
            filters=filters,
            require_filters=require_filters,
        )
    if item.recommendation == "watch":
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=["watch_only_recheck_later"],
        )
    return None


def _partial_reduce_plan(
    item: PositionReviewItem,
    *,
    position_mode: str,
    fraction: float,
    filters: SymbolExecutionFilters | None,
    require_filters: bool,
) -> PositionAdjustmentPlanItem:
    if require_filters and filters is None:
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=["symbol_filters_missing"],
        )
    bounded_fraction = min(max(fraction, 0.0), 1.0)
    desired_quantity = abs(item.position_amt) * bounded_fraction
    quantity_check = _filtered_reduce_quantity(
        item,
        desired_quantity=desired_quantity,
        filters=filters,
        check_min_notional=True,
    )
    if quantity_check.rejection_reasons:
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=quantity_check.rejection_reasons,
        )
    quantity = quantity_check.quantity
    remaining = abs(item.position_amt) - quantity
    return PositionAdjustmentPlanItem(
        review_item=item,
        adjustment_allowed=True,
        reasons=["partial_take_profit_candidate"],
        order_plan=_market_reduce_plan(
            item,
            action="partial_take_profit",
            quantity=quantity,
            reason_codes=_dedupe(["partial_take_profit", *quantity_check.reason_codes, *item.reasons]),
            expected_remaining=round(remaining if item.position_amt > 0 else -remaining, 8),
            position_mode=position_mode,
        ),
    )


def _full_close_plan(
    item: PositionReviewItem,
    *,
    position_mode: str,
    filters: SymbolExecutionFilters | None,
    require_filters: bool,
) -> PositionAdjustmentPlanItem:
    if require_filters and filters is None:
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=["symbol_filters_missing"],
        )
    quantity_check = _filtered_reduce_quantity(
        item,
        desired_quantity=abs(item.position_amt),
        filters=filters,
        check_min_notional=False,
    )
    if quantity_check.rejection_reasons:
        return PositionAdjustmentPlanItem(
            review_item=item,
            adjustment_allowed=False,
            reasons=quantity_check.rejection_reasons,
        )
    return PositionAdjustmentPlanItem(
        review_item=item,
        adjustment_allowed=True,
        reasons=["full_close_candidate"],
        order_plan=_market_reduce_plan(
            item,
            action="full_close",
            quantity=quantity_check.quantity,
            reason_codes=_dedupe(["position_review_close", *quantity_check.reason_codes, *item.reasons]),
            expected_remaining=0.0,
            position_mode=position_mode,
        ),
    )


def _market_reduce_plan(
    item: PositionReviewItem,
    *,
    action: str,
    quantity: float,
    reason_codes: list[str],
    expected_remaining: float,
    position_mode: str,
) -> PositionAdjustmentOrderPlan:
    side = "SELL" if item.position_amt > 0 else "BUY"
    hedge_mode = position_mode.strip().lower() == "hedge"
    return PositionAdjustmentOrderPlan(
        symbol=item.symbol,
        action=action,
        side=side,
        order_type="MARKET",
        quantity=quantity,
        position_side=item.position_side if hedge_mode else None,
        reduce_only=False if hedge_mode else True,
        reason_codes=_dedupe(reason_codes),
        source_recommendation=item.recommendation,
        expected_remaining_position_amt=expected_remaining,
    )


@dataclass(frozen=True)
class _FilteredReduceQuantity:
    quantity: float
    reason_codes: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)


def _filtered_reduce_quantity(
    item: PositionReviewItem,
    *,
    desired_quantity: float,
    filters: SymbolExecutionFilters | None,
    check_min_notional: bool,
) -> _FilteredReduceQuantity:
    if filters is None:
        return _FilteredReduceQuantity(quantity=round(desired_quantity, 8))
    desired = Decimal(str(desired_quantity))
    rounded = _round_down(desired, filters.step_size)
    reasons = ["quantity_filter_checked"]
    rejections: list[str] = []
    if rounded <= 0:
        rejections.append("quantity_not_positive_after_step")
    if filters.min_qty is not None and rounded < filters.min_qty:
        rejections.append("quantity_below_min")
    if filters.max_qty is not None and rounded > filters.max_qty:
        rejections.append("quantity_above_max")
    reference_price = Decimal(str(item.mark_price or item.entry_price or 0.0))
    if check_min_notional and filters.min_notional is not None and reference_price > 0:
        notional = rounded * reference_price
        if notional < filters.min_notional:
            rejections.append("notional_below_min")
    if not check_min_notional and rounded != desired:
        rejections.append("full_close_quantity_not_step_aligned")
    return _FilteredReduceQuantity(
        quantity=float(rounded),
        reason_codes=reasons,
        rejection_reasons=_dedupe(rejections),
    )


def _round_down(value: Decimal, increment: Decimal | None) -> Decimal:
    if increment is None or increment <= 0:
        return value
    units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
    return units * increment


def _exchange_info_payload(
    config: AppConfig,
    *,
    market_client=None,
    exchange_info: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if exchange_info is not None:
        return exchange_info
    client = market_client
    if client is None:
        client = BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))
    try:
        return client.exchange_info().payload
    except Exception:
        return None


def _filters_by_symbol(
    exchange_info: Mapping[str, Any] | None,
    review: PositionReviewReport,
) -> dict[str, SymbolExecutionFilters]:
    if not exchange_info:
        return {}
    result: dict[str, SymbolExecutionFilters] = {}
    for item in review.positions:
        try:
            result[item.symbol.upper()] = SymbolExecutionFilters.from_exchange_info(exchange_info, item.symbol)
        except ValueError:
            continue
    return result


def _execute_plan_item(
    client: BinanceFuturesSignedClient,
    *,
    config: AppConfig,
    db_path: str,
    checked_at: str,
    item: PositionAdjustmentPlanItem,
) -> PositionAdjustmentExecution:
    assert item.order_plan is not None
    order_plan = item.order_plan
    response: dict[str, Any] | None = None
    post_amount: float | None = None
    cancel_response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    status = "position_adjustment_submitted"
    try:
        response = client.new_order(
            symbol=order_plan.symbol,
            side=order_plan.side,
            order_type=order_plan.order_type,
            quantity=order_plan.quantity,
            reduce_only=bool(order_plan.reduce_only),
            position_side=order_plan.position_side,
            new_client_order_id=_client_order_id(order_plan.symbol, checked_at, action=order_plan.action),
        )
    except BinanceSignedError as exc:
        status = "position_adjustment_failed"
        error = {
            "endpoint": exc.endpoint,
            "code": exc.binance_code,
            "message": exc.binance_message,
        }

    if response is not None:
        post_amount = _matching_position_amount(
            client,
            symbol=order_plan.symbol,
            position_side=order_plan.position_side,
        )
        if post_amount is None:
            status = "position_adjustment_submitted_cleanup_deferred"
            error = {
                "endpoint": "/fapi/v2/positionRisk",
                "code": None,
                "message": "post-adjustment position check failed",
            }
        elif order_plan.action == "full_close" and post_amount != 0.0:
            status = "position_adjustment_submitted_cleanup_deferred"
            error = {
                "endpoint": "/fapi/v2/positionRisk",
                "code": None,
                "message": "position still non-zero after full close submission",
            }
        elif order_plan.action == "full_close":
            try:
                cancel_response = client.cancel_all_open_algo_orders(order_plan.symbol)
            except BinanceSignedError as exc:
                status = "position_adjustment_submitted_cleanup_failed"
                error = {
                    "endpoint": exc.endpoint,
                    "code": exc.binance_code,
                    "message": exc.binance_message,
                }

    persisted: dict[str, int] = {}
    connection = connect(db_path)
    try:
        store = EventStore(connection)
        intent = _execution_intent(config, checked_at=checked_at, order_plan=order_plan)
        persisted["order_intent"] = persist_order_intent(
            store,
            intent=intent,
            status=status,
            risk=RiskDecision(True, ["position_adjustment_confirmed"]),
        )
        persisted["exchange_response"] = persist_exchange_response(
            store,
            intent=intent,
            response={
                "position_adjustment_status": status,
                "order": response,
                "post_order_position_amt": post_amount,
                "cancel_algo_orders": cancel_response,
                "error": error,
                "plan_item": item.to_dict(),
            },
            response_type="position_adjustment",
        )
    finally:
        connection.close()

    return PositionAdjustmentExecution(
        symbol=order_plan.symbol,
        status=status,
        order_plan=order_plan,
        order_response=response,
        post_order_position_amt=post_amount,
        cancel_algo_response=cancel_response,
        persisted=persisted,
        error=error,
    )


def _execution_intent(
    config: AppConfig,
    *,
    checked_at: str,
    order_plan: PositionAdjustmentOrderPlan,
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
        reason_codes=list(order_plan.reason_codes),
        metadata={
            "position_adjustment": True,
            "adjustment_action": order_plan.action,
            "position_side": order_plan.position_side,
            "source_recommendation": order_plan.source_recommendation,
        },
    )


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
        amount += _float_or_default(position.get("positionAmt"), 0.0)
        found = True
    return amount if found else 0.0


def _client_order_id(symbol: str, checked_at: str, *, action: str) -> str:
    cleaned_time = "".join(ch for ch in checked_at if ch.isdigit())
    prefix = "bfa-adj-part" if action == "partial_take_profit" else "bfa-adj-close"
    return f"{prefix}-{symbol.lower()}-{cleaned_time}"[:36]


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _now_iso(now: str | None) -> str:
    if now:
        return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace(
            "+00:00",
            "Z",
        )
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".")


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
