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
    price_basis: dict[str, Any] = field(default_factory=dict)
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
            "price_basis": dict(self.price_basis),
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


@dataclass(frozen=True)
class TradeSetupProfile:
    name: str = "standard"
    min_edge: float = 10.0
    min_confidence: float = 0.0
    min_risk_reward: float = 1.2
    max_stop_distance_percent: float = 4.2
    min_indicator_sample_size: int = 0
    require_trend_alignment: bool = False
    require_rsi_not_extreme: bool = False
    max_notional_fraction: float = 1.0
    stop_distance_multiplier: float = 1.0
    target_distance_multiplier: float = 1.0
    disabled_sides: tuple[str, ...] = ()
    excluded_symbols: tuple[str, ...] = ()


STANDARD_SETUP_PROFILE = TradeSetupProfile()


def build_trade_setup(
    candidate: Mapping[str, Any] | Any,
    *,
    risk_limits: RiskLimits,
    profile: TradeSetupProfile | Mapping[str, Any] | None = None,
) -> TradeSetup:
    setup_profile = _setup_profile(profile)
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
            price_basis={},
            reasons=_dedupe(["quant_setup_pass", *warnings]),
            warnings=warnings,
        )

    entry = _entry_price(reference, side, volatility)
    stop_distance, stop_basis = _stop_distance_percent(entry, volatility, features, side, setup_profile)
    target_distance, target_basis = _target_distance_percent(
        entry,
        stop_distance,
        edge,
        volatility,
        features,
        side,
        setup_profile,
    )
    stop, target = _stop_target(entry, side, stop_distance, target_distance)
    price_basis = _price_basis(
        reference=reference,
        entry=entry,
        stop=stop,
        target=target,
        side=side,
        features=features,
        stop_basis=stop_basis,
        target_basis=target_basis,
        profile=setup_profile,
    )
    notional, sizing_warnings = _setup_notional(
        entry_price=entry,
        stop_price=stop,
        risk_limits=risk_limits,
        features=features,
        edge=edge,
        profile=setup_profile,
    )
    warnings.extend(sizing_warnings)
    reasons = _setup_reasons(side, factor_scores, regime, warnings)
    decision = "trade"
    if notional is None:
        decision = "pass"
        reasons = _dedupe([*reasons, "notional_not_executable"])
    confidence = _confidence(edge, factor_scores)
    if edge < setup_profile.min_edge:
        decision = "pass"
        reasons = _dedupe([*reasons, "factor_edge_too_small"])
    if confidence < setup_profile.min_confidence:
        decision = "pass"
        reasons = _dedupe([*reasons, "confidence_below_profile_min"])
    if target_distance / stop_distance < setup_profile.min_risk_reward:
        decision = "pass"
        reasons = _dedupe([*reasons, "risk_reward_below_profile_min"])
    profile_rejections = _profile_rejections(symbol, features, side, setup_profile)
    if profile_rejections:
        decision = "pass"
        reasons = _dedupe([*reasons, *profile_rejections])
    if _high_crowding(features, side):
        warnings.append("crowding_risk")
        reasons = _dedupe([*reasons, "crowding_risk"])
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
            price_basis=price_basis,
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
        price_basis=price_basis,
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
        _trend_factor(features),
        _rsi_factor(features),
        _volume_impulse_factor(features),
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


def _trend_factor(features: Mapping[str, Any]) -> FactorScore:
    spread = _float(features.get("ema_spread_percent"))
    reference = _float(features.get("reference_price"))
    vwap = _float(features.get("vwap"))
    if spread is None and reference is None:
        return FactorScore("trend_structure", None, 0.0, 1.2, reasons=["missing_trend_structure"])
    score = _clip((spread or 0.0) * 12.0, -22.0, 22.0)
    reasons: list[str] = []
    if spread is not None:
        if spread >= 0.15:
            reasons.append("ema_trend_up")
        elif spread <= -0.15:
            reasons.append("ema_trend_down")
        else:
            reasons.append("ema_trend_flat")
    if reference is not None and vwap is not None and vwap > 0:
        vwap_delta = ((reference - vwap) / vwap) * 100.0
        score += _clip(vwap_delta * 3.0, -8.0, 8.0)
        if vwap_delta >= 0.2:
            reasons.append("price_above_vwap")
        elif vwap_delta <= -0.2:
            reasons.append("price_below_vwap")
    return FactorScore("trend_structure", spread, _clip(score, -26.0, 26.0), 1.2, reasons=reasons)


def _rsi_factor(features: Mapping[str, Any]) -> FactorScore:
    rsi = _float(features.get("rsi"))
    if rsi is None:
        return FactorScore("rsi_regime", None, 0.0, 0.8, reasons=["missing_rsi"])
    score = _clip((rsi - 50.0) * 0.55, -18.0, 18.0)
    reasons: list[str] = []
    if 45 <= rsi <= 65:
        reasons.append("rsi_balanced")
    elif 65 < rsi <= 80:
        reasons.append("rsi_bullish_momentum")
    elif 20 <= rsi < 35:
        reasons.append("rsi_bearish_momentum")
    elif rsi > 80:
        score -= 8.0
        reasons.append("rsi_overbought_caution")
    elif rsi < 20:
        score += 8.0
        reasons.append("rsi_oversold_caution")
    return FactorScore("rsi_regime", rsi, _clip(score, -20.0, 20.0), 0.8, reasons=reasons)


def _volume_impulse_factor(features: Mapping[str, Any]) -> FactorScore:
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    momentum = _float(features.get("kline_micro_momentum_percent")) or _float(features.get("kline_momentum_percent"))
    if volume_change is None or momentum is None:
        return FactorScore("volume_impulse", None, 0.0, 0.8, reasons=["missing_volume_impulse"])
    impulse = min(max(volume_change, -50.0), 120.0) / 6.0
    direction = 1.0 if momentum >= 0 else -1.0
    score = impulse * direction
    reasons = ["volume_expands_with_move"] if volume_change >= 20 else ["volume_neutral"]
    if volume_change < -20:
        reasons = ["volume_fades_move"]
        score *= 0.5
    return FactorScore("volume_impulse", volume_change, _clip(score, -16.0, 16.0), 0.8, reasons=reasons)


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


def _stop_distance_percent(
    entry: float,
    volatility: float | None,
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    atr = _float(features.get("atr_percent"))
    base_volatility = atr or volatility or 1.0
    base = max(base_volatility * 1.15, 0.65)
    close_position = _float(features.get("kline_close_position_percent"))
    if side == "long" and close_position is not None and close_position >= 80:
        base *= 0.9
    if side == "short" and close_position is not None and close_position <= 20:
        base *= 0.9
    structure_price = _positive_float(features.get("support_price" if side == "long" else "resistance_price"))
    structure_distance: float | None = None
    if structure_price is not None:
        if side == "long" and structure_price < entry:
            structure_distance = ((entry - structure_price) / entry) * 100.0 + max(base_volatility * 0.18, 0.08)
        if side == "short" and structure_price > entry:
            structure_distance = ((structure_price - entry) / entry) * 100.0 + max(base_volatility * 0.18, 0.08)
    if structure_distance is not None:
        stop_distance = max(base, min(structure_distance, base * 2.1))
        anchor = "support_price" if side == "long" else "resistance_price"
    else:
        stop_distance = base
        anchor = "atr_volatility"
    stop_distance *= max(profile.stop_distance_multiplier, 0.1)
    stop_distance = min(max(stop_distance, 0.45), profile.max_stop_distance_percent)
    return stop_distance, {
        "anchor": anchor,
        "atr_percent": atr,
        "volatility_percent": volatility,
        "structure_distance_percent": structure_distance,
        "raw_stop_distance_percent": stop_distance,
        "profile": profile.name,
    }


def _target_distance_percent(
    entry: float,
    stop_distance: float,
    edge: float,
    volatility: float | None,
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    reward_multiple = 1.35 + min(edge / 60.0, 0.65)
    trend = abs(_float(features.get("ema_spread_percent")) or 0.0)
    if trend >= 0.35:
        reward_multiple += 0.15
    target = stop_distance * reward_multiple
    if volatility is not None:
        target = min(target, max(volatility * 2.0, stop_distance * 1.25))
    structure_price = _positive_float(features.get("resistance_price" if side == "long" else "support_price"))
    structure_distance: float | None = None
    if structure_price is not None:
        if side == "long" and structure_price > entry:
            structure_distance = ((structure_price - entry) / entry) * 100.0
        if side == "short" and structure_price < entry:
            structure_distance = ((entry - structure_price) / entry) * 100.0
    anchor = "edge_reward_multiple"
    if structure_distance is not None and structure_distance >= stop_distance * 1.2:
        target = min(max(target, structure_distance), stop_distance * 2.4)
        anchor = "nearest_structure_with_min_rr"
    target *= max(profile.target_distance_multiplier, 0.1)
    target = min(max(target, stop_distance * profile.min_risk_reward), 7.0)
    return target, {
        "anchor": anchor,
        "reward_multiple": reward_multiple,
        "structure_distance_percent": structure_distance,
        "raw_target_distance_percent": target,
        "profile": profile.name,
    }


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
    profile: TradeSetupProfile,
) -> tuple[float | None, list[str]]:
    stop_fraction = abs(entry_price - stop_price) / entry_price
    warnings: list[str] = []
    if stop_fraction <= 0:
        return None, ["invalid_stop_distance"]
    risk_notional = risk_limits.max_risk_per_trade_usdt / stop_fraction
    edge_fraction = min(max(edge / 40.0, 0.35), 1.0)
    max_notional = min(risk_limits.max_position_notional_usdt, risk_notional)
    notional = max_notional * edge_fraction
    notional *= min(max(profile.max_notional_fraction, 0.0), 1.0)
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
    trend = abs(_float(features.get("ema_spread_percent")) or 0.0)
    if volatility is None:
        return "unknown"
    if volatility >= 5.0:
        return "high_volatility"
    if trend >= 0.5 and momentum >= 1.0:
        return "trend_expansion"
    if momentum >= 2.5 and volatility >= 0.5:
        return "momentum_expansion"
    if volatility < 0.35:
        return "compressed"
    return "normal"


def _volatility_percent(features: Mapping[str, Any]) -> float | None:
    return (
        _float(features.get("atr_percent"))
        or _float(features.get("kline_range_mean_percent"))
        or _float(features.get("kline_range_percent"))
        or _float(features.get("kline_range_max_percent"))
    )


def _price_basis(
    *,
    reference: float,
    entry: float,
    stop: float,
    target: float,
    side: str,
    features: Mapping[str, Any],
    stop_basis: Mapping[str, Any],
    target_basis: Mapping[str, Any],
    profile: TradeSetupProfile,
) -> dict[str, Any]:
    return {
        "model": "expected_market_entry_structure_stop_target_v1",
        "profile": profile.name,
        "side": side,
        "reference_price": reference,
        "entry_price": round(entry, 8),
        "stop_price": round(stop, 8),
        "target_price": round(target, 8),
        "support_price": _float(features.get("support_price")),
        "resistance_price": _float(features.get("resistance_price")),
        "vwap": _float(features.get("vwap")),
        "atr_percent": _float(features.get("atr_percent")),
        "ema_fast": _float(features.get("ema_fast")),
        "ema_slow": _float(features.get("ema_slow")),
        "ema_spread_percent": _float(features.get("ema_spread_percent")),
        "rsi": _float(features.get("rsi")),
        "indicator_sample_size": _float(features.get("indicator_sample_size")),
        "stop_basis": dict(stop_basis),
        "target_basis": dict(target_basis),
    }


def _profile_rejections(symbol: str, features: Mapping[str, Any], side: str, profile: TradeSetupProfile) -> list[str]:
    rejections: list[str] = []
    if side.lower() in {item.lower() for item in profile.disabled_sides}:
        rejections.append("side_disabled_by_profile")
    if symbol.upper() in {item.upper() for item in profile.excluded_symbols}:
        rejections.append("symbol_excluded_by_profile")
    sample_size = int(_float(features.get("indicator_sample_size")) or 0)
    if sample_size < profile.min_indicator_sample_size:
        rejections.append("indicator_sample_below_profile_min")
    trend = _float(features.get("ema_spread_percent"))
    if profile.require_trend_alignment and trend is not None:
        if side == "long" and trend <= 0:
            rejections.append("trend_not_aligned")
        if side == "short" and trend >= 0:
            rejections.append("trend_not_aligned")
    rsi = _float(features.get("rsi"))
    if profile.require_rsi_not_extreme and rsi is not None:
        if side == "long" and rsi >= 78:
            rejections.append("rsi_extreme_for_long")
        if side == "short" and rsi <= 22:
            rejections.append("rsi_extreme_for_short")
    return _dedupe(rejections)


def _setup_profile(profile: TradeSetupProfile | Mapping[str, Any] | None) -> TradeSetupProfile:
    if profile is None:
        return STANDARD_SETUP_PROFILE
    if isinstance(profile, TradeSetupProfile):
        return profile
    if isinstance(profile, Mapping):
        values = {key: profile[key] for key in TradeSetupProfile.__dataclass_fields__ if key in profile}
        if "disabled_sides" in values:
            values["disabled_sides"] = tuple(str(item).lower() for item in _sequence(values["disabled_sides"]))
        if "excluded_symbols" in values:
            values["excluded_symbols"] = tuple(str(item).upper() for item in _sequence(values["excluded_symbols"]))
        return TradeSetupProfile(**values)
    return STANDARD_SETUP_PROFILE


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None:
        return []
    return [value]


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
