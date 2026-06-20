"""Deterministic multi-factor trade setup generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.ai.schema import AiTradeDecision, DecisionValidationResult, RiskLimits
from bfa.event_store.store import EventStore


@dataclass(frozen=True)
class FactorScore:
    name: str
    value: float | None
    score: float
    weight: float
    direction: str = "long"
    reasons: list[str] = field(default_factory=list)

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "score": self.score,
            "weight": self.weight,
            "weighted_score": self.weighted_score,
            "direction": self.direction,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TradeSetup:
    symbol: str
    decision: str
    side: str
    confidence: float
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    notional_usdt: float | None
    hold_time_minutes: int | None
    factor_scores: list[FactorScore]
    long_score: float
    short_score: float
    edge_score: float
    regime: str
    risk_reward_ratio: float | None
    stop_distance_percent: float | None
    target_distance_percent: float | None
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision": self.decision,
            "side": self.side,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "notional_usdt": self.notional_usdt,
            "hold_time_minutes": self.hold_time_minutes,
            "factor_scores": [factor.to_dict() for factor in self.factor_scores],
            "long_score": self.long_score,
            "short_score": self.short_score,
            "edge_score": self.edge_score,
            "regime": self.regime,
            "risk_reward_ratio": self.risk_reward_ratio,
            "stop_distance_percent": self.stop_distance_percent,
            "target_distance_percent": self.target_distance_percent,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }

    def to_decision_payload(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "side": self.side,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "notional_usdt": self.notional_usdt,
            "hold_time_minutes": self.hold_time_minutes,
            "reasons": list(self.reasons),
        }

    def to_validation(self) -> DecisionValidationResult:
        return DecisionValidationResult(
            accepted=self.decision == "trade",
            decision=AiTradeDecision(
                decision=self.decision,
                side=self.side,
                confidence=self.confidence,
                entry_price=self.entry_price,
                stop_price=self.stop_price,
                target_price=self.target_price,
                notional_usdt=self.notional_usdt,
                hold_time_minutes=self.hold_time_minutes,
                reasons=list(self.reasons),
            ),
            validation_errors=[] if self.decision == "trade" else ["quant_setup_pass"],
            validation_warnings=list(self.warnings),
        )


def build_trade_setup(
    candidate: Mapping[str, Any] | Any,
    *,
    risk_limits: RiskLimits,
) -> TradeSetup:
    payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
    symbol = str(payload.get("symbol", "")).upper()
    features = _mapping(payload.get("features"))
    factor_scores = _factor_scores(payload, features)
    long_score, short_score = _direction_scores(factor_scores)
    side = _select_side(long_score, short_score)
    edge = max(long_score, short_score) - min(long_score, short_score)
    reference = _positive_float(features.get("reference_price"))
    volatility = _volatility_percent(features)
    regime = _regime(volatility, features)
    warnings: list[str] = []

    if side == "flat" or reference is None:
        if reference is None:
            warnings.append("missing_reference_price")
        if side == "flat":
            warnings.append("factor_edge_too_small")
        return TradeSetup(
            symbol=symbol,
            decision="pass",
            side="flat",
            confidence=round(_confidence(edge, factor_scores), 4),
            entry_price=None,
            stop_price=None,
            target_price=None,
            notional_usdt=None,
            hold_time_minutes=None,
            factor_scores=factor_scores,
            long_score=round(long_score, 4),
            short_score=round(short_score, 4),
            edge_score=round(edge, 4),
            regime=regime,
            risk_reward_ratio=None,
            stop_distance_percent=None,
            target_distance_percent=None,
            reasons=_dedupe(["quant_setup_pass", *warnings]),
            warnings=warnings,
        )

    entry = _entry_price(reference, side, volatility)
    stop_distance = _stop_distance_percent(volatility, features, side)
    target_distance = _target_distance_percent(stop_distance, edge, volatility)
    stop, target = _stop_target(entry, side, stop_distance, target_distance)
    notional, sizing_warnings = _setup_notional(
        entry_price=entry,
        stop_price=stop,
        risk_limits=risk_limits,
        features=features,
        edge=edge,
    )
    warnings.extend(sizing_warnings)
    reasons = _setup_reasons(side, factor_scores, regime, warnings)
    decision = "trade"
    if notional is None:
        decision = "pass"
        reasons = _dedupe([*reasons, "notional_not_executable"])
    if edge < 10.0:
        decision = "pass"
        reasons = _dedupe([*reasons, "factor_edge_too_small"])
    if _high_crowding(features, side):
        warnings.append("crowding_risk")
        reasons = _dedupe([*reasons, "crowding_risk"])
    confidence = _confidence(edge, factor_scores)
    if decision == "pass":
        return TradeSetup(
            symbol=symbol,
            decision="pass",
            side="flat",
            confidence=round(confidence, 4),
            entry_price=None,
            stop_price=None,
            target_price=None,
            notional_usdt=None,
            hold_time_minutes=None,
            factor_scores=factor_scores,
            long_score=round(long_score, 4),
            short_score=round(short_score, 4),
            edge_score=round(edge, 4),
            regime=regime,
            risk_reward_ratio=None,
            stop_distance_percent=None,
            target_distance_percent=None,
            reasons=reasons,
            warnings=_dedupe(warnings),
        )

    return TradeSetup(
        symbol=symbol,
        decision="trade",
        side=side,
        confidence=round(confidence, 4),
        entry_price=round(entry, 8),
        stop_price=round(stop, 8),
        target_price=round(target, 8),
        notional_usdt=round(notional, 8),
        hold_time_minutes=_hold_minutes(edge, volatility),
        factor_scores=factor_scores,
        long_score=round(long_score, 4),
        short_score=round(short_score, 4),
        edge_score=round(edge, 4),
        regime=regime,
        risk_reward_ratio=round(target_distance / stop_distance, 4),
        stop_distance_percent=round(stop_distance, 4),
        target_distance_percent=round(target_distance, 4),
        reasons=reasons,
        warnings=_dedupe(warnings),
    )


def persist_trade_setup(
    store: EventStore,
    *,
    setup: TradeSetup,
    candidate: Mapping[str, Any] | Any,
    decided_at: str,
) -> int:
    candidate_payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
    return store.insert_artifact(
        "trade_setups",
        occurred_at=decided_at,
        source="strategy.quant_setup",
        symbol=setup.symbol,
        ref_id=f"trade_setup:{setup.symbol}:{decided_at}",
        payload={
            "setup": setup.to_dict(),
            "candidate": candidate_payload,
        },
        event_type="trade_setup",
    )


def _factor_scores(payload: Mapping[str, Any], features: Mapping[str, Any]) -> list[FactorScore]:
    return [
        _momentum_factor(features),
        _liquidity_factor(features),
        _oi_factor(features),
        _taker_flow_factor(features),
        _funding_factor(features),
        _volatility_factor(features),
        _narrative_factor(payload, features),
        _tradability_factor(features),
    ]


def _momentum_factor(features: Mapping[str, Any]) -> FactorScore:
    change_24h = _float(features.get("price_change_percent"))
    kline = _float(features.get("kline_momentum_percent"))
    micro = _float(features.get("kline_micro_momentum_percent"))
    close_position = _float(features.get("kline_close_position_percent"))
    values = [value for value in (change_24h, kline, micro) if value is not None]
    if not values:
        return FactorScore("momentum", None, 0.0, 1.5, reasons=["missing_momentum"])
    score = _clip(sum(values) * 3.0, -30.0, 30.0)
    reasons: list[str] = []
    if change_24h is not None and abs(change_24h) >= 3:
        reasons.append("24h_momentum")
    if kline is not None and abs(kline) >= 0.6:
        reasons.append("kline_window_momentum")
    if close_position is not None:
        if close_position >= 70:
            score += 4.0
            reasons.append("close_near_range_high")
        elif close_position <= 30:
            score -= 4.0
            reasons.append("close_near_range_low")
    return FactorScore("momentum", kline if kline is not None else change_24h, _clip(score, -35.0, 35.0), 1.5, reasons=reasons)


def _liquidity_factor(features: Mapping[str, Any]) -> FactorScore:
    quote_volume = _float(features.get("quote_volume"))
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    if quote_volume is None:
        return FactorScore("liquidity", None, -8.0, 0.9, reasons=["missing_liquidity"])
    score = min(quote_volume / 2_000_000.0, 20.0)
    reasons = ["liquidity_ok"] if quote_volume >= 5_000_000 else ["thin_liquidity"]
    if volume_change is not None and volume_change > 20:
        score += min(volume_change / 10.0, 8.0)
        reasons.append("volume_impulse")
    return FactorScore("liquidity", quote_volume, _clip(score, -10.0, 28.0), 0.9, direction="both", reasons=reasons)


def _oi_factor(features: Mapping[str, Any]) -> FactorScore:
    value = _float(features.get("open_interest_value")) or _float(features.get("open_interest"))
    if value is None:
        return FactorScore("open_interest", None, 0.0, 1.0, direction="both", reasons=["missing_open_interest"])
    scale = 1_000_000.0 if _float(features.get("open_interest_value")) is not None else 100_000.0
    score = min(value / scale, 20.0)
    return FactorScore("open_interest", value, score, 1.0, direction="both", reasons=["oi_confirmation"])


def _taker_flow_factor(features: Mapping[str, Any]) -> FactorScore:
    ratio = _float(features.get("taker_buy_sell_ratio"))
    change = _float(features.get("taker_buy_sell_ratio_change"))
    if ratio is None:
        return FactorScore("taker_flow", None, 0.0, 1.4, reasons=["missing_taker_flow"])
    score = _clip((ratio - 1.0) * 45.0, -25.0, 25.0)
    reasons: list[str] = []
    if ratio >= 1.08:
        reasons.append("taker_buy_bias")
    elif ratio <= 0.92:
        reasons.append("taker_sell_bias")
    if change is not None and abs(change) >= 0.05:
        score += _clip(change * 20.0, -5.0, 5.0)
        reasons.append("taker_flow_acceleration")
    return FactorScore("taker_flow", ratio, _clip(score, -30.0, 30.0), 1.4, reasons=reasons)


def _funding_factor(features: Mapping[str, Any]) -> FactorScore:
    funding = _float(features.get("funding_rate"))
    if funding is None:
        return FactorScore("funding", None, 0.0, 0.7, reasons=["missing_funding"])
    score = _clip(-funding * 20000.0, -10.0, 10.0)
    reasons = ["funding_supports_long"] if score > 1 else ["funding_supports_short"] if score < -1 else ["funding_neutral"]
    return FactorScore("funding", funding, score, 0.7, reasons=reasons)


def _volatility_factor(features: Mapping[str, Any]) -> FactorScore:
    volatility = _volatility_percent(features)
    if volatility is None:
        return FactorScore("volatility", None, -5.0, 0.9, direction="both", reasons=["missing_volatility"])
    if volatility < 0.25:
        return FactorScore("volatility", volatility, -6.0, 0.9, direction="both", reasons=["range_too_compressed"])
    if volatility <= 3.0:
        return FactorScore("volatility", volatility, 10.0, 0.9, direction="both", reasons=["volatility_tradeable"])
    if volatility <= 8.0:
        return FactorScore("volatility", volatility, 2.0, 0.9, direction="both", reasons=["volatility_elevated"])
    return FactorScore("volatility", volatility, -12.0, 0.9, direction="both", reasons=["volatility_excessive"])


def _narrative_factor(payload: Mapping[str, Any], features: Mapping[str, Any]) -> FactorScore:
    mentions = _float(features.get("mention_count")) or 0.0
    sources = _float(features.get("source_count")) or 0.0
    engagement = _float(features.get("engagement_score")) or 0.0
    base = min(mentions * 5.0 + sources * 4.0 + engagement / 50.0, 18.0)
    reasons: list[str] = []
    reason_codes = [str(item) for item in payload.get("reason_codes", []) if str(item)]
    if "market_derived" in " ".join(reason_codes):
        reasons.append("market_derived_narrative")
    if mentions > 0:
        reasons.append("narrative_heat")
    if sources > 1:
        reasons.append("source_diversity")
    return FactorScore("narrative", mentions, base, 0.8, direction="both", reasons=reasons or ["no_external_narrative"])


def _tradability_factor(features: Mapping[str, Any]) -> FactorScore:
    min_executable = _positive_float(features.get("min_executable_notional"))
    if min_executable is None:
        return FactorScore("tradability", None, -4.0, 0.6, direction="both", reasons=["missing_min_executable_notional"])
    score = 8.0 if min_executable <= 10.0 else 3.0 if min_executable <= 25.0 else -8.0
    return FactorScore("tradability", min_executable, score, 0.6, direction="both", reasons=["pilot_tradable"])


def _direction_scores(factors: list[FactorScore]) -> tuple[float, float]:
    long_score = 0.0
    short_score = 0.0
    for factor in factors:
        weighted = factor.weighted_score
        if factor.direction == "both":
            long_score += weighted
            short_score += weighted
        elif weighted >= 0:
            long_score += weighted
        else:
            short_score += abs(weighted)
    return long_score, short_score


def _select_side(long_score: float, short_score: float) -> str:
    edge = abs(long_score - short_score)
    if edge < 10.0:
        return "flat"
    return "long" if long_score > short_score else "short"


def _entry_price(reference: float, side: str, volatility: float | None) -> float:
    slippage_buffer = min(max((volatility or 1.0) * 0.015, 0.0005), 0.0015)
    if side == "long":
        return reference * (1.0 + slippage_buffer)
    return reference * (1.0 - slippage_buffer)


def _stop_distance_percent(volatility: float | None, features: Mapping[str, Any], side: str) -> float:
    base = max((volatility or 1.0) * 0.9, 0.65)
    close_position = _float(features.get("kline_close_position_percent"))
    if side == "long" and close_position is not None and close_position >= 80:
        base *= 0.9
    if side == "short" and close_position is not None and close_position <= 20:
        base *= 0.9
    return min(max(base, 0.45), 3.2)


def _target_distance_percent(stop_distance: float, edge: float, volatility: float | None) -> float:
    reward_multiple = 1.35 + min(edge / 60.0, 0.65)
    target = stop_distance * reward_multiple
    if volatility is not None:
        target = min(target, max(volatility * 1.8, stop_distance * 1.25))
    return min(max(target, stop_distance * 1.2), 6.0)


def _stop_target(entry: float, side: str, stop_distance: float, target_distance: float) -> tuple[float, float]:
    stop_fraction = stop_distance / 100.0
    target_fraction = target_distance / 100.0
    if side == "long":
        return entry * (1.0 - stop_fraction), entry * (1.0 + target_fraction)
    return entry * (1.0 + stop_fraction), entry * (1.0 - target_fraction)


def _setup_notional(
    *,
    entry_price: float,
    stop_price: float,
    risk_limits: RiskLimits,
    features: Mapping[str, Any],
    edge: float,
) -> tuple[float | None, list[str]]:
    stop_fraction = abs(entry_price - stop_price) / entry_price
    warnings: list[str] = []
    if stop_fraction <= 0:
        return None, ["invalid_stop_distance"]
    risk_notional = risk_limits.max_risk_per_trade_usdt / stop_fraction
    edge_fraction = min(max(edge / 40.0, 0.35), 1.0)
    max_notional = min(risk_limits.max_position_notional_usdt, risk_notional)
    notional = max_notional * edge_fraction
    min_executable = _positive_float(features.get("min_executable_notional"))
    if min_executable is not None and notional < min_executable:
        if min_executable <= max_notional:
            warnings.append("raised_to_min_executable_notional")
            notional = min_executable
        else:
            return None, ["min_executable_exceeds_risk_sized_notional"]
    if notional <= 0:
        return None, ["notional_not_positive"]
    return min(notional, risk_limits.max_position_notional_usdt), warnings


def _setup_reasons(
    side: str,
    factors: list[FactorScore],
    regime: str,
    warnings: list[str],
) -> list[str]:
    reasons = [f"quant_{side}_setup", f"regime:{regime}"]
    for factor in factors:
        if abs(factor.weighted_score) >= 4.0:
            reasons.extend(factor.reasons)
    reasons.extend(warnings)
    return _dedupe(reasons)


def _hold_minutes(edge: float, volatility: float | None) -> int:
    if volatility is not None and volatility >= 3.0:
        return 10
    if edge >= 35:
        return 30
    return 15


def _confidence(edge: float, factors: list[FactorScore]) -> float:
    non_missing = sum(1 for factor in factors if not any(reason.startswith("missing_") for reason in factor.reasons))
    coverage = non_missing / len(factors) if factors else 0.0
    return min(0.45 + edge / 120.0 + coverage * 0.18, 0.88)


def _regime(volatility: float | None, features: Mapping[str, Any]) -> str:
    momentum = abs(_float(features.get("kline_momentum_percent")) or _float(features.get("price_change_percent")) or 0.0)
    if volatility is None:
        return "unknown"
    if volatility >= 5.0:
        return "high_volatility"
    if momentum >= 2.5 and volatility >= 0.5:
        return "momentum_expansion"
    if volatility < 0.35:
        return "compressed"
    return "normal"


def _volatility_percent(features: Mapping[str, Any]) -> float | None:
    return (
        _float(features.get("kline_range_mean_percent"))
        or _float(features.get("kline_range_percent"))
        or _float(features.get("kline_range_max_percent"))
    )


def _high_crowding(features: Mapping[str, Any], side: str) -> bool:
    funding = _float(features.get("funding_rate")) or 0.0
    taker = _float(features.get("taker_buy_sell_ratio")) or 1.0
    if side == "long":
        return funding > 0.0008 and taker > 1.8
    return funding < -0.0008 and taker < 0.55


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any) -> float | None:
    parsed = _float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
