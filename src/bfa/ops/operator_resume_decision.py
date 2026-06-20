"""Read-only operator decision packet for live-resume readiness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.exposure_clearance import exposure_clearance_from_payload
from bfa.ops.live_resume_readiness import LiveResumeReadinessReport, build_live_resume_readiness_report
from bfa.ops.strategy_promotion import ALL_INTERVALS_SCOPE


DECISION_STATUSES = {
    "keep_live_paused",
    "collect_more_paper",
    "resolve_exposure",
    "eligible_for_operator_resume",
}


@dataclass(frozen=True)
class OperatorResumeDecisionPacket:
    status: str
    eligible_for_operator_resume: bool
    readiness_status: str
    readiness_live_resume_allowed: bool
    blocker_groups: dict[str, list[str]]
    exposure: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    confirmation_flow: dict[str, Any] = field(default_factory=dict)
    read_only: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_operator_resume_decision_v1",
            "status": self.status,
            "eligible_for_operator_resume": self.eligible_for_operator_resume,
            "readiness_status": self.readiness_status,
            "readiness_live_resume_allowed": self.readiness_live_resume_allowed,
            "blocker_groups": {key: list(value) for key, value in self.blocker_groups.items()},
            "exposure": dict(self.exposure),
            "recommendation": dict(self.recommendation),
            "confirmation_flow": dict(self.confirmation_flow),
            "read_only": dict(self.read_only),
        }


def build_operator_resume_decision_packet(
    config: AppConfig,
    *,
    db_path: str | None = None,
    matrix_report_path: str | None = None,
    variant: str = "quant_setup_selective",
    interval: str = "5m",
    since: str | None = None,
    min_outcomes: int = 20,
    min_win_rate: float = 0.5,
    min_net_pnl_usdt: float = 0.0,
    min_profit_factor: float | None = 1.1,
    max_worst_drawdown_usdt: float | None = 1.5,
    latest_limit: int = 10,
    min_group_outcomes: int = 1,
    worst_limit: int = 8,
    matrix_scope: str = ALL_INTERVALS_SCOPE,
    matrix_intervals: Sequence[str] | None = None,
    matrix_min_trade_count: int = 5,
    matrix_min_positive_window_rate: float = 0.5,
    matrix_max_worst_drawdown_usdt: float | None = None,
    target_profile: str | None = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
    hypothetical_symbol: str | None = None,
    hypothetical_side: str | None = None,
    check_binance: bool = True,
    signed_client: BinanceFuturesSignedClient | None = None,
    exchange_state: str = "auto",
    manual_exposure_symbols: Sequence[str] | None = None,
    check_systemd: bool = True,
    server_state_overrides: Mapping[str, str] | None = None,
    require_operator_confirmation: bool = True,
    exposure_clearance: Mapping[str, Any] | None = None,
) -> OperatorResumeDecisionPacket:
    readiness = build_live_resume_readiness_report(
        config,
        db_path=db_path,
        matrix_report_path=matrix_report_path,
        variant=variant,
        interval=interval,
        since=since,
        min_outcomes=min_outcomes,
        min_win_rate=min_win_rate,
        min_net_pnl_usdt=min_net_pnl_usdt,
        min_profit_factor=min_profit_factor,
        max_worst_drawdown_usdt=max_worst_drawdown_usdt,
        latest_limit=latest_limit,
        min_group_outcomes=min_group_outcomes,
        worst_limit=worst_limit,
        matrix_scope=matrix_scope,
        matrix_intervals=matrix_intervals,
        matrix_min_trade_count=matrix_min_trade_count,
        matrix_min_positive_window_rate=matrix_min_positive_window_rate,
        matrix_max_worst_drawdown_usdt=matrix_max_worst_drawdown_usdt,
        target_profile=target_profile,
        allow_two_positions=allow_two_positions,
        hypothetical_symbol=hypothetical_symbol,
        hypothetical_side=hypothetical_side,
        check_binance=check_binance,
        signed_client=signed_client,
        exchange_state=exchange_state,
        manual_exposure_symbols=manual_exposure_symbols,
        check_systemd=check_systemd,
        server_state_overrides=server_state_overrides,
        require_operator_confirmation=require_operator_confirmation,
    )
    return build_operator_resume_decision_packet_from_readiness(
        readiness,
        exposure_clearance=exposure_clearance,
    )


def build_operator_resume_decision_packet_from_readiness(
    readiness: LiveResumeReadinessReport | Mapping[str, Any],
    *,
    exposure_clearance: Mapping[str, Any] | None = None,
) -> OperatorResumeDecisionPacket:
    payload = readiness.to_dict() if isinstance(readiness, LiveResumeReadinessReport) else dict(readiness)
    clearance = exposure_clearance_from_payload(exposure_clearance) if exposure_clearance else {}
    reasons = _mapping(payload.get("reasons"))
    blocker_groups = {
        "strategy": _strings(reasons.get("matrix")),
        "paper": _strings(reasons.get("strategy_evidence")),
        "server": _strings(reasons.get("server_state")),
        "exchange_manual_exposure": _strings(reasons.get("exchange_state")),
        "exposure_clearance": _clearance_reasons(clearance),
        "risk_profile": _strings(reasons.get("risk_profile")),
        "ai_provider_health": _ai_provider_health_reasons(payload),
        "confirmation": _strings(reasons.get("confirmation")),
    }
    status = _decision_status(blocker_groups)
    exposure = _exposure_summary(payload, clearance=clearance)
    return OperatorResumeDecisionPacket(
        status=status,
        eligible_for_operator_resume=status == "eligible_for_operator_resume",
        readiness_status=str(payload.get("status") or "unknown"),
        readiness_live_resume_allowed=bool(payload.get("live_resume_allowed")),
        blocker_groups=blocker_groups,
        exposure=exposure,
        recommendation=_recommendation(status, blocker_groups),
        confirmation_flow={
            "required_before_live_resume": True,
            "separate_explicit_flow_required": True,
            "this_packet_performs_resume": False,
            "this_packet_applies_profile": False,
        },
        read_only={
            "places_orders": False,
            "applies_risk_profiles": False,
            "writes_env_files": False,
            "changes_systemd_state": False,
            "mutates_exchange_state": False,
            "creates_order_intents": False,
            "restores_live_timer": False,
            "cancels_orders": False,
        },
    )


def _decision_status(blocker_groups: Mapping[str, list[str]]) -> str:
    if (
        blocker_groups.get("exchange_manual_exposure")
        or blocker_groups.get("exposure_clearance")
        or blocker_groups.get("risk_profile")
    ):
        return "resolve_exposure"
    if blocker_groups.get("strategy") or blocker_groups.get("paper"):
        return "collect_more_paper"
    if blocker_groups.get("server") or blocker_groups.get("ai_provider_health"):
        return "keep_live_paused"
    return "eligible_for_operator_resume"


def _recommendation(status: str, blocker_groups: Mapping[str, list[str]]) -> dict[str, Any]:
    next_actions = {
        "resolve_exposure": "resolve_or_classify_exchange_exposure_then_rerun_readiness",
        "collect_more_paper": "collect_more_guarded_paper_or_recalibrate_before_live_resume",
        "keep_live_paused": "fix_server_or_ai_provider_blockers_then_rerun_readiness",
        "eligible_for_operator_resume": "prepare_separate_operator_confirmation_flow",
    }
    return {
        "next_action": next_actions[status],
        "summary": _summary(status),
        "blocking_categories": [key for key, values in blocker_groups.items() if values],
    }


def _summary(status: str) -> str:
    if status == "resolve_exposure":
        return "Exchange/manual exposure or risk-profile blockers must be resolved before live resume."
    if status == "collect_more_paper":
        return "Strategy or forward-paper evidence is not strong enough for live resume."
    if status == "keep_live_paused":
        return "Server or AI/provider health blockers require live automation to stay paused."
    return "Readiness gates are clear except for a separate explicit operator confirmation flow."


def _exposure_summary(payload: Mapping[str, Any], *, clearance: Mapping[str, Any]) -> dict[str, Any]:
    review = _mapping(payload.get("exchange_review"))
    return {
        "manual_or_unattributed_symbols": _strings(review.get("manual_or_unattributed_symbols")),
        "agent_managed_symbols": _strings(review.get("agent_managed_symbols")),
        "manual_exposure_is_agent_evidence": bool(review.get("manual_exposure_is_agent_evidence", False)),
        "position_count": _int_or_zero(review.get("position_count")),
        "open_order_count": _int_or_zero(review.get("open_order_count")),
        "open_algo_order_count": _int_or_zero(review.get("open_algo_order_count")),
        "clearance": dict(clearance),
    }


def _clearance_reasons(clearance: Mapping[str, Any]) -> list[str]:
    if not clearance:
        return []
    reasons: list[str] = []
    if not bool(clearance.get("clearance_allowed")):
        status = str(clearance.get("status") or "exposure_clearance_blocked")
        reasons.append(status)
    for classification in _strings(clearance.get("blocking_classifications")):
        reasons.append(f"clearance_{classification}")
    return _dedupe(reasons)


def _ai_provider_health_reasons(payload: Mapping[str, Any]) -> list[str]:
    strategy = _mapping(payload.get("strategy_evidence"))
    live_status = _mapping(strategy.get("live_status"))
    backoff = _mapping(strategy.get("openai_backoff") or live_status.get("openai_backoff"))
    if bool(backoff.get("active")):
        reason = str(backoff.get("reason") or "ai_provider_backoff_active")
        return [reason]
    return []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
