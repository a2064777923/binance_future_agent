"""Read-only pilot learning packet for live server canaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.exposure_status import ExposureStatusReport, build_exposure_status_report
from bfa.ops.live_outcome_ledger import LiveOutcomeLedgerReport, build_live_outcome_ledger_report
from bfa.ops.position_hold_check import TimeExitPlanReport, build_time_exit_plan_report
from bfa.ops.position_review import PositionReviewReport, build_position_review_report
from bfa.ops.trade_trace import TradeTraceReport, build_trade_trace_report


@dataclass(frozen=True)
class PilotLearningPacketReport:
    status: str
    reasons: list[str]
    manual_symbols: list[str]
    learning_summary: dict[str, Any]
    cap_usage: dict[str, Any]
    lifecycle: dict[str, Any]
    exit_plan: dict[str, Any]
    live_outcomes: dict[str, Any]
    trace_index: list[dict[str, Any]] = field(default_factory=list)
    source_reports: dict[str, Any] = field(default_factory=dict)
    mutation_proof: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_pilot_learning_packet_v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "manual_symbols": list(self.manual_symbols),
            "learning_summary": dict(self.learning_summary),
            "cap_usage": dict(self.cap_usage),
            "lifecycle": dict(self.lifecycle),
            "exit_plan": dict(self.exit_plan),
            "live_outcomes": dict(self.live_outcomes),
            "trace_index": [dict(item) for item in self.trace_index],
            "source_reports": dict(self.source_reports),
            "mutation_proof": dict(self.mutation_proof),
        }


def build_pilot_learning_packet_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    signed_client: BinanceFuturesSignedClient | None = None,
    now: str | None = None,
    latest_traces: int = 5,
) -> PilotLearningPacketReport:
    """Build one read-only packet from live ops evidence."""

    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    exposure = build_exposure_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client if check_binance else None,
        target_profile=None,
    )
    position_review = build_position_review_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        now=now,
        signed_client=signed_client if check_binance else None,
    )
    time_exit = build_time_exit_plan_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        now=now,
        signed_client=signed_client if check_binance else None,
    )
    ledger = build_live_outcome_ledger_report(
        config,
        db_path=resolved_db_path,
        latest_limit=max(1, latest_traces),
        min_group_outcomes=1,
        reconcile=False,
        persist_closed=False,
    )
    traces = _trade_traces(
        db_path=resolved_db_path,
        event_ids=_trace_event_ids(position_review, ledger, max_count=max(0, latest_traces)),
    )
    source_reports = {
        "exposure_status": exposure.to_dict(),
        "position_review": position_review.to_dict(),
        "time_exit_plan": time_exit.to_dict(),
        "live_outcome_ledger": ledger.to_dict(),
        "trade_traces": [trace.to_dict() for trace in traces],
    }
    manual_symbols = config.get_list("BFA_MANUAL_POSITION_SYMBOLS")
    trace_index = _trace_index(
        exposure=exposure,
        position_review=position_review,
        ledger=ledger,
        traces=traces,
    )
    lifecycle = _lifecycle_summary(position_review)
    exit_plan = _exit_summary(time_exit)
    live_outcomes = _live_outcome_summary(ledger)
    cap_usage = _cap_usage(exposure)
    reasons = _packet_reasons(
        exposure=exposure,
        position_review=position_review,
        time_exit=time_exit,
        ledger=ledger,
        trace_index=trace_index,
    )
    return PilotLearningPacketReport(
        status=_packet_status(position_review=position_review, time_exit=time_exit),
        reasons=reasons,
        manual_symbols=manual_symbols,
        learning_summary={
            "mode": config.get("BFA_MODE"),
            "check_binance": check_binance,
            "position_review_status": position_review.status,
            "position_action_required": position_review.action_required,
            "entry_capacity_status": exposure.entry_capacity.status,
            "can_open_new_position": exposure.entry_capacity.can_open_new_position,
            "time_exit_status": time_exit.status,
            "time_exit_allowed": time_exit.exit_allowed,
            "live_ledger_status": ledger.status,
            "guard_feedback_count": len(ledger.guard_feedback),
            "trace_count": len(trace_index),
        },
        cap_usage=cap_usage,
        lifecycle=lifecycle,
        exit_plan=exit_plan,
        live_outcomes=live_outcomes,
        trace_index=trace_index,
        source_reports=source_reports,
        mutation_proof=_mutation_proof(),
    )


def _trace_event_ids(
    position_review: PositionReviewReport,
    ledger: LiveOutcomeLedgerReport,
    *,
    max_count: int,
) -> list[int]:
    ids: list[int] = []
    for item in position_review.positions:
        _append_id(ids, item.matching_intent_event_id)
    for outcome in ledger.latest_outcomes:
        trace_ids = outcome.get("trace_ids") if isinstance(outcome, dict) else {}
        if isinstance(trace_ids, dict):
            _append_id(ids, trace_ids.get("order_intent_event_id"))
    return ids[:max_count]


def _trade_traces(*, db_path: str, event_ids: list[int]) -> list[TradeTraceReport]:
    reports: list[TradeTraceReport] = []
    for event_id in event_ids:
        try:
            reports.append(build_trade_trace_report(db_path=db_path, event_id=event_id))
        except (ValueError, OSError):
            continue
    return reports


def _trace_index(
    *,
    exposure: ExposureStatusReport,
    position_review: PositionReviewReport,
    ledger: LiveOutcomeLedgerReport,
    traces: list[TradeTraceReport],
) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for position in position_review.positions:
        index.append(
            {
                "source": "position_review",
                "symbol": position.symbol,
                "position_side": position.position_side,
                "recommendation": position.recommendation,
                "order_intent_event_id": position.matching_intent_event_id,
            }
        )
    for outcome in ledger.latest_outcomes:
        if not isinstance(outcome, dict):
            continue
        trace_ids = outcome.get("trace_ids") if isinstance(outcome.get("trace_ids"), dict) else {}
        index.append(
            {
                "source": "live_outcome",
                "symbol": outcome.get("symbol"),
                "side": outcome.get("side"),
                "outcome_event_id": trace_ids.get("outcome_event_id"),
                "order_intent_event_id": trace_ids.get("order_intent_event_id"),
                "trade_setup_event_id": trace_ids.get("trade_setup_event_id"),
                "ai_decision_event_id": trace_ids.get("ai_decision_event_id"),
            }
        )
    for trace in traces:
        payload = trace.to_dict()
        exchange_responses = payload.get("exchange_responses") or []
        index.append(
            {
                "source": "trade_trace",
                "symbol": payload.get("symbol"),
                "status": payload.get("status"),
                "order_intent_event_id": _artifact_event_id(payload.get("order_intent")),
                "trade_setup_event_id": _artifact_event_id(payload.get("trade_setup")),
                "ai_decision_event_id": _artifact_event_id(payload.get("ai_decision")),
                "exchange_response_event_ids": [
                    _artifact_event_id(item)
                    for item in exchange_responses
                    if _artifact_event_id(item) is not None
                ],
            }
        )
    if not index and exposure.entry_capacity.active_exposures:
        for item in exposure.entry_capacity.active_exposures:
            index.append(
                {
                    "source": "active_exposure",
                    "symbol": item.get("symbol"),
                    "direction": item.get("direction"),
                    "order_intent_event_id": None,
                }
            )
    return index


def _lifecycle_summary(position_review: PositionReviewReport) -> dict[str, Any]:
    return {
        "status": position_review.status,
        "action_required": position_review.action_required,
        "reasons": list(position_review.reasons),
        "position_count": len(position_review.positions),
        "decisions": [
            {
                "symbol": item.symbol,
                "position_side": item.position_side,
                "recommendation": item.recommendation,
                "urgency": item.urgency,
                "reasons": list(item.reasons),
                "matching_intent_event_id": item.matching_intent_event_id,
                "algo_protection_count": item.algo_protection_count,
            }
            for item in position_review.positions
        ],
    }


def _exit_summary(time_exit: TimeExitPlanReport) -> dict[str, Any]:
    return {
        "status": time_exit.status,
        "exit_allowed": time_exit.exit_allowed,
        "reasons": list(time_exit.reasons),
        "plans": [
            {
                "symbol": item.position.symbol,
                "position_side": item.position.position_side,
                "exit_allowed": item.exit_allowed,
                "reasons": list(item.reasons),
                "order_plan": item.order_plan.to_dict() if item.order_plan else None,
                "matching_intent_event_id": item.position.matching_intent.event_id
                if item.position.matching_intent
                else None,
            }
            for item in time_exit.plans
        ],
    }


def _live_outcome_summary(ledger: LiveOutcomeLedgerReport) -> dict[str, Any]:
    return {
        "status": ledger.status,
        "reasons": list(ledger.reasons),
        "summary": dict(ledger.summary),
        "guard_feedback_count": len(ledger.guard_feedback),
        "guard_feedback": [dict(item) for item in ledger.guard_feedback],
        "latest_trace_ids": [
            dict(item.get("trace_ids"))
            for item in ledger.latest_outcomes
            if isinstance(item.get("trace_ids"), dict)
        ],
    }


def _cap_usage(exposure: ExposureStatusReport) -> dict[str, Any]:
    capacity = exposure.entry_capacity
    max_open = capacity.max_open_positions
    max_notional = capacity.max_portfolio_notional_usdt or 0.0
    max_margin = capacity.max_portfolio_margin_usdt or 0.0
    return {
        "current_profile": dict(exposure.current_profile),
        "current_sizing": exposure.current_sizing.to_dict(),
        "direction_support": exposure.direction_support.to_dict(),
        "entry_capacity": capacity.to_dict(),
        "exchange_summary": dict(exposure.exchange_summary),
        "utilization": {
            "open_positions_fraction": _ratio(capacity.active_position_count, max_open),
            "portfolio_notional_fraction": _ratio(capacity.active_notional_usdt, max_notional),
            "portfolio_margin_fraction": _ratio(capacity.active_initial_margin_usdt, max_margin),
            "manual_position_count": capacity.manual_position_count,
            "bot_position_count": capacity.active_position_count,
        },
    }


def _packet_reasons(
    *,
    exposure: ExposureStatusReport,
    position_review: PositionReviewReport,
    time_exit: TimeExitPlanReport,
    ledger: LiveOutcomeLedgerReport,
    trace_index: list[dict[str, Any]],
) -> list[str]:
    reasons = ["pilot_learning_packet_ready"]
    if position_review.action_required:
        reasons.append("position_review_action_required")
    if time_exit.exit_allowed:
        reasons.append("time_exit_candidate_present")
    if exposure.entry_capacity.can_open_new_position:
        reasons.append("entry_capacity_available")
    else:
        reasons.extend(exposure.entry_capacity.reasons)
    if ledger.guard_feedback:
        reasons.append("guard_feedback_recommendations_present")
    if not trace_index:
        reasons.append("trace_ids_missing")
    return _dedupe(reasons)


def _packet_status(*, position_review: PositionReviewReport, time_exit: TimeExitPlanReport) -> str:
    if position_review.action_required or time_exit.exit_allowed:
        return "review_required"
    return "packet_ready"


def _mutation_proof() -> dict[str, bool]:
    return {
        "places_orders": False,
        "cancels_orders": False,
        "changes_systemd_state": False,
        "writes_env_files": False,
        "raises_risk": False,
        "applies_guard_changes": False,
        "persists_closed_fills_and_outcomes": False,
    }


def _append_id(values: list[int], value: Any) -> None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return
    if parsed not in values:
        values.append(parsed)


def _artifact_event_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    event_id = value.get("event_id")
    try:
        return int(event_id) if event_id is not None else None
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 8)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
