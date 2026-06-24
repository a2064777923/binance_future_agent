"""Deterministic regime routing for live strategy candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from bfa.strategy.candidates import CandidateSignal


TREND = "TREND"
RANGE = "RANGE"
CHOP = "CHOP"

TREND_LEG = "trend"
MICRO_GRID_LEG = "micro_grid"
RANGE_REVERSION_LEG = "range_reversion"

ALLOW = "allow"
SKIP_CHOP = "skip_chop"
SKIP_LEG_MISMATCH = "skip_leg_mismatch"
SKIP_LOW_CONFIDENCE = "skip_low_confidence"

RANGE_MIN_WIDTH_PERCENT = 0.18
RANGE_MAX_WIDTH_PERCENT = 3.4
RANGE_MAX_EMA_SPREAD_PERCENT = 0.42
RANGE_MAX_DRIFT_TO_WIDTH = 0.9
TREND_MIN_PATH_EFFICIENCY = 0.50
RANGE_MAX_PATH_EFFICIENCY = 0.35
RANGE_MIN_EDGE_ALTERNATIONS = 2
MIN_CONFIDENCE = 0.55


@dataclass(frozen=True)
class RegimeDecision:
    label: str
    confidence: float
    reason_codes: list[str]
    allowed_strategy_legs: list[str]
    route_decision: str
    route_shadow_only: bool
    diagnostics: dict[str, Any]

    def to_feature_payload(self) -> dict[str, Any]:
        return {
            "regime_label": self.label,
            "regime_confidence": round(self.confidence, 4),
            "regime_reason_codes": list(self.reason_codes),
            "allowed_strategy_legs": list(self.allowed_strategy_legs),
            "route_decision": self.route_decision,
            "route_shadow_only": self.route_shadow_only,
            "regime_diagnostics": dict(self.diagnostics),
        }


def annotate_candidates(
    normal_candidates: list[CandidateSignal],
    micro_candidates: list[CandidateSignal],
    *,
    shadow_only: bool = True,
) -> tuple[list[CandidateSignal], list[CandidateSignal]]:
    return (
        [annotate_candidate(candidate, shadow_only=shadow_only) for candidate in normal_candidates],
        [annotate_candidate(candidate, shadow_only=shadow_only) for candidate in micro_candidates],
    )


def annotate_candidate(candidate: CandidateSignal, *, shadow_only: bool = True) -> CandidateSignal:
    features = dict(candidate.features or {})
    strategy_leg = candidate_strategy_leg(candidate)
    features.setdefault("strategy_leg", strategy_leg)
    decision = classify_regime(features, strategy_leg=strategy_leg, shadow_only=shadow_only)
    features.update(decision.to_feature_payload())
    return replace(candidate, features=features)


def classify_regime(
    features: Mapping[str, Any],
    *,
    strategy_leg: str | None = None,
    shadow_only: bool = True,
) -> RegimeDecision:
    leg = _normalize_strategy_leg(strategy_leg or str(features.get("strategy_leg") or ""))
    diagnostics = _diagnostics(features)
    trend_signal, trend_reasons, trend_score = _trend_evidence(diagnostics)
    range_signal, range_reasons, range_score = _range_evidence(diagnostics)
    chop_reasons = _chop_reasons(diagnostics, trend_signal=trend_signal, range_signal=range_signal)

    if chop_reasons:
        label = CHOP
        confidence = _clamp(0.58 + 0.06 * len(chop_reasons), 0.58, 0.88)
        reasons = chop_reasons
    elif trend_signal and not range_signal:
        label = TREND
        confidence = _clamp(trend_score, 0.0, 0.95)
        reasons = trend_reasons
    elif range_signal and not trend_signal:
        label = RANGE
        confidence = _clamp(range_score, 0.0, 0.95)
        reasons = range_reasons
    else:
        label = CHOP
        confidence = 0.5
        reasons = ["regime_insufficient_evidence"]

    if label != CHOP and confidence < MIN_CONFIDENCE:
        label = CHOP
        reasons = _dedupe([*reasons, "regime_low_confidence"])

    allowed = allowed_legs_for_regime(label)
    route_decision = route_decision_for_leg(label, leg, allowed, confidence)
    return RegimeDecision(
        label=label,
        confidence=round(confidence, 4),
        reason_codes=_dedupe(reasons),
        allowed_strategy_legs=allowed,
        route_decision=route_decision,
        route_shadow_only=bool(shadow_only),
        diagnostics=diagnostics,
    )


def allowed_legs_for_regime(label: str) -> list[str]:
    normalized = str(label or "").upper()
    if normalized == TREND:
        return [TREND_LEG]
    if normalized == RANGE:
        return [MICRO_GRID_LEG, RANGE_REVERSION_LEG]
    return []


def route_decision_for_leg(label: str, strategy_leg: str, allowed: list[str], confidence: float) -> str:
    if str(label or "").upper() == CHOP:
        return SKIP_CHOP if confidence >= MIN_CONFIDENCE else SKIP_LOW_CONFIDENCE
    return ALLOW if _normalize_strategy_leg(strategy_leg) in allowed else SKIP_LEG_MISMATCH


def route_allows_candidate(candidate: Any) -> bool:
    features = getattr(candidate, "features", {}) or {}
    if not isinstance(features, Mapping):
        return True
    if "route_decision" not in features:
        return True
    return str(features.get("route_decision") or "") == ALLOW


def candidate_strategy_leg(candidate: Any) -> str:
    features = getattr(candidate, "features", {}) or {}
    if isinstance(features, Mapping):
        explicit = _normalize_strategy_leg(str(features.get("strategy_leg") or ""))
        if explicit:
            return explicit
        source = str(features.get("strategy_source") or features.get("setup_signal_mode") or "").lower()
        if "micro_grid" in source:
            return MICRO_GRID_LEG
        if "range" in source or "reversion" in source:
            return RANGE_REVERSION_LEG
    for reason in getattr(candidate, "reason_codes", []) or []:
        text = str(reason)
        if text.startswith("strategy_leg:"):
            return _normalize_strategy_leg(text.split(":", 1)[1]) or TREND_LEG
        if text.startswith("signal_mode:orderly_range") or "orderly_range_reversion" in text:
            return RANGE_REVERSION_LEG
    return TREND_LEG


def regime_route_summary(candidates: list[Any]) -> dict[str, Any]:
    label_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    leg_counts: dict[str, int] = {}
    symbols: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        features = getattr(candidate, "features", {}) or {}
        if not isinstance(features, Mapping):
            continue
        label = str(features.get("regime_label") or "UNCLASSIFIED")
        route = str(features.get("route_decision") or "unclassified")
        leg = _normalize_strategy_leg(str(features.get("strategy_leg") or "")) or "unknown"
        label_counts[label] = label_counts.get(label, 0) + 1
        route_counts[route] = route_counts.get(route, 0) + 1
        leg_counts[leg] = leg_counts.get(leg, 0) + 1
        symbol = str(getattr(candidate, "symbol", "") or "").upper()
        if symbol:
            symbols[symbol] = {
                "regime_label": label,
                "regime_confidence": features.get("regime_confidence"),
                "strategy_leg": leg,
                "route_decision": route,
            }
    return {
        "candidate_count": len(candidates),
        "label_counts": dict(sorted(label_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "strategy_leg_counts": dict(sorted(leg_counts.items())),
        "symbols": symbols,
    }


def _diagnostics(features: Mapping[str, Any]) -> dict[str, Any]:
    micro_state = features.get("micro_grid_state")
    if not isinstance(micro_state, Mapping):
        micro_state = {}
    width = _first_float(
        features.get("range_width_percent"),
        micro_state.get("width_percent"),
        features.get("kline_range_percent"),
    )
    stable_width = _first_float(
        features.get("range_stable_width_percent"),
        micro_state.get("stable_width_percent"),
        features.get("kline_range_mean_percent"),
    )
    path_efficiency = _first_float(
        features.get("range_path_efficiency"),
        micro_state.get("path_efficiency"),
    )
    edge_alternations = _first_int(
        features.get("range_edge_alternation_count"),
        micro_state.get("edge_alternation_count"),
    )
    drift_to_width = _first_float(
        features.get("range_drift_to_width"),
        micro_state.get("drift_to_width"),
    )
    ema_spread = _float_or_none(features.get("ema_spread_percent"))
    momentum = _float_or_none(features.get("kline_momentum_percent"))
    micro_momentum = _float_or_none(features.get("kline_micro_momentum_percent"))
    realized_vol = _first_float(features.get("realized_volatility_percent"), features.get("atr_percent"))
    width_expansion_ratio = None
    if width is not None and stable_width is not None and stable_width > 0:
        width_expansion_ratio = width / stable_width
    return {
        "path_efficiency": path_efficiency,
        "edge_alternation_count": edge_alternations,
        "range_width_percent": width,
        "stable_width_percent": stable_width,
        "width_expansion_ratio": width_expansion_ratio,
        "drift_to_width": drift_to_width,
        "ema_spread_percent": ema_spread,
        "kline_momentum_percent": momentum,
        "kline_micro_momentum_percent": micro_momentum,
        "realized_volatility_percent": realized_vol,
    }


def _trend_evidence(diagnostics: Mapping[str, Any]) -> tuple[bool, list[str], float]:
    path = _float_or_none(diagnostics.get("path_efficiency"))
    edge_alternations = _int_or_none(diagnostics.get("edge_alternation_count"))
    ema = _float_or_none(diagnostics.get("ema_spread_percent"))
    momentum = _float_or_none(diagnostics.get("kline_momentum_percent"))
    micro_momentum = _float_or_none(diagnostics.get("kline_micro_momentum_percent"))

    reasons: list[str] = []
    score = 0.52
    path_trend = path is not None and path >= TREND_MIN_PATH_EFFICIENCY
    if path_trend:
        reasons.append("trend_path_efficiency")
        score += min((path - TREND_MIN_PATH_EFFICIENCY) / 0.45, 1.0) * 0.18
    if edge_alternations is not None and edge_alternations <= 1:
        reasons.append("trend_low_edge_alternation")
        score += 0.06

    strong_ema_momentum = False
    if ema is not None and momentum is not None and _same_nonzero_sign(ema, momentum):
        strength = min(abs(ema) / 0.42, 1.0) * 0.09 + min(abs(momentum) / 1.2, 1.0) * 0.12
        score += strength
        if abs(ema) >= 0.08 and abs(momentum) >= 0.45:
            strong_ema_momentum = True
            reasons.append("trend_ema_momentum_aligned")
    if momentum is not None and micro_momentum is not None and _same_nonzero_sign(momentum, micro_momentum):
        if abs(momentum) >= 0.35 and abs(micro_momentum) >= 0.05:
            reasons.append("trend_multi_momentum_aligned")
            score += 0.06

    trend_signal = (path_trend and (edge_alternations is None or edge_alternations <= 1)) or strong_ema_momentum
    return trend_signal, reasons or ["trend_signal"], score


def _range_evidence(diagnostics: Mapping[str, Any]) -> tuple[bool, list[str], float]:
    path = _float_or_none(diagnostics.get("path_efficiency"))
    edge_alternations = _int_or_none(diagnostics.get("edge_alternation_count"))
    width = _float_or_none(diagnostics.get("range_width_percent"))
    ema = abs(_float_or_none(diagnostics.get("ema_spread_percent")) or 0.0)
    drift = _float_or_none(diagnostics.get("drift_to_width"))

    reasons: list[str] = []
    score = 0.52
    path_ok = path is not None and path <= RANGE_MAX_PATH_EFFICIENCY
    if path_ok:
        reasons.append("range_low_path_efficiency")
        score += min((RANGE_MAX_PATH_EFFICIENCY - path) / RANGE_MAX_PATH_EFFICIENCY, 1.0) * 0.14
    edge_ok = edge_alternations is not None and edge_alternations >= RANGE_MIN_EDGE_ALTERNATIONS
    if edge_ok:
        reasons.append("range_edge_alternation")
        score += min((edge_alternations - RANGE_MIN_EDGE_ALTERNATIONS + 1) / 4.0, 1.0) * 0.12
    width_ok = width is not None and RANGE_MIN_WIDTH_PERCENT <= width <= RANGE_MAX_WIDTH_PERCENT
    if width_ok:
        reasons.append("range_tradeable_width")
        score += 0.07
    ema_ok = ema <= RANGE_MAX_EMA_SPREAD_PERCENT
    if ema_ok:
        reasons.append("range_ema_flat_enough")
        score += 0.06
    drift_ok = drift is None or drift <= RANGE_MAX_DRIFT_TO_WIDTH
    if drift_ok:
        reasons.append("range_drift_contained")
        score += 0.04

    return path_ok and edge_ok and width_ok and ema_ok and drift_ok, reasons or ["range_signal"], score


def _chop_reasons(
    diagnostics: Mapping[str, Any],
    *,
    trend_signal: bool,
    range_signal: bool,
) -> list[str]:
    reasons: list[str] = []
    if trend_signal and range_signal:
        reasons.append("regime_conflicting_trend_range_evidence")
    width = _float_or_none(diagnostics.get("range_width_percent"))
    path = _float_or_none(diagnostics.get("path_efficiency"))
    realized_vol = _float_or_none(diagnostics.get("realized_volatility_percent"))
    expansion = _float_or_none(diagnostics.get("width_expansion_ratio"))
    drift = _float_or_none(diagnostics.get("drift_to_width"))
    if expansion is not None and expansion >= 1.75:
        reasons.append("regime_range_width_expanding")
    if width is not None and width > RANGE_MAX_WIDTH_PERCENT * 1.8 and not trend_signal:
        reasons.append("regime_width_extreme_without_direction")
    if realized_vol is not None and realized_vol >= 8.0 and not trend_signal:
        reasons.append("regime_extreme_volatility_without_direction")
    if drift is not None and drift > 1.25 and path is not None and path < TREND_MIN_PATH_EFFICIENCY:
        reasons.append("regime_drift_without_clean_path")
    return reasons


def _normalize_strategy_leg(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"micro", "microgrid", "grid", "scalp", "scalping"}:
        return MICRO_GRID_LEG
    if normalized in {"orderly_range", "range", "range_revert", "range_reversion", "orderly_range_reversion"}:
        return RANGE_REVERSION_LEG
    if normalized in {"trend", "normal", "quant", "quant_setup", ""}:
        return TREND_LEG if normalized else ""
    return normalized


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def _same_nonzero_sign(left: float, right: float) -> bool:
    return (left > 0 and right > 0) or (left < 0 and right < 0)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
