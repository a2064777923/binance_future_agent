"""Confirmation-gated risk profile planning and env application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.risk_change_check import RiskChangeCheckReport, build_risk_change_check_report


APPROVED_PROFILE_KEYS = (
    "BFA_ACCOUNT_CAPITAL_USDT",
    "BFA_MAX_LEVERAGE",
    "BFA_MAX_POSITION_NOTIONAL_USDT",
    "BFA_MAX_RISK_PER_TRADE_USDT",
    "BFA_MAX_DAILY_LOSS_USDT",
    "BFA_MAX_OPEN_POSITIONS",
    "BFA_DYNAMIC_POSITION_SIZING_ENABLED",
    "BFA_MAX_MARGIN_PER_POSITION_USDT",
    "BFA_MAX_MARGIN_FRACTION",
    "BFA_MAX_EFFECTIVE_NOTIONAL_USDT",
    "BFA_MAX_PORTFOLIO_MARGIN_USDT",
    "BFA_MAX_PORTFOLIO_MARGIN_FRACTION",
    "BFA_MAX_PORTFOLIO_NOTIONAL_USDT",
    "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT",
    "BFA_MULTI_POSITION_ENABLED",
)


PROFILE_30U_8X_DYNAMIC = {
    "BFA_ACCOUNT_CAPITAL_USDT": "30",
    "BFA_MAX_LEVERAGE": "8",
    "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
    "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
    "BFA_MAX_DAILY_LOSS_USDT": "1",
    "BFA_MAX_OPEN_POSITIONS": "1",
    "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
    "BFA_MAX_MARGIN_PER_POSITION_USDT": "3",
    "BFA_MAX_MARGIN_FRACTION": "0.08",
    "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
    "BFA_MAX_PORTFOLIO_MARGIN_USDT": "6",
    "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "0.18",
    "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "45",
    "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "30",
    "BFA_MULTI_POSITION_ENABLED": "false",
}

PROFILE_30U_10X_MULTI_DYNAMIC = {
    "BFA_ACCOUNT_CAPITAL_USDT": "30",
    "BFA_MAX_LEVERAGE": "10",
    "BFA_MAX_POSITION_NOTIONAL_USDT": "60",
    "BFA_MAX_RISK_PER_TRADE_USDT": "0.4",
    "BFA_MAX_DAILY_LOSS_USDT": "1",
    "BFA_MAX_OPEN_POSITIONS": "6",
    "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
    "BFA_MAX_MARGIN_PER_POSITION_USDT": "6",
    "BFA_MAX_MARGIN_FRACTION": "0.20",
    "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "60",
    "BFA_MAX_PORTFOLIO_MARGIN_USDT": "30",
    "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "0.95",
    "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "360",
    "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "300",
    "BFA_MULTI_POSITION_ENABLED": "true",
}


@dataclass(frozen=True)
class RiskProfileDiffItem:
    key: str
    current: str
    target: str
    changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "current": self.current,
            "target": self.target,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class RiskProfilePlan:
    profile: str
    target_leverage: int
    target_values: dict[str, str]
    diff: list[RiskProfileDiffItem]
    confirmation_token: str
    allow_two_positions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "target_leverage": self.target_leverage,
            "allow_two_positions": self.allow_two_positions,
            "target_values": dict(self.target_values),
            "diff": [item.to_dict() for item in self.diff],
            "confirmation_token": self.confirmation_token,
        }


@dataclass(frozen=True)
class RiskProfileApplyReport:
    status: str
    applied: bool
    reasons: list[str] = field(default_factory=list)
    plan: RiskProfilePlan | None = None
    risk_change: RiskChangeCheckReport | None = None
    backup_path: str | None = None
    written_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "applied": self.applied,
            "reasons": list(self.reasons),
            "plan": self.plan.to_dict() if self.plan else None,
            "risk_change": self.risk_change.to_dict() if self.risk_change else None,
            "backup_path": self.backup_path,
            "written_keys": list(self.written_keys),
        }


def build_risk_profile_plan(
    config: AppConfig,
    *,
    profile: str,
    allow_two_positions: bool = False,
) -> RiskProfilePlan:
    target = target_profile_values(profile, allow_two_positions=allow_two_positions)
    diff = [
        RiskProfileDiffItem(
            key=key,
            current=config.get(key),
            target=target[key],
            changed=config.get(key) != target[key],
        )
        for key in APPROVED_PROFILE_KEYS
    ]
    return RiskProfilePlan(
        profile=profile,
        target_leverage=int(float(target["BFA_MAX_LEVERAGE"])),
        target_values=target,
        diff=diff,
        confirmation_token=confirmation_token(profile, target),
        allow_two_positions=allow_two_positions,
    )


def apply_risk_profile(
    config: AppConfig,
    *,
    env_path: str,
    db_path: str | None = None,
    profile: str,
    confirm_token: str | None,
    allow_two_positions: bool = False,
    service_active: bool = False,
    risk_change_report: RiskChangeCheckReport | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
) -> RiskProfileApplyReport:
    plan = build_risk_profile_plan(
        config,
        profile=profile,
        allow_two_positions=allow_two_positions,
    )
    if service_active:
        return RiskProfileApplyReport(
            status="apply_blocked",
            applied=False,
            reasons=["live_service_active"],
            plan=plan,
        )
    if confirm_token != plan.confirmation_token:
        return RiskProfileApplyReport(
            status="confirmation_required",
            applied=False,
            reasons=["confirmation_token_missing_or_mismatch"],
            plan=plan,
        )
    risk_change = risk_change_report or build_risk_change_check_report(
        config,
        db_path=db_path,
        check_binance=True,
        target_leverage=plan.target_leverage,
        target_profile=plan.target_values,
        signed_client=signed_client,
    )
    if not risk_change.risk_change_allowed:
        return RiskProfileApplyReport(
            status="apply_blocked",
            applied=False,
            reasons=["risk_change_not_allowed", *risk_change.reasons],
            plan=plan,
            risk_change=risk_change,
        )

    backup_path = write_env_profile(env_path, plan.target_values)
    return RiskProfileApplyReport(
        status="applied",
        applied=True,
        reasons=["profile_applied"],
        plan=plan,
        risk_change=risk_change,
        backup_path=backup_path,
        written_keys=list(APPROVED_PROFILE_KEYS),
    )


def target_profile_values(profile: str, *, allow_two_positions: bool = False) -> dict[str, str]:
    if profile == "30u_8x_dynamic":
        target = dict(PROFILE_30U_8X_DYNAMIC)
    elif profile == "30u_10x_multi_dynamic":
        target = dict(PROFILE_30U_10X_MULTI_DYNAMIC)
    else:
        raise ValueError("profile must be 30u_8x_dynamic or 30u_10x_multi_dynamic")
    if allow_two_positions:
        target["BFA_MAX_OPEN_POSITIONS"] = str(max(int(target["BFA_MAX_OPEN_POSITIONS"]), 2))
        target["BFA_MULTI_POSITION_ENABLED"] = "true"
    return target


def confirmation_token(profile: str, values: Mapping[str, str]) -> str:
    raw = "|".join([profile, *[f"{key}={values[key]}" for key in APPROVED_PROFILE_KEYS]])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"RISK-PROFILE-{profile.upper()}-{digest}"


def write_env_profile(env_path: str, target_values: Mapping[str, str]) -> str:
    path = Path(env_path)
    if not path.exists():
        raise FileNotFoundError(env_path)
    current = _read_env_lines(path)
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    seen: set[str] = set()
    output: list[str] = []
    for raw_line in current:
        key = _line_key(raw_line)
        if key in APPROVED_PROFILE_KEYS:
            output.append(f"{key}={target_values[key]}")
            seen.add(key)
        else:
            output.append(raw_line)
    for key in APPROVED_PROFILE_KEYS:
        if key not in seen:
            output.append(f"{key}={target_values[key]}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return str(backup)


def _read_env_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _line_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()
