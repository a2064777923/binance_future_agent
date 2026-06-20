"""Dynamic position sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.config import AppConfig


@dataclass(frozen=True)
class PositionSizingInput:
    account_capital_usdt: float
    max_leverage: float
    fixed_max_notional_usdt: float
    max_risk_per_trade_usdt: float
    max_margin_per_position_usdt: float
    max_margin_fraction: float
    max_effective_notional_usdt: float
    available_balance_usdt: float | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    min_executable_notional_usdt: float | None = None


@dataclass(frozen=True)
class PositionSizingResult:
    enabled: bool
    max_position_notional_usdt: float
    fixed_max_notional_usdt: float
    max_position_margin_usdt: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_position_notional_usdt": self.max_position_notional_usdt,
            "fixed_max_notional_usdt": self.fixed_max_notional_usdt,
            "max_position_margin_usdt": self.max_position_margin_usdt,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def sizing_input_from_config(
    config: AppConfig,
    *,
    available_balance_usdt: float | None = None,
    candidate: Mapping[str, Any] | None = None,
    entry_price: float | None = None,
    stop_price: float | None = None,
) -> PositionSizingInput:
    features = _mapping(candidate.get("features")) if isinstance(candidate, Mapping) else {}
    return PositionSizingInput(
        account_capital_usdt=float(config.get("BFA_ACCOUNT_CAPITAL_USDT")),
        max_leverage=float(config.get("BFA_MAX_LEVERAGE")),
        fixed_max_notional_usdt=float(config.get("BFA_MAX_POSITION_NOTIONAL_USDT")),
        max_risk_per_trade_usdt=float(config.get("BFA_MAX_RISK_PER_TRADE_USDT")),
        max_margin_per_position_usdt=float(config.get("BFA_MAX_MARGIN_PER_POSITION_USDT")),
        max_margin_fraction=float(config.get("BFA_MAX_MARGIN_FRACTION")),
        max_effective_notional_usdt=float(config.get("BFA_MAX_EFFECTIVE_NOTIONAL_USDT")),
        available_balance_usdt=available_balance_usdt,
        entry_price=entry_price or _float_or_none(features.get("reference_price")),
        stop_price=stop_price,
        min_executable_notional_usdt=_float_or_none(features.get("min_executable_notional")),
    )


def compute_position_sizing(
    sizing: PositionSizingInput,
    *,
    enabled: bool,
) -> PositionSizingResult:
    if not enabled:
        return PositionSizingResult(
            enabled=False,
            max_position_notional_usdt=sizing.fixed_max_notional_usdt,
            fixed_max_notional_usdt=sizing.fixed_max_notional_usdt,
            max_position_margin_usdt=_margin(sizing.fixed_max_notional_usdt, sizing.max_leverage),
            reasons=["fixed_notional_cap"],
        )

    balance_base = min(
        sizing.account_capital_usdt,
        sizing.available_balance_usdt
        if sizing.available_balance_usdt is not None
        else sizing.account_capital_usdt,
    )
    margin_cap = min(
        sizing.max_margin_per_position_usdt,
        balance_base * sizing.max_margin_fraction,
    )
    leverage_notional = margin_cap * sizing.max_leverage
    risk_notional = _risk_based_notional(sizing)
    candidates = [
        sizing.max_effective_notional_usdt,
        leverage_notional,
    ]
    reasons = ["effective_notional_cap", "margin_fraction_cap"]
    if risk_notional is not None:
        candidates.append(risk_notional)
        reasons.append("stop_risk_cap")
    notional = max(0.0, min(candidates))
    warnings: list[str] = []
    if (
        sizing.min_executable_notional_usdt is not None
        and notional < sizing.min_executable_notional_usdt
    ):
        warnings.append("below_min_executable_notional")
    return PositionSizingResult(
        enabled=True,
        max_position_notional_usdt=round(notional, 8),
        fixed_max_notional_usdt=sizing.fixed_max_notional_usdt,
        max_position_margin_usdt=round(_margin(notional, sizing.max_leverage), 8),
        reasons=reasons,
        warnings=warnings,
    )


def dynamic_sizing_enabled(config: AppConfig) -> bool:
    return str(config.get("BFA_DYNAMIC_POSITION_SIZING_ENABLED")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def multi_position_enabled(config: AppConfig) -> bool:
    return str(config.get("BFA_MULTI_POSITION_ENABLED")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _risk_based_notional(sizing: PositionSizingInput) -> float | None:
    if sizing.entry_price is None or sizing.stop_price is None:
        return None
    if sizing.entry_price <= 0:
        return None
    stop_distance_fraction = abs(sizing.entry_price - sizing.stop_price) / sizing.entry_price
    if stop_distance_fraction <= 0:
        return None
    return sizing.max_risk_per_trade_usdt / stop_distance_fraction


def _margin(notional: float, leverage: float) -> float:
    if leverage <= 0:
        return notional
    return notional / leverage


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
