"""Dynamic position sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.execution.models import RiskState


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


@dataclass(frozen=True)
class AdaptiveSizingGovernorResult:
    enabled: bool
    accepted: bool
    base_notional_usdt: float | None
    final_notional_usdt: float | None
    hard_cap_notional_usdt: float | None
    multiplier: float
    components: dict[str, float]
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_adaptive_sizing_governor_v1",
            "enabled": self.enabled,
            "accepted": self.accepted,
            "base_notional_usdt": self.base_notional_usdt,
            "final_notional_usdt": self.final_notional_usdt,
            "hard_cap_notional_usdt": self.hard_cap_notional_usdt,
            "multiplier": self.multiplier,
            "components": dict(self.components),
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
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


def adaptive_sizing_governor_enabled(config: AppConfig) -> bool:
    return str(config.get("BFA_ADAPTIVE_SIZING_GOVERNOR_ENABLED")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def apply_adaptive_sizing_governor(
    config: AppConfig,
    *,
    setup: Mapping[str, Any] | Any,
    candidate: Mapping[str, Any] | Any,
    risk_state: RiskState | None = None,
    paper_guard: Any | None = None,
) -> AdaptiveSizingGovernorResult:
    setup_payload = setup.to_dict() if hasattr(setup, "to_dict") else _mapping(setup)
    candidate_payload = candidate.to_dict() if hasattr(candidate, "to_dict") else _mapping(candidate)
    enabled = adaptive_sizing_governor_enabled(config)
    base_notional = _float_or_none(setup_payload.get("notional_usdt"))
    diagnostics: dict[str, Any] = {
        "setup_decision": setup_payload.get("decision"),
        "candidate_symbol": candidate_payload.get("symbol"),
    }
    if not enabled:
        return AdaptiveSizingGovernorResult(
            enabled=False,
            accepted=True,
            base_notional_usdt=base_notional,
            final_notional_usdt=base_notional,
            hard_cap_notional_usdt=None,
            multiplier=1.0,
            components={"disabled": 1.0},
            reason_codes=["adaptive_sizing_governor_disabled"],
            diagnostics=diagnostics,
        )
    if setup_payload.get("decision") != "trade" or base_notional is None:
        return AdaptiveSizingGovernorResult(
            enabled=True,
            accepted=True,
            base_notional_usdt=base_notional,
            final_notional_usdt=base_notional,
            hard_cap_notional_usdt=None,
            multiplier=1.0,
            components={"setup_not_trade": 1.0},
            reason_codes=["setup_not_trade"],
            diagnostics=diagnostics,
        )

    features = _mapping(candidate_payload.get("features"))
    price_basis = _mapping(setup_payload.get("price_basis"))
    factor_summary = _mapping(setup_payload.get("factor_summary"))
    sizing_diagnostics = _mapping(price_basis.get("sizing_diagnostics"))
    liquidation = _mapping(price_basis.get("liquidation_diagnostics"))
    stop_distance_percent = _first_float(
        setup_payload.get("stop_distance_percent"),
        price_basis.get("stop_distance_percent"),
        sizing_diagnostics.get("stop_distance_percent"),
    )
    max_leverage = _float_or_none(config.get("BFA_MAX_LEVERAGE")) or 1.0
    hard_cap, cap_diagnostics = _hard_cap_notional(
        config,
        stop_distance_percent=stop_distance_percent,
        risk_state=risk_state,
        max_leverage=max_leverage,
    )
    diagnostics.update(cap_diagnostics)
    if hard_cap <= 0:
        return AdaptiveSizingGovernorResult(
            enabled=True,
            accepted=False,
            base_notional_usdt=base_notional,
            final_notional_usdt=None,
            hard_cap_notional_usdt=round(hard_cap, 8),
            multiplier=0.0,
            components={"hard_cap": 0.0},
            reason_codes=["adaptive_sizing_no_remaining_cap"],
            diagnostics=diagnostics,
        )

    components, component_warnings, component_blocks, component_diagnostics = _governor_components(
        config,
        features=features,
        factor_summary=factor_summary,
        price_basis=price_basis,
        liquidation=liquidation,
        setup_payload=setup_payload,
        stop_distance_percent=stop_distance_percent,
        risk_state=risk_state,
        paper_guard=paper_guard,
        max_leverage=max_leverage,
    )
    diagnostics.update(component_diagnostics)
    if component_blocks:
        return AdaptiveSizingGovernorResult(
            enabled=True,
            accepted=False,
            base_notional_usdt=base_notional,
            final_notional_usdt=None,
            hard_cap_notional_usdt=round(hard_cap, 8),
            multiplier=0.0,
            components=components,
            reason_codes=_dedupe(component_blocks),
            warnings=_dedupe(component_warnings),
            diagnostics=diagnostics,
        )

    raw_multiplier = 1.0
    for value in components.values():
        raw_multiplier *= value
    multiplier = _clip(
        raw_multiplier,
        _float_or_none(config.get("BFA_ADAPTIVE_SIZING_MIN_MULTIPLIER")) or 0.25,
        _float_or_none(config.get("BFA_ADAPTIVE_SIZING_MAX_MULTIPLIER")) or 1.15,
    )
    guard_downsize_active = (
        components.get("outcome_health", 1.0) < 1.0
        and any("_downsize:" in warning for warning in component_warnings)
    )
    expansion_allowed = (
        components.get("signal_quality", 0.0) >= 1.0
        and multiplier >= 0.95
        and not guard_downsize_active
    )
    if expansion_allowed:
        target_notional = min(hard_cap, max(base_notional, hard_cap * multiplier))
    elif guard_downsize_active:
        target_notional = min(hard_cap, base_notional * multiplier)
    else:
        target_notional = min(base_notional, hard_cap * multiplier)
    min_executable = _positive_float(features.get("min_executable_notional"))
    reason_codes = ["adaptive_sizing_accepted"]
    warnings = list(component_warnings)
    if target_notional > base_notional:
        reason_codes.append("adaptive_scaled_up_within_caps")
    elif target_notional < base_notional:
        reason_codes.append("adaptive_downsized")
    if min_executable is not None and target_notional < min_executable:
        if min_executable <= hard_cap:
            target_notional = min_executable
            warnings.append("adaptive_raised_to_min_executable_notional")
        else:
            return AdaptiveSizingGovernorResult(
                enabled=True,
                accepted=False,
                base_notional_usdt=base_notional,
                final_notional_usdt=None,
                hard_cap_notional_usdt=round(hard_cap, 8),
                multiplier=round(multiplier, 8),
                components=components,
                reason_codes=["min_executable_exceeds_adaptive_cap"],
                warnings=_dedupe(warnings),
                diagnostics={**diagnostics, "min_executable_notional": min_executable},
            )
    diagnostics.update(
        {
            "raw_multiplier": round(raw_multiplier, 8),
            "bounded_multiplier": round(multiplier, 8),
            "guard_downsize_active": guard_downsize_active,
            "expansion_allowed": expansion_allowed,
            "target_notional_before_rounding_usdt": target_notional,
            "min_executable_notional": min_executable,
        }
    )
    return AdaptiveSizingGovernorResult(
        enabled=True,
        accepted=True,
        base_notional_usdt=round(base_notional, 8),
        final_notional_usdt=round(target_notional, 8),
        hard_cap_notional_usdt=round(hard_cap, 8),
        multiplier=round(multiplier, 8),
        components={key: round(value, 8) for key, value in components.items()},
        reason_codes=_dedupe(reason_codes),
        warnings=_dedupe(warnings),
        diagnostics=diagnostics,
    )


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


def _hard_cap_notional(
    config: AppConfig,
    *,
    stop_distance_percent: float | None,
    risk_state: RiskState | None,
    max_leverage: float,
) -> tuple[float, dict[str, Any]]:
    cap_candidates: dict[str, float] = {
        "max_position_notional": _float_or_none(config.get("BFA_MAX_POSITION_NOTIONAL_USDT")) or 0.0,
        "max_effective_notional": _float_or_none(config.get("BFA_MAX_EFFECTIVE_NOTIONAL_USDT")) or 0.0,
    }
    if stop_distance_percent is not None and stop_distance_percent > 0:
        max_risk = _float_or_none(config.get("BFA_MAX_RISK_PER_TRADE_USDT")) or 0.0
        cap_candidates["stop_risk_notional"] = max_risk / (stop_distance_percent / 100.0)
    if risk_state is not None and risk_state.account_available_balance_usdt is not None:
        cap_candidates["available_balance_notional"] = max(0.0, risk_state.account_available_balance_usdt) * max_leverage
    portfolio_remaining = _portfolio_remaining_margin(config, risk_state)
    if portfolio_remaining is not None:
        cap_candidates["portfolio_remaining_margin_notional"] = max(0.0, portfolio_remaining) * max_leverage
    positive_caps = [value for value in cap_candidates.values() if value > 0]
    hard_cap = min(positive_caps) if positive_caps else 0.0
    return hard_cap, {
        "hard_cap_candidates": {key: round(value, 8) for key, value in cap_candidates.items()},
        "portfolio_remaining_margin_usdt": round(portfolio_remaining, 8) if portfolio_remaining is not None else None,
    }


def _governor_components(
    config: AppConfig,
    *,
    features: Mapping[str, Any],
    factor_summary: Mapping[str, Any],
    price_basis: Mapping[str, Any],
    liquidation: Mapping[str, Any],
    setup_payload: Mapping[str, Any],
    stop_distance_percent: float | None,
    risk_state: RiskState | None,
    paper_guard: Any | None,
    max_leverage: float,
) -> tuple[dict[str, float], list[str], list[str], dict[str, Any]]:
    warnings: list[str] = []
    blocks: list[str] = []
    diagnostics: dict[str, Any] = {}
    components = {
        "signal_quality": _signal_quality_multiplier(factor_summary),
        "liquidity": _liquidity_multiplier(config, features, warnings, blocks),
        "volatility": _volatility_multiplier(config, features, warnings, blocks),
        "stop_liquidation": _stop_liquidation_multiplier(
            config,
            price_basis=price_basis,
            liquidation=liquidation,
            setup_payload=setup_payload,
            stop_distance_percent=stop_distance_percent,
            max_leverage=max_leverage,
            warnings=warnings,
            blocks=blocks,
        ),
        "manual_margin_pressure": _manual_margin_multiplier(config, risk_state, warnings, blocks),
        "outcome_health": _outcome_health_multiplier(setup_payload, paper_guard, warnings, blocks),
    }
    diagnostics["component_inputs"] = {
        "edge_score": _float_or_none(factor_summary.get("edge_score")),
        "confidence": _float_or_none(factor_summary.get("confidence")),
        "coverage_ratio": _float_or_none(factor_summary.get("coverage_ratio")),
        "quote_volume": _float_or_none(features.get("quote_volume")),
        "volatility_percent": _feature_volatility(features),
        "stop_distance_percent": stop_distance_percent,
        "manual_initial_margin_usdt": risk_state.manual_initial_margin_usdt if risk_state else 0.0,
        "account_available_balance_usdt": risk_state.account_available_balance_usdt if risk_state else None,
    }
    return components, warnings, blocks, diagnostics


def _signal_quality_multiplier(factor_summary: Mapping[str, Any]) -> float:
    edge = _float_or_none(factor_summary.get("edge_score")) or 0.0
    confidence = _float_or_none(factor_summary.get("confidence")) or 0.0
    coverage = _float_or_none(factor_summary.get("coverage_ratio")) or 0.0
    quality = 0.45 + min(edge, 60.0) / 60.0 * 0.45
    quality += (confidence - 0.55) * 0.6
    quality += (coverage - 0.70) * 0.25
    return _clip(quality, 0.35, 1.15)


def _liquidity_multiplier(
    config: AppConfig,
    features: Mapping[str, Any],
    warnings: list[str],
    blocks: list[str],
) -> float:
    quote_volume = _float_or_none(features.get("quote_volume"))
    min_liquidity = _float_or_none(config.get("BFA_MIN_LIQUIDITY_QUOTE_VOLUME_USDT")) or 5_000_000.0
    strong_liquidity = _float_or_none(config.get("BFA_STRONG_LIQUIDITY_QUOTE_VOLUME_USDT")) or 50_000_000.0
    if quote_volume is None:
        warnings.append("adaptive_missing_liquidity")
        return 0.75
    if quote_volume < min_liquidity:
        blocks.append("insufficient_liquidity_for_adaptive_sizing")
        return 0.0
    if quote_volume >= strong_liquidity:
        return 1.05
    if quote_volume < min_liquidity * 2:
        warnings.append("adaptive_thin_liquidity_downsize")
        return 0.70
    return 1.0


def _volatility_multiplier(
    config: AppConfig,
    features: Mapping[str, Any],
    warnings: list[str],
    blocks: list[str],
) -> float:
    volatility = _feature_volatility(features)
    if volatility is None:
        warnings.append("adaptive_missing_volatility")
        return 0.85
    block_at = _float_or_none(config.get("BFA_HIGH_LEVERAGE_BLOCK_VOLATILITY_PERCENT")) or 12.0
    downsize_at = _float_or_none(config.get("BFA_HIGH_LEVERAGE_MAX_VOLATILITY_PERCENT")) or 8.0
    if volatility >= block_at:
        blocks.append("volatility_exceeds_high_leverage_block")
        return 0.0
    if volatility >= downsize_at:
        warnings.append("adaptive_high_volatility_downsize")
        return 0.55
    if volatility < 0.15:
        warnings.append("adaptive_compressed_volatility_downsize")
        return 0.70
    if volatility <= 3.0:
        return 1.03
    return 0.85


def _stop_liquidation_multiplier(
    config: AppConfig,
    *,
    price_basis: Mapping[str, Any],
    liquidation: Mapping[str, Any],
    setup_payload: Mapping[str, Any],
    stop_distance_percent: float | None,
    max_leverage: float,
    warnings: list[str],
    blocks: list[str],
) -> float:
    if stop_distance_percent is None:
        warnings.append("adaptive_missing_stop_distance")
        return 0.75
    min_stop = _float_or_none(config.get("BFA_HIGH_LEVERAGE_MIN_STOP_DISTANCE_PERCENT")) or 0.35
    micro_grid = _is_micro_grid_setup(setup_payload, price_basis)
    if stop_distance_percent < min_stop and not micro_grid:
        blocks.append("stop_distance_too_tight_for_high_leverage")
        return 0.0
    if stop_distance_percent < min_stop and micro_grid:
        warnings.append("adaptive_micro_grid_tight_stop_allowed")
    threshold = _float_or_none(config.get("BFA_HIGH_LEVERAGE_THRESHOLD")) or 8.0
    if max_leverage < threshold:
        return 1.0
    liquidation_distance = (
        _float_or_none(liquidation.get("approx_liquidation_distance_percent"))
        or (100.0 / max(max_leverage, 1.0))
    )
    ratio_cap = _float_or_none(config.get("BFA_HIGH_LEVERAGE_MAX_STOP_TO_LIQUIDATION_RATIO")) or 0.45
    stop_to_liq = stop_distance_percent / liquidation_distance if liquidation_distance > 0 else 1.0
    if stop_to_liq > ratio_cap:
        blocks.append("stop_too_close_to_liquidation_for_high_leverage")
        return 0.0
    if stop_to_liq > ratio_cap * 0.8:
        warnings.append("adaptive_stop_liquidation_buffer_downsize")
        return 0.70
    if bool(liquidation) and not liquidation.get("stop_before_liquidation", True):
        blocks.append("stop_after_liquidation")
        return 0.0
    if _float_or_none(price_basis.get("risk_reward_ratio")) is not None and float(price_basis["risk_reward_ratio"]) < 1.2:
        warnings.append("adaptive_low_risk_reward_downsize")
        return 0.80
    return 1.0


def _is_micro_grid_setup(setup_payload: Mapping[str, Any], price_basis: Mapping[str, Any]) -> bool:
    if str(setup_payload.get("regime") or "").startswith("micro_grid"):
        return True
    if str(price_basis.get("profile") or "") == "micro_grid_v5f_live":
        return True
    return any(str(reason) == "strategy_leg:micro_grid" for reason in setup_payload.get("reasons", []) or [])


def _manual_margin_multiplier(
    config: AppConfig,
    risk_state: RiskState | None,
    warnings: list[str],
    blocks: list[str],
) -> float:
    if not _truthy(config.get("BFA_MANUAL_MARGIN_PRESSURE_GUARD_ENABLED")) or risk_state is None:
        return 1.0
    cap = _portfolio_margin_cap(config)
    if cap <= 0:
        return 1.0
    manual_margin = risk_state.manual_initial_margin_usdt
    total_margin = risk_state.total_initial_margin_usdt
    if total_margin >= cap:
        blocks.append("portfolio_margin_pressure_from_manual_positions")
        return 0.0
    pressure = manual_margin / cap
    if pressure >= 0.75:
        warnings.append("adaptive_manual_margin_pressure_downsize")
        return 0.50
    if pressure >= 0.50:
        warnings.append("adaptive_manual_margin_pressure_downsize")
        return 0.65
    if pressure >= 0.30:
        warnings.append("adaptive_manual_margin_pressure_downsize")
        return 0.80
    return 1.0


def _outcome_health_multiplier(
    setup_payload: Mapping[str, Any],
    paper_guard: Any | None,
    warnings: list[str],
    blocks: list[str],
) -> float:
    if paper_guard is None:
        return 1.0
    symbol = str(setup_payload.get("symbol") or "").upper()
    side = str(setup_payload.get("side") or "").lower()
    active = bool(getattr(paper_guard, "active", False))
    if not active:
        return 1.0
    symbol_blocks = getattr(paper_guard, "symbol_blocks", {}) or {}
    side_blocks = getattr(paper_guard, "side_blocks", {}) or {}
    if symbol in symbol_blocks:
        mode = _relax_block_on_low_samples(_guard_mode_for(paper_guard, "symbol", symbol), symbol_blocks[symbol], warnings, symbol)
        if mode == "observe":
            warnings.append(f"forward_paper_symbol_observed:{symbol}")
            return 1.0
        if mode == "downsize":
            warnings.append(f"forward_paper_symbol_downsize:{symbol}")
            return _clip(
                _float_or_none(getattr(paper_guard, "symbol_downsize_multiplier", None)) or 0.65,
                _OUTCOME_HEALTH_DOWNSIZE_FLOOR,
                1.0,
            )
        blocks.append(f"forward_paper_symbol_block:{symbol}")
        return 0.0
    if side in side_blocks:
        mode = _relax_block_on_low_samples(_guard_mode_for(paper_guard, "side", side), side_blocks[side], warnings, side)
        if mode == "observe":
            warnings.append(f"forward_paper_side_observed:{side}")
            return 1.0
        if mode == "downsize":
            warnings.append(f"forward_paper_side_downsize:{side}")
            return _clip(
                _float_or_none(getattr(paper_guard, "side_downsize_multiplier", None)) or 0.65,
                _OUTCOME_HEALTH_DOWNSIZE_FLOOR,
                1.0,
            )
        blocks.append(f"forward_paper_side_block:{side}")
        return 0.0
    factor_blocks = getattr(paper_guard, "factor_blocks", {}) or {}
    setup_reasons = {str(reason) for reason in setup_payload.get("reasons", [])}
    blocked_factors = sorted(setup_reasons & set(factor_blocks))
    if blocked_factors:
        mode = str(getattr(paper_guard, "factor_mode", "block") or "block").lower()
        low_sample_factors = [
            reason for reason in blocked_factors
            if _should_relax_factor_block(reason, factor_blocks)
        ]
        if low_sample_factors and mode == "block":
            mode = "downsize"
            warnings.append(
                f"forward_paper_factor_block_relaxed_low_sample:{','.join(low_sample_factors)}"
            )
        if mode == "observe":
            warnings.extend(f"forward_paper_factor_observed:{reason}" for reason in blocked_factors)
            return 1.0
        if mode == "downsize":
            warnings.extend(f"forward_paper_factor_downsize:{reason}" for reason in blocked_factors)
            return _clip(
                _float_or_none(getattr(paper_guard, "factor_downsize_multiplier", None)) or 0.65,
                _OUTCOME_HEALTH_DOWNSIZE_FLOOR,
                1.0,
            )
        blocks.extend(f"forward_paper_factor_block:{reason}" for reason in blocked_factors)
        return 0.0
    return 1.0


# Below the block sample floor a paper-guard block is statistically too thin to
# fully shut the bot out: doing so starves the system of the fresh samples it
# needs to ever clear the block. Such blocks are downgraded to a downsize with
# a hard floor so the agent keeps producing measurable evidence instead of
# locking itself into a no-trade positive feedback loop.
_OUTCOME_HEALTH_DOWNSIZE_FLOOR = 0.5
_OUTCOME_HEALTH_BLOCK_SAMPLE_FLOOR = 30


def _relax_block_on_low_samples(
    mode: str,
    stats: Any,
    warnings: list[str],
    name: str,
) -> str:
    if mode != "block":
        return mode
    outcome_count = int(getattr(stats, "outcome_count", 0) or 0)
    if outcome_count < _OUTCOME_HEALTH_BLOCK_SAMPLE_FLOOR:
        warnings.append(
            f"forward_paper_block_relaxed_low_sample:{name}:{outcome_count}/{_OUTCOME_HEALTH_BLOCK_SAMPLE_FLOOR}"
        )
        return "downsize"
    return mode


def _should_relax_factor_block(reason: str, factor_blocks: Mapping[str, Any]) -> bool:
    stats = factor_blocks.get(reason)
    if stats is None:
        return False
    outcome_count = int(getattr(stats, "outcome_count", 0) or 0)
    return outcome_count < _OUTCOME_HEALTH_BLOCK_SAMPLE_FLOOR


def _guard_mode_for(paper_guard: Any, group: str, name: str) -> str:
    method_name = f"{group}_mode_for"
    method = getattr(paper_guard, method_name, None)
    if callable(method):
        value = method(name)
    else:
        value = getattr(paper_guard, f"{group}_mode", "block")
    normalized = str(value or "block").strip().lower()
    return normalized if normalized in {"block", "downsize", "observe"} else "block"


def _portfolio_remaining_margin(config: AppConfig, risk_state: RiskState | None) -> float | None:
    if risk_state is None:
        return None
    cap = _portfolio_margin_cap(config)
    if cap <= 0:
        return None
    return cap - risk_state.total_initial_margin_usdt


def _portfolio_margin_cap(config: AppConfig) -> float:
    absolute = _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")) or 0.0
    capital = _float_or_none(config.get("BFA_ACCOUNT_CAPITAL_USDT")) or 0.0
    fraction = _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")) or 0.0
    fraction_cap = capital * fraction
    positive = [value for value in (absolute, fraction_cap) if value > 0]
    return min(positive) if positive else 0.0


def _feature_volatility(features: Mapping[str, Any]) -> float | None:
    return _first_float(
        features.get("atr_percent"),
        features.get("realized_volatility_percent"),
        features.get("kline_range_mean_percent"),
        features.get("kline_range_percent"),
        features.get("kline_range_max_percent"),
    )


def _positive_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
