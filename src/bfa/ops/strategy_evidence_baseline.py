"""Compact read-only baseline for strategy evidence and live-resume blockers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import shutil
import subprocess
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect
from bfa.ops.forward_paper_loss_attribution import (
    ForwardPaperLossAttributionReport,
    build_forward_paper_loss_attribution_report,
)
from bfa.ops.forward_paper_performance import (
    ForwardPaperPerformanceReport,
    build_forward_paper_performance_report,
)
from bfa.strategy.paper_guard import ForwardPaperGuard, build_forward_paper_guard, guard_config_from_app


SERVER_UNITS = {
    "paper.timer": "binance-futures-agent-paper.timer",
    "live.timer": "binance-futures-agent-live.timer",
    "live.service": "binance-futures-agent-live.service",
}


@dataclass(frozen=True)
class StrategyEvidenceBaselineReport:
    status: str
    live_resume_allowed: bool
    reasons: dict[str, list[str]]
    variant: str
    interval: str
    performance: ForwardPaperPerformanceReport
    loss_attribution: ForwardPaperLossAttributionReport
    paper_guard: ForwardPaperGuard
    server_state: dict[str, Any] = field(default_factory=dict)
    exchange_state: dict[str, Any] = field(default_factory=dict)
    confirmation: dict[str, Any] = field(default_factory=dict)
    read_only: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_strategy_evidence_baseline_v1",
            "status": self.status,
            "live_resume_allowed": self.live_resume_allowed,
            "reasons": {key: list(value) for key, value in self.reasons.items()},
            "variant": self.variant,
            "interval": self.interval,
            "performance": self.performance.to_dict(),
            "loss_attribution": self.loss_attribution.to_dict(),
            "paper_guard": self.paper_guard.to_dict(),
            "server_state": dict(self.server_state),
            "exchange_state": dict(self.exchange_state),
            "confirmation": dict(self.confirmation),
            "read_only": dict(self.read_only),
        }


def build_strategy_evidence_baseline_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    variant: str = "quant_setup_selective",
    interval: str = "5m",
    since: str | None = None,
    min_outcomes: int = 20,
    min_win_rate: float = 0.5,
    min_net_pnl_usdt: float = 0.0,
    min_profit_factor: float | None = None,
    max_worst_drawdown_usdt: float | None = 1.5,
    latest_limit: int = 10,
    min_group_outcomes: int = 1,
    worst_limit: int = 8,
    server_state_overrides: Mapping[str, str] | None = None,
    check_systemd: bool = True,
    exchange_state: str = "unknown",
    manual_exposure_symbols: list[str] | None = None,
    require_operator_confirmation: bool = True,
) -> StrategyEvidenceBaselineReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    performance = build_forward_paper_performance_report(
        resolved_db_path,
        variant=variant,
        interval=interval,
        since=since,
        min_outcomes=min_outcomes,
        min_win_rate=min_win_rate,
        min_net_pnl_usdt=min_net_pnl_usdt,
        min_profit_factor=min_profit_factor,
        max_worst_drawdown_usdt=max_worst_drawdown_usdt,
        latest_limit=latest_limit,
    )
    loss_attribution = build_forward_paper_loss_attribution_report(
        resolved_db_path,
        variant=variant,
        interval=interval,
        since=since,
        min_group_outcomes=min_group_outcomes,
        worst_limit=worst_limit,
    )
    paper_guard = _build_guard(
        config,
        db_path=resolved_db_path,
        variant=variant,
        interval=interval,
        since=since,
    )
    server_state = _server_state(check_systemd=check_systemd, overrides=server_state_overrides)
    exchange = _exchange_state(exchange_state, manual_exposure_symbols or [])
    confirmation = _confirmation(require_operator_confirmation=require_operator_confirmation)
    reasons = _reason_groups(
        performance=performance,
        loss_attribution=loss_attribution,
        paper_guard=paper_guard,
        server_state=server_state,
        exchange_state=exchange,
        confirmation=confirmation,
    )
    live_resume_allowed = not any(reasons.values())
    return StrategyEvidenceBaselineReport(
        status=_status(reasons),
        live_resume_allowed=live_resume_allowed,
        reasons=reasons,
        variant=variant,
        interval=interval,
        performance=performance,
        loss_attribution=loss_attribution,
        paper_guard=paper_guard,
        server_state=server_state,
        exchange_state=exchange,
        confirmation=confirmation,
        read_only={
            "places_orders": False,
            "applies_risk_profiles": False,
            "writes_env_files": False,
            "changes_systemd_state": False,
            "mutates_exchange_state": False,
            "creates_order_intents": False,
        },
    )


def _build_guard(
    config: AppConfig,
    *,
    db_path: str,
    variant: str,
    interval: str,
    since: str | None,
) -> ForwardPaperGuard:
    guard_config = guard_config_from_app(config)
    guard_config = replace(
        guard_config,
        variant=variant,
        interval=interval,
        since=since if since is not None else guard_config.since,
    )
    connection = connect(db_path)
    try:
        return build_forward_paper_guard(connection, guard_config)
    finally:
        connection.close()


def _server_state(
    *,
    check_systemd: bool,
    overrides: Mapping[str, str] | None,
) -> dict[str, Any]:
    states = {}
    for key, unit in SERVER_UNITS.items():
        state = _systemd_is_active(unit) if check_systemd else "unknown"
        if overrides and key in overrides and overrides[key]:
            state = str(overrides[key]).strip() or state
        states[key] = {"unit": unit, "state": state}
    return states


def _systemd_is_active(unit: str) -> str:
    if shutil.which("systemctl") is None:
        return "unknown"
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    state = result.stdout.strip() or result.stderr.strip()
    return state or "unknown"


def _exchange_state(state: str, manual_symbols: list[str]) -> dict[str, Any]:
    normalized = state.strip().lower()
    if normalized not in {"unknown", "clear", "manual_exposure", "agent_exposure", "open_orders"}:
        normalized = "unknown"
    return {
        "state": normalized,
        "manual_exposure_symbols": [symbol.upper() for symbol in manual_symbols],
        "manual_exposure_is_agent_evidence": False,
    }


def _confirmation(*, require_operator_confirmation: bool) -> dict[str, Any]:
    return {
        "required": require_operator_confirmation,
        "received": False,
        "reason": "operator_confirmation_required" if require_operator_confirmation else "not_required",
    }


def _reason_groups(
    *,
    performance: ForwardPaperPerformanceReport,
    loss_attribution: ForwardPaperLossAttributionReport,
    paper_guard: ForwardPaperGuard,
    server_state: Mapping[str, Any],
    exchange_state: Mapping[str, Any],
    confirmation: Mapping[str, Any],
) -> dict[str, list[str]]:
    strategy_reasons: list[str] = []
    if not performance.paper_promotion_allowed:
        strategy_reasons.extend(performance.reasons)
    if loss_attribution.status != "loss_attribution_ready":
        strategy_reasons.extend(loss_attribution.reasons)
    if paper_guard.status == "active" and (
        paper_guard.symbol_blocks or paper_guard.side_blocks or paper_guard.factor_blocks
    ):
        strategy_reasons.extend(paper_guard.reasons)

    server_reasons = _server_reasons(server_state)
    exchange_reasons = _exchange_reasons(exchange_state)
    confirmation_reasons = ["operator_confirmation_required"] if confirmation.get("required") else []
    return {
        "strategy_evidence": _dedupe(strategy_reasons),
        "server_state": server_reasons,
        "exchange_state": exchange_reasons,
        "confirmation": confirmation_reasons,
    }


def _server_reasons(server_state: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    paper_timer = _state_value(server_state.get("paper.timer"))
    live_timer = _state_value(server_state.get("live.timer"))
    live_service = _state_value(server_state.get("live.service"))
    if paper_timer != "active":
        reasons.append("paper_timer_not_active_or_unknown")
    if live_timer == "active":
        reasons.append("live_timer_already_active")
    if live_service == "active":
        reasons.append("live_service_currently_active")
    return reasons


def _exchange_reasons(exchange_state: Mapping[str, Any]) -> list[str]:
    state = str(exchange_state.get("state") or "unknown")
    if state == "clear":
        return []
    if state == "manual_exposure":
        return ["manual_exchange_exposure_present"]
    if state == "agent_exposure":
        return ["agent_exchange_exposure_present"]
    if state == "open_orders":
        return ["exchange_open_orders_present"]
    return ["exchange_state_not_checked"]


def _status(reasons: Mapping[str, list[str]]) -> str:
    if reasons.get("strategy_evidence"):
        return "keep_live_paused"
    if any(reasons.values()):
        return "live_resume_blocked"
    return "live_resume_ready"


def _state_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("state") or "unknown").strip().lower()
    return str(value or "unknown").strip().lower()


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
