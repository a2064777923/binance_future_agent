"""Confirmation-gated live resume action planning and apply wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import subprocess
from typing import Any, Callable, Mapping

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.risk_profile import RiskProfileApplyReport, RiskProfilePlan, apply_risk_profile, build_risk_profile_plan


SYSTEMD_UNITS = {
    "live.timer": "binance-futures-agent-live.timer",
    "live.service": "binance-futures-agent-live.service",
    "paper.timer": "binance-futures-agent-paper.timer",
    "paper.service": "binance-futures-agent-paper.service",
}

DEFAULT_TARGET_SYSTEMD_STATES = {
    "live.timer": "active",
    "live.service": "inactive",
    "paper.timer": "active",
    "paper.service": "inactive",
}


@dataclass(frozen=True)
class SystemdUnitChange:
    name: str
    unit: str
    current_state: str
    target_state: str
    action: str
    command: list[str] = field(default_factory=list)
    needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "current_state": self.current_state,
            "target_state": self.target_state,
            "action": self.action,
            "command": list(self.command),
            "needed": self.needed,
        }


@dataclass(frozen=True)
class LiveResumePlanReport:
    status: str
    resume_allowed: bool
    applies_changes: bool
    reasons: list[str]
    operator_decision: dict[str, Any]
    readiness: dict[str, Any]
    target_profile: RiskProfilePlan
    risk_boundaries: dict[str, Any]
    systemd_plan: dict[str, Any]
    confirmation_token: str
    read_only: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_live_resume_plan_v1",
            "status": self.status,
            "resume_allowed": self.resume_allowed,
            "applies_changes": self.applies_changes,
            "reasons": list(self.reasons),
            "operator_decision": dict(self.operator_decision),
            "readiness": dict(self.readiness),
            "target_profile": self.target_profile.to_dict(),
            "risk_boundaries": dict(self.risk_boundaries),
            "systemd_plan": {
                **dict(self.systemd_plan),
                "actions": [dict(item) for item in self.systemd_plan.get("actions", [])],
            },
            "confirmation_token": self.confirmation_token,
            "read_only": dict(self.read_only),
        }


@dataclass(frozen=True)
class LiveResumeApplyReport:
    status: str
    applied: bool
    reasons: list[str]
    plan: LiveResumePlanReport
    risk_profile_apply: RiskProfileApplyReport | Mapping[str, Any] | None = None
    systemd_actions: list[dict[str, Any]] = field(default_factory=list)
    read_only: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        risk_payload = self.risk_profile_apply
        if isinstance(risk_payload, RiskProfileApplyReport):
            risk_payload = risk_payload.to_dict()
        return {
            "schema": "bfa_live_resume_apply_v1",
            "status": self.status,
            "applied": self.applied,
            "reasons": list(self.reasons),
            "plan": self.plan.to_dict(),
            "risk_profile_apply": dict(risk_payload) if isinstance(risk_payload, Mapping) else None,
            "systemd_actions": [dict(item) for item in self.systemd_actions],
            "read_only": dict(self.read_only),
        }


def build_live_resume_plan(
    config: AppConfig,
    *,
    operator_decision: Mapping[str, Any],
    readiness_artifact_path: str | None = None,
    target_profile: str = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
    current_systemd_states: Mapping[str, str] | None = None,
    target_systemd_states: Mapping[str, str] | None = None,
) -> LiveResumePlanReport:
    decision = _operator_decision_summary(operator_decision)
    risk_plan = build_risk_profile_plan(
        config,
        profile=target_profile,
        allow_two_positions=allow_two_positions,
    )
    systemd = _systemd_plan(
        current_states=current_systemd_states or {},
        target_states=target_systemd_states or DEFAULT_TARGET_SYSTEMD_STATES,
    )
    reasons = _plan_reasons(decision)
    token = _confirmation_token(
        operator_status=str(decision.get("status") or ""),
        readiness_artifact_path=readiness_artifact_path,
        target_profile=risk_plan,
        systemd_plan=systemd,
    )
    resume_allowed = not reasons
    return LiveResumePlanReport(
        status="resume_apply_ready" if resume_allowed else "resume_apply_blocked",
        resume_allowed=resume_allowed,
        applies_changes=False,
        reasons=reasons or ["operator_packet_eligible_confirmation_required"],
        operator_decision=decision,
        readiness={
            "artifact_path": readiness_artifact_path,
            "status": _string_or_none(operator_decision.get("readiness_status")),
            "live_resume_allowed": bool(operator_decision.get("readiness_live_resume_allowed")),
        },
        target_profile=risk_plan,
        risk_boundaries=_risk_boundaries(risk_plan.target_values),
        systemd_plan=systemd,
        confirmation_token=token,
        read_only=_non_mutation_proof(applies_risk_profiles=False, changes_systemd_state=False),
    )


def apply_live_resume_plan(
    config: AppConfig,
    *,
    env_path: str,
    operator_decision: Mapping[str, Any],
    confirm_token: str | None,
    db_path: str | None = None,
    readiness_artifact_path: str | None = None,
    target_profile: str = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
    current_systemd_states: Mapping[str, str] | None = None,
    target_systemd_states: Mapping[str, str] | None = None,
    service_active: bool = False,
    signed_client: BinanceFuturesSignedClient | None = None,
    risk_profile_apply_fn: Callable[..., RiskProfileApplyReport | Mapping[str, Any]] = apply_risk_profile,
    systemd_apply_fn: Callable[[list[SystemdUnitChange]], list[dict[str, Any]]] | None = None,
) -> LiveResumeApplyReport:
    resolved_systemd_apply_fn = systemd_apply_fn or apply_systemd_changes
    plan = build_live_resume_plan(
        config,
        operator_decision=operator_decision,
        readiness_artifact_path=readiness_artifact_path,
        target_profile=target_profile,
        allow_two_positions=allow_two_positions,
        current_systemd_states=current_systemd_states,
        target_systemd_states=target_systemd_states,
    )
    if not plan.resume_allowed:
        return _blocked_apply("operator_decision_not_eligible", plan)
    if confirm_token != plan.confirmation_token:
        return LiveResumeApplyReport(
            status="confirmation_required",
            applied=False,
            reasons=["confirmation_token_missing_or_mismatch"],
            plan=plan,
            read_only=_non_mutation_proof(),
        )
    live_service_state = _state(current_systemd_states or {}, "live.service")
    if service_active or live_service_state == "active":
        return _blocked_apply("live_service_active", plan)
    if live_service_state != "inactive":
        return _blocked_apply("live_service_state_not_confirmed_inactive", plan)

    risk_apply = risk_profile_apply_fn(
        config,
        env_path=env_path,
        db_path=db_path,
        profile=target_profile,
        confirm_token=plan.target_profile.confirmation_token,
        allow_two_positions=allow_two_positions,
        service_active=False,
        signed_client=signed_client,
    )
    risk_applied = bool(_mapping_from_report(risk_apply).get("applied"))
    if not risk_applied:
        reasons = ["risk_profile_apply_failed", *_strings(_mapping_from_report(risk_apply).get("reasons"))]
        return LiveResumeApplyReport(
            status="apply_blocked",
            applied=False,
            reasons=_dedupe(reasons),
            plan=plan,
            risk_profile_apply=risk_apply,
            read_only=_non_mutation_proof(),
        )

    actions = [
        _change_from_dict(item)
        for item in plan.systemd_plan.get("actions", [])
        if bool(item.get("needed"))
    ]
    systemd_results = resolved_systemd_apply_fn(actions)
    failed = [item for item in systemd_results if not bool(item.get("applied", False))]
    if failed:
        return LiveResumeApplyReport(
            status="partial_apply_failed",
            applied=False,
            reasons=["systemd_action_failed"],
            plan=plan,
            risk_profile_apply=risk_apply,
            systemd_actions=systemd_results,
            read_only=_non_mutation_proof(mutates_env_or_systemd=True),
        )
    return LiveResumeApplyReport(
        status="applied",
        applied=True,
        reasons=["live_resume_plan_applied"],
        plan=plan,
        risk_profile_apply=risk_apply,
        systemd_actions=systemd_results,
        read_only=_non_mutation_proof(mutates_env_or_systemd=True),
    )


def apply_systemd_changes(actions: list[SystemdUnitChange]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for action in actions:
        completed = subprocess.run(
            action.command,
            check=False,
            capture_output=True,
            text=True,
        )
        results.append(
            {
                **action.to_dict(),
                "applied": completed.returncode == 0,
                "return_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    return results


def _operator_decision_summary(operator_decision: Mapping[str, Any]) -> dict[str, Any]:
    status = str(operator_decision.get("status") or "unknown")
    return {
        "schema": operator_decision.get("schema"),
        "status": status,
        "eligible_for_operator_resume": status == "eligible_for_operator_resume"
        and bool(operator_decision.get("eligible_for_operator_resume")),
        "readiness_status": operator_decision.get("readiness_status"),
        "readiness_live_resume_allowed": bool(operator_decision.get("readiness_live_resume_allowed")),
        "blocking_categories": list(
            _mapping(operator_decision.get("recommendation")).get("blocking_categories") or []
        ),
        "next_action": _mapping(operator_decision.get("recommendation")).get("next_action"),
    }


def _plan_reasons(decision: Mapping[str, Any]) -> list[str]:
    if decision.get("status") != "eligible_for_operator_resume":
        return [f"operator_decision_{decision.get('status') or 'unknown'}"]
    if not bool(decision.get("eligible_for_operator_resume")):
        return ["operator_decision_eligible_flag_false"]
    return []


def _systemd_plan(
    *,
    current_states: Mapping[str, str],
    target_states: Mapping[str, str],
) -> dict[str, Any]:
    normalized_targets = {
        key: _normalize_state(target_states.get(key, DEFAULT_TARGET_SYSTEMD_STATES[key]))
        for key in SYSTEMD_UNITS
    }
    normalized_current = {key: _state(current_states, key) for key in SYSTEMD_UNITS}
    actions = [
        _unit_change(key, normalized_current[key], normalized_targets[key]).to_dict()
        for key in SYSTEMD_UNITS
    ]
    return {
        "current_states": normalized_current,
        "target_states": normalized_targets,
        "actions": actions,
    }


def _unit_change(name: str, current_state: str, target_state: str) -> SystemdUnitChange:
    unit = SYSTEMD_UNITS[name]
    if current_state == target_state:
        return SystemdUnitChange(
            name=name,
            unit=unit,
            current_state=current_state,
            target_state=target_state,
            action="none",
            needed=False,
        )
    if target_state not in {"active", "inactive"}:
        return SystemdUnitChange(
            name=name,
            unit=unit,
            current_state=current_state,
            target_state=target_state,
            action="none",
            needed=False,
        )
    if target_state == "active":
        return SystemdUnitChange(
            name=name,
            unit=unit,
            current_state=current_state,
            target_state=target_state,
            action="start",
            command=["systemctl", "start", unit],
            needed=True,
        )
    return SystemdUnitChange(
        name=name,
        unit=unit,
        current_state=current_state,
        target_state=target_state,
        action="stop",
        command=["systemctl", "stop", unit],
        needed=True,
    )


def _confirmation_token(
    *,
    operator_status: str,
    readiness_artifact_path: str | None,
    target_profile: RiskProfilePlan,
    systemd_plan: Mapping[str, Any],
) -> str:
    payload = {
        "operator_status": operator_status,
        "readiness_artifact_path": readiness_artifact_path,
        "risk_profile_token": target_profile.confirmation_token,
        "target_profile": target_profile.target_values,
        "systemd_targets": systemd_plan.get("target_states"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"LIVE-RESUME-{target_profile.profile.upper()}-{digest}"


def _risk_boundaries(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "account_capital_usdt": _number(values.get("BFA_ACCOUNT_CAPITAL_USDT")),
        "max_leverage": _number(values.get("BFA_MAX_LEVERAGE")),
        "max_position_notional_usdt": _number(values.get("BFA_MAX_POSITION_NOTIONAL_USDT")),
        "max_risk_per_trade_usdt": _number(values.get("BFA_MAX_RISK_PER_TRADE_USDT")),
        "max_daily_loss_usdt": _number(values.get("BFA_MAX_DAILY_LOSS_USDT")),
        "max_open_positions": _int_or_none(values.get("BFA_MAX_OPEN_POSITIONS")),
        "dynamic_position_sizing_enabled": _truthy(values.get("BFA_DYNAMIC_POSITION_SIZING_ENABLED")),
        "max_margin_per_position_usdt": _number(values.get("BFA_MAX_MARGIN_PER_POSITION_USDT")),
        "max_margin_fraction": _number(values.get("BFA_MAX_MARGIN_FRACTION")),
        "max_effective_notional_usdt": _number(values.get("BFA_MAX_EFFECTIVE_NOTIONAL_USDT")),
        "max_portfolio_margin_usdt": _number(values.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")),
        "max_portfolio_margin_fraction": _number(values.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")),
        "max_portfolio_notional_usdt": _number(values.get("BFA_MAX_PORTFOLIO_NOTIONAL_USDT")),
        "max_same_direction_notional_usdt": _number(values.get("BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT")),
        "multi_position_enabled": _truthy(values.get("BFA_MULTI_POSITION_ENABLED")),
    }


def _non_mutation_proof(
    *,
    applies_risk_profiles: bool = False,
    changes_systemd_state: bool = False,
    mutates_env_or_systemd: bool = False,
) -> dict[str, Any]:
    return {
        "places_orders": False,
        "cancels_orders": False,
        "creates_order_intents": False,
        "mutates_exchange_state": False,
        "writes_env_files": applies_risk_profiles or mutates_env_or_systemd,
        "applies_risk_profiles": applies_risk_profiles or mutates_env_or_systemd,
        "changes_systemd_state": changes_systemd_state or mutates_env_or_systemd,
    }


def _blocked_apply(reason: str, plan: LiveResumePlanReport) -> LiveResumeApplyReport:
    return LiveResumeApplyReport(
        status="apply_blocked",
        applied=False,
        reasons=[reason, *([item for item in plan.reasons if item != "operator_packet_eligible_confirmation_required"])],
        plan=plan,
        read_only=_non_mutation_proof(),
    )


def _change_from_dict(item: Mapping[str, Any]) -> SystemdUnitChange:
    return SystemdUnitChange(
        name=str(item.get("name") or ""),
        unit=str(item.get("unit") or ""),
        current_state=str(item.get("current_state") or "unknown"),
        target_state=str(item.get("target_state") or "unknown"),
        action=str(item.get("action") or "none"),
        command=[str(part) for part in item.get("command") or []],
        needed=bool(item.get("needed")),
    )


def _mapping_from_report(value: RiskProfileApplyReport | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, RiskProfileApplyReport):
        return value.to_dict()
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _state(states: Mapping[str, str], key: str) -> str:
    return _normalize_state(states.get(key, "unknown"))


def _normalize_state(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    if normalized in {"active", "inactive"}:
        return normalized
    return "unknown"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
