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
            "group": _factor_group(self.name),
            "value": self.value,
            "score": self.score,
            "weight": self.weight,
            "weighted_score": self.weighted_score,
            "direction": self.direction,
            "polarity": _factor_polarity(self),
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
    factor_summary: dict[str, Any] = field(default_factory=dict)
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
            "factor_summary": dict(self.factor_summary),
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
    blocked_factor_reasons: tuple[str, ...] = ()
    blocked_setup_reasons: tuple[str, ...] = ()
    blocked_factor_names: tuple[str, ...] = ()
    require_open_interest: bool = False
    min_quote_volume_usdt: float | None = None
    min_abs_momentum_percent: float | None = None
    min_volume_impulse_percent: float | None = None
    max_volatility_percent: float | None = None
    min_directional_taker_flow_edge: float | None = None
    require_directional_confluence: bool = False
    min_directional_confluence: int = 0
    block_adverse_trend_vwap: bool = False
    block_hot_micro_reversal: bool = False
    block_volume_fade: bool = False
    block_spike_reversal_conflict: bool = False
    block_trend_edge_exhaustion: bool = False
    trend_edge_exhaustion_zone_percent: float = 68.0
    trend_edge_exhaustion_volume_fade_percent: float = -50.0
    trend_edge_exhaustion_micro_adverse_percent: float = 0.0
    max_adverse_micro_momentum_percent: float | None = None
    min_rsi_for_long: float | None = None
    max_rsi_for_short: float | None = None
    entry_order_type: str = "market"
    limit_entry_retrace_fraction: float = 0.0
    limit_entry_min_offset_percent: float = 0.04
    limit_entry_max_offset_percent: float = 0.45
    limit_entry_max_wait_seconds: int = 0
    min_post_cost_edge_ratio: float = 0.0
    fee_bps: float = 4.0
    slippage_bps: float = 5.0
    require_mtf_alignment: bool = False
    min_mtf_alignment_score: int = 0
    adaptive_stop_enabled: bool = False
    adaptive_stop_atr_multiplier: float = 1.15
    adaptive_stop_realized_volatility_multiplier: float = 1.6
    adaptive_target_volatility_multiplier: float = 2.0
    time_exit_enabled: bool = True
    time_exit_only_when_not_profitable: bool = False
    time_exit_use_config_max_hold_only: bool = False
    early_exit_enabled: bool = False
    early_exit_min_seconds: int = 90
    early_exit_min_favorable_r: float = 0.25
    early_exit_max_adverse_r: float = 0.2
    early_exit_min_adverse_votes: int = 2
    early_exit_flow_edge: float = 0.02
    require_entry_quality: bool = False
    min_entry_quality_score: int = 0
    require_limit_entry_quality: bool = False
    min_limit_entry_quality_score: int = 0
    allow_counter_signal: bool = False
    min_counter_signal_score: int = 0
    enable_orderly_range: bool = False
    min_orderly_range_score: int = 0
    orderly_range_min_width_percent: float = 0.35
    orderly_range_max_width_percent: float = 2.4
    orderly_range_max_trend_abs_percent: float = 0.22
    orderly_range_max_volume_cv: float = 0.55
    orderly_range_min_touch_count: int = 2
    orderly_range_max_path_efficiency: float = 0.45
    orderly_range_low_zone_percent: float = 25.0
    orderly_range_high_zone_percent: float = 75.0
    orderly_range_min_edge_alternations: int = 0
    orderly_range_min_mid_cross_count: int = 0
    orderly_range_min_width_cost_ratio: float = 0.0
    # ML-learned trend filter: when enabled, a trained LightGBM booster scores
    # P(win) from continuous features and a trade is only allowed when the
    # probability clears ``ml_trend_threshold``. This supersedes the brittle
    # boolean-gate stack (require_entry_quality / block_* / confluence / mtf)
    # for the trend leg, which over-rejected and starved the system. The model
    # path and threshold are calibrated offline from 6 months of 23-symbol
    # data; the gate is additive and defaults off so existing variants are
    # unaffected.
    use_ml_trend_filter: bool = False
    ml_trend_model_path: str = ""
    ml_trend_threshold: float = 0.55


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
    features = dict(_mapping(payload.get("features")))
    factor_scores = _factor_scores(payload, features)
    long_score, short_score = _direction_scores(factor_scores)
    side = _select_side(long_score, short_score)
    edge = max(long_score, short_score) - min(long_score, short_score)
    base_confidence = _confidence(edge, factor_scores)
    side, edge, signal_diagnostics = _signal_side_adjustment(features, side, edge, setup_profile)
    if signal_diagnostics["mode"] in {"counter_signal", "orderly_range_reversion"}:
        base_confidence = max(base_confidence, min(0.45 + edge / 120.0, 0.82))
    features["setup_signal_mode"] = signal_diagnostics["mode"]
    features["setup_signal_diagnostics"] = signal_diagnostics
    factor_summary = _factor_summary(
        factors=factor_scores,
        long_score=long_score,
        short_score=short_score,
        edge=edge,
        selected_side=side,
        confidence=base_confidence,
        profile=setup_profile,
        features=features,
    )
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
            confidence=round(base_confidence, 4),
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
            factor_summary=factor_summary,
            price_basis={},
            reasons=_dedupe(["quant_setup_pass", *warnings]),
            warnings=warnings,
        )

    entry, entry_basis = _entry_price(reference, side, volatility, features, setup_profile)
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
    notional, sizing_warnings, sizing_diagnostics = _setup_notional(
        entry_price=entry,
        stop_price=stop,
        risk_limits=risk_limits,
        features=features,
        edge=edge,
        profile=setup_profile,
    )
    price_basis = _price_basis(
        reference=reference,
        entry=entry,
        stop=stop,
        target=target,
        side=side,
        features=features,
        entry_basis=entry_basis,
        stop_basis=stop_basis,
        target_basis=target_basis,
        signal_diagnostics=signal_diagnostics,
        profile=setup_profile,
        risk_limits=risk_limits,
        sizing_diagnostics=sizing_diagnostics,
    )
    warnings.extend(sizing_warnings)
    reasons = _setup_reasons(side, factor_scores, regime, warnings)
    reasons = _dedupe([*reasons, f"signal_mode:{signal_diagnostics['mode']}", *_entry_order_reason_codes(entry_basis)])
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
    cost_rejections = _post_cost_rejections(target_distance, setup_profile)
    if cost_rejections:
        decision = "pass"
        reasons = _dedupe([*reasons, *cost_rejections])
    signal_rejections = _signal_quality_rejections(signal_diagnostics, setup_profile)
    if signal_rejections:
        decision = "pass"
        reasons = _dedupe([*reasons, *signal_rejections])
    limit_entry_rejections = _limit_entry_quality_rejections(entry_basis, features, side, signal_diagnostics, setup_profile)
    if limit_entry_rejections:
        decision = "pass"
        reasons = _dedupe([*reasons, *limit_entry_rejections])
    if _high_crowding(features, side):
        warnings.append("crowding_risk")
        reasons = _dedupe([*reasons, "crowding_risk"])
    # ML-learned trend filter short-circuits the boolean-gate stack when
    # enabled: a single calibrated probability replaces require_entry_quality /
    # confluence / block_* / mtf checks, which over-rejected and starved the
    # system. Existing variants keep their boolean gates (flag defaults off).
    if setup_profile.use_ml_trend_filter:
        ml_verdict = _ml_trend_filter_rejection(features, side, setup_profile)
        if ml_verdict:
            decision = "pass"
            reasons = _dedupe([*reasons, *ml_verdict])
        # skip the boolean-gate stack below when ML governs the trend leg
    else:
        profile_rejections = _profile_rejections(symbol, features, side, setup_profile)
        profile_rejections.extend(_setup_reason_rejections(reasons, setup_profile))
        profile_rejections.extend(_factor_guard_rejections(factor_scores, setup_profile))
        if profile_rejections:
            decision = "pass"
            reasons = _dedupe([*reasons, *profile_rejections])
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
            risk_reward_ratio=round(target_distance / stop_distance, 4),
            stop_distance_percent=round(stop_distance, 4),
            target_distance_percent=round(target_distance, 4),
            factor_summary=factor_summary,
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
        factor_summary=factor_summary,
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
        _spike_reversal_factor(features),
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
    change = _float(features.get("open_interest_change_percent"))
    if value is None:
        return FactorScore("open_interest", None, 0.0, 1.0, direction="both", reasons=["missing_open_interest"])
    scale = 1_000_000.0 if _float(features.get("open_interest_value")) is not None else 100_000.0
    score = min(value / scale, 20.0)
    reasons = ["oi_confirmation"]
    if change is None:
        reasons.append("missing_open_interest_change")
    elif change >= 2.0:
        score += min(change * 1.5, 10.0)
        reasons.append("oi_expanding")
    elif change <= -2.0:
        score -= min(abs(change) * 1.2, 8.0)
        reasons.append("oi_contracting")
    return FactorScore("open_interest", value, _clip(score, -8.0, 28.0), 1.0, direction="both", reasons=reasons)


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


def _spike_reversal_factor(features: Mapping[str, Any]) -> FactorScore:
    signal = str(features.get("spike_reversal_signal") or "").lower()
    wick = _float(features.get("spike_wick_percent"))
    ratio = _float(features.get("spike_wick_to_body_ratio"))
    if signal not in {"long", "short"}:
        return FactorScore("spike_reversal", None, 0.0, 0.8, reasons=["no_spike_reversal_signal"])
    strength = 8.0
    if wick is not None:
        strength += min(wick * 2.0, 8.0)
    if ratio is not None:
        strength += min(ratio, 6.0)
    reasons = [f"spike_reversal_{signal}"]
    if wick is not None:
        reasons.append(f"spike_wick_percent:{round(wick, 4)}")
    if ratio is not None:
        reasons.append(f"spike_wick_to_body_ratio:{round(ratio, 4)}")
    return FactorScore("spike_reversal", wick, _clip(strength, 0.0, 22.0), 0.8, direction=signal, reasons=reasons)


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


def _entry_price(
    reference: float,
    side: str,
    volatility: float | None,
    features: Mapping[str, Any],
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    order_type = str(profile.entry_order_type or "market").lower()
    if order_type == "limit":
        return _limit_entry_price(reference, side, volatility, features, profile)
    slippage_buffer = min(max((volatility or 1.0) * 0.015, 0.0005), 0.0015)
    if side == "long":
        entry = reference * (1.0 + slippage_buffer)
    else:
        entry = reference * (1.0 - slippage_buffer)
    return entry, {
        "order_type": "market",
        "anchor": "reference_with_slippage_buffer",
        "slippage_buffer_percent": slippage_buffer * 100.0,
        "limit_entry_max_wait_seconds": 0,
    }


def _limit_entry_price(
    reference: float,
    side: str,
    volatility: float | None,
    features: Mapping[str, Any],
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    min_offset = max(_float(profile.limit_entry_min_offset_percent) or 0.0, 0.0)
    max_offset = max(_float(profile.limit_entry_max_offset_percent) or min_offset, min_offset)
    signal_mode = str(features.get("setup_signal_mode") or "trend_follow")
    range_low = _positive_float(features.get("range_low_price"))
    range_high = _positive_float(features.get("range_high_price"))
    range_entry: dict[str, float | str] | None = None
    if signal_mode == "orderly_range_reversion" and range_low is not None and range_high is not None and range_high > range_low:
        span = range_high - range_low
        if side == "long" and range_low < reference:
            price = range_low + span * 0.14
            dynamic_offset = abs(reference - price) / reference * 100.0
            max_offset = max(max_offset, min(dynamic_offset + 0.03, profile.orderly_range_max_width_percent))
            range_entry = {"anchor": "range_low_reversion", "price": price}
        elif side == "short" and range_high > reference:
            price = range_high - span * 0.14
            dynamic_offset = abs(reference - price) / reference * 100.0
            max_offset = max(max_offset, min(dynamic_offset + 0.03, profile.orderly_range_max_width_percent))
            range_entry = {"anchor": "range_high_reversion", "price": price}
    vol_basis = max(
        value
        for value in (
            volatility,
            _float(features.get("atr_percent")),
            _float(features.get("realized_volatility_percent")),
            min_offset / max(_float(profile.limit_entry_retrace_fraction) or 1.0, 0.01),
        )
        if value is not None
    )
    raw_offset = vol_basis * max(_float(profile.limit_entry_retrace_fraction) or 0.0, 0.0)
    offset = _clip(raw_offset, min_offset, max_offset)
    default_price = reference * (1.0 - offset / 100.0) if side == "long" else reference * (1.0 + offset / 100.0)
    candidates: list[dict[str, float | str]] = [{"anchor": "volatility_retrace", "price": default_price}]
    vwap = _positive_float(features.get("vwap"))
    support = _positive_float(features.get("support_price"))
    resistance = _positive_float(features.get("resistance_price"))
    if range_entry is not None:
        candidates.append(range_entry)

    if side == "long":
        lower_bound = reference * (1.0 - max_offset / 100.0)
        upper_bound = reference * (1.0 - min_offset / 100.0)
        if vwap is not None and lower_bound <= vwap <= upper_bound:
            candidates.append({"anchor": "vwap_pullback", "price": vwap})
        if support is not None and lower_bound <= support <= upper_bound:
            candidates.append({"anchor": "support_retest", "price": support})
        selected = range_entry if range_entry is not None else max(candidates, key=lambda item: float(item["price"]))
        entry = _clip(float(selected["price"]), lower_bound, upper_bound)
    else:
        lower_bound = reference * (1.0 + min_offset / 100.0)
        upper_bound = reference * (1.0 + max_offset / 100.0)
        if vwap is not None and lower_bound <= vwap <= upper_bound:
            candidates.append({"anchor": "vwap_retest", "price": vwap})
        if resistance is not None and lower_bound <= resistance <= upper_bound:
            candidates.append({"anchor": "resistance_retest", "price": resistance})
        selected = range_entry if range_entry is not None else min(candidates, key=lambda item: float(item["price"]))
        entry = _clip(float(selected["price"]), lower_bound, upper_bound)

    actual_offset = abs(reference - entry) / reference * 100.0
    return entry, {
        "order_type": "limit",
        "anchor": str(selected["anchor"]),
        "raw_offset_percent": raw_offset,
        "offset_percent": actual_offset,
        "min_offset_percent": min_offset,
        "max_offset_percent": max_offset,
        "volatility_basis_percent": vol_basis,
        "limit_entry_max_wait_seconds": max(0, int(_float(profile.limit_entry_max_wait_seconds) or 0)),
        "candidate_prices": [
            {"anchor": str(item["anchor"]), "price": round(float(item["price"]), 8)} for item in candidates
        ],
    }


def _stop_distance_percent(
    entry: float,
    volatility: float | None,
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    atr = _float(features.get("atr_percent"))
    realized_volatility = _float(features.get("realized_volatility_percent"))
    base_volatility = atr or volatility or 1.0
    if profile.adaptive_stop_enabled:
        adaptive_candidates = [0.65]
        if atr is not None:
            adaptive_candidates.append(atr * max(profile.adaptive_stop_atr_multiplier, 0.1))
        if realized_volatility is not None:
            adaptive_candidates.append(realized_volatility * max(profile.adaptive_stop_realized_volatility_multiplier, 0.1))
        if volatility is not None:
            adaptive_candidates.append(volatility * 1.05)
        base = max(adaptive_candidates)
    else:
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
    raw_stop_distance = stop_distance
    profile_adjusted = raw_stop_distance * max(profile.stop_distance_multiplier, 0.1)
    capped_stop_distance = min(max(profile_adjusted, 0.45), profile.max_stop_distance_percent)
    return capped_stop_distance, {
        "anchor": anchor,
        "adaptive_stop_enabled": profile.adaptive_stop_enabled,
        "atr_percent": atr,
        "realized_volatility_percent": realized_volatility,
        "volatility_percent": volatility,
        "structure_distance_percent": structure_distance,
        "raw_stop_distance_percent": raw_stop_distance,
        "profile_adjusted_stop_distance_percent": profile_adjusted,
        "capped_stop_distance_percent": capped_stop_distance,
        "min_stop_distance_percent": 0.45,
        "max_stop_distance_percent": profile.max_stop_distance_percent,
        "was_capped": capped_stop_distance != profile_adjusted,
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
    # Volatility ceiling must never force target below stop * min_risk_reward.
    # Previously `min(target, max(vol*2.0, stop*1.25))` could collapse the
    # reward geometry so the min_risk_reward gate could never be satisfied in
    # compressed volatility, making the trend leg systematically untradeable.
    # The floor is now stop * min_risk_reward so the cap only trims excess
    # reward, never the minimum admissible risk/reward.
    min_rr_floor = stop_distance * max(profile.min_risk_reward, 1.0)
    volatility_ceiling_reason = None
    if volatility is not None:
        volatility_ceiling = max(volatility * 2.0, stop_distance * 1.25)
        if target > volatility_ceiling:
            target = max(volatility_ceiling, min_rr_floor)
            volatility_ceiling_reason = "capped_to_volatility_ceiling" if target == volatility_ceiling else "volatility_ceiling_floor_protected"
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
    raw_target = target
    profile_adjusted = raw_target * max(profile.target_distance_multiplier, 0.1)
    max_target = 7.0
    if profile.adaptive_stop_enabled:
        adaptive_volatility = max(
            value
            for value in (
                volatility,
                _float(features.get("atr_percent")),
                _float(features.get("realized_volatility_percent")),
                stop_distance,
            )
            if value is not None
        )
        max_target = min(7.0, max(stop_distance * profile.min_risk_reward, adaptive_volatility * max(profile.adaptive_target_volatility_multiplier, 0.1)))
    capped_target = min(max(profile_adjusted, stop_distance * profile.min_risk_reward), max_target)
    return capped_target, {
        "anchor": anchor,
        "adaptive_target_enabled": profile.adaptive_stop_enabled,
        "reward_multiple": reward_multiple,
        "structure_distance_percent": structure_distance,
        "raw_target_distance_percent": raw_target,
        "profile_adjusted_target_distance_percent": profile_adjusted,
        "capped_target_distance_percent": capped_target,
        "min_target_distance_percent": stop_distance * profile.min_risk_reward,
        "max_target_distance_percent": max_target,
        "was_capped": capped_target != profile_adjusted,
        "min_rr_floor_percent": min_rr_floor,
        "volatility_ceiling_reason": volatility_ceiling_reason,
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
) -> tuple[float | None, list[str], dict[str, Any]]:
    stop_fraction = abs(entry_price - stop_price) / entry_price
    warnings: list[str] = []
    diagnostics: dict[str, Any] = {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_fraction": stop_fraction,
        "stop_distance_percent": stop_fraction * 100.0,
        "max_risk_per_trade_usdt": risk_limits.max_risk_per_trade_usdt,
        "max_position_notional_usdt": risk_limits.max_position_notional_usdt,
        "profile_notional_fraction": min(max(profile.max_notional_fraction, 0.0), 1.0),
        "min_executable_notional": _positive_float(features.get("min_executable_notional")),
        "min_qty": _positive_float(features.get("min_qty")),
        "step_size": _positive_float(features.get("step_size")),
        "min_notional": _positive_float(features.get("min_notional")),
    }
    if stop_fraction <= 0:
        diagnostics["status"] = "invalid_stop_distance"
        return None, ["invalid_stop_distance"], diagnostics
    risk_notional = risk_limits.max_risk_per_trade_usdt / stop_fraction
    edge_fraction = min(max(edge / 40.0, 0.35), 1.0)
    max_notional = min(risk_limits.max_position_notional_usdt, risk_notional)
    notional = max_notional * edge_fraction
    notional *= min(max(profile.max_notional_fraction, 0.0), 1.0)
    diagnostics.update(
        {
            "risk_sized_notional_usdt": risk_notional,
            "max_notional_before_edge_usdt": max_notional,
            "edge_fraction": edge_fraction,
            "candidate_notional_before_min_usdt": notional,
            "stop_risk_at_cap_usdt": max_notional * stop_fraction,
        }
    )
    min_executable = _positive_float(features.get("min_executable_notional"))
    if min_executable is not None and notional < min_executable:
        diagnostics["min_notional_pressure"] = round(min_executable - notional, 8)
        if min_executable <= max_notional:
            warnings.append("raised_to_min_executable_notional")
            notional = min_executable
        else:
            diagnostics["status"] = "min_executable_exceeds_risk_sized_notional"
            diagnostics["final_notional_usdt"] = None
            return None, ["min_executable_exceeds_risk_sized_notional"], diagnostics
    else:
        diagnostics["min_notional_pressure"] = 0.0
    if notional <= 0:
        diagnostics["status"] = "notional_not_positive"
        diagnostics["final_notional_usdt"] = None
        return None, ["notional_not_positive"], diagnostics
    final_notional = min(notional, risk_limits.max_position_notional_usdt)
    diagnostics["final_notional_usdt"] = final_notional
    diagnostics["stop_risk_usdt"] = final_notional * stop_fraction
    diagnostics["capped_by_max_position_notional"] = notional > risk_limits.max_position_notional_usdt
    diagnostics["warnings"] = list(warnings)
    diagnostics["status"] = "sized"
    return final_notional, warnings, diagnostics


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


def _entry_order_reason_codes(entry_basis: Mapping[str, Any]) -> list[str]:
    order_type = str(entry_basis.get("order_type") or "market").strip().lower()
    if order_type != "limit":
        return ["entry_order_type:market"]
    wait_seconds = int(_float(entry_basis.get("limit_entry_max_wait_seconds")) or 45)
    return [
        "entry_order_type:limit",
        "entry_time_in_force:GTX",
        f"limit_entry_max_wait_seconds:{max(wait_seconds, 1)}",
        *([f"limit_entry_anchor:{entry_basis.get('anchor')}"] if entry_basis.get("anchor") else []),
        *(
            [f"limit_entry_offset_percent:{round(float(offset), 6)}"]
            if (offset := _float(entry_basis.get("offset_percent"))) is not None
            else []
        ),
    ]


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
        or _float(features.get("realized_volatility_percent"))
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
    entry_basis: Mapping[str, Any],
    stop_basis: Mapping[str, Any],
    target_basis: Mapping[str, Any],
    signal_diagnostics: Mapping[str, Any],
    profile: TradeSetupProfile,
    risk_limits: RiskLimits,
    sizing_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    stop_distance = abs(entry - stop) / entry * 100.0
    target_distance = abs(target - entry) / entry * 100.0
    risk_reward = target_distance / stop_distance if stop_distance > 0 else None
    return {
        "model": "limit_entry_structure_stop_target_v1"
        if str(entry_basis.get("order_type") or "").lower() == "limit"
        else "expected_market_entry_structure_stop_target_v1",
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
        "entry_basis": _rounded_mapping(entry_basis),
        "limit_entry_quality": _limit_entry_quality_diagnostics(entry_basis, features, side, profile),
        "stop_basis": dict(stop_basis),
        "target_basis": dict(target_basis),
        "exit_policy": _exit_policy_basis(profile),
        "signal_diagnostics": _rounded_mapping(signal_diagnostics),
        "post_cost_edge": _post_cost_diagnostics(target_distance, profile),
        "mtf_alignment": _mtf_alignment_diagnostics(features, side, profile),
        "risk_reward_ratio": round(risk_reward, 4) if risk_reward is not None else None,
        "stop_distance_percent": round(stop_distance, 4),
        "target_distance_percent": round(target_distance, 4),
        "sizing_diagnostics": _rounded_mapping(sizing_diagnostics),
        "liquidation_diagnostics": _liquidation_diagnostics(entry=entry, stop=stop, side=side, risk_limits=risk_limits),
        "exchange_filters": {
            "min_qty": _float(features.get("min_qty")),
            "step_size": _float(features.get("step_size")),
            "min_notional": _float(features.get("min_notional")),
            "min_executable_notional": _float(features.get("min_executable_notional")),
        },
        "spike_reversal_reference": _spike_reversal_reference(features),
        "missing_inputs": _missing_geometry_inputs(features),
    }


def _spike_reversal_reference(features: Mapping[str, Any]) -> dict[str, Any] | None:
    signal = str(features.get("spike_reversal_signal") or "").lower()
    if signal not in {"long", "short"}:
        return None
    return {
        "signal": signal,
        "wick_percent": _float(features.get("spike_wick_percent")),
        "wick_to_body_ratio": _float(features.get("spike_wick_to_body_ratio")),
        "entry_price": _positive_float(features.get("spike_reversal_entry_price")),
        "stop_price": _positive_float(features.get("spike_reversal_stop_price")),
        "target_price": _positive_float(features.get("spike_reversal_target_price")),
    }


# Cached ML booster so repeated setup calls do not re-read the model file.
_ML_TREND_MODEL_CACHE: dict[str, Any] = {}


def _ml_trend_filter_rejection(
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> list[str]:
    """Run the ML trend filter; return rejection reasons (empty = accepted).

    Features are read from the candidate feature dict; the 14 inputs mirror
    what the indicator layer already produces so no extra computation is
    needed in the live path. The model is loaded lazily and cached by path.
    """
    if not profile.ml_trend_model_path:
        return ["ml_trend_model_path_missing"]
    try:
        from bfa.strategy.ml_trend_filter import (
            FEATURE_NAMES,
            ml_trend_filter_verdict,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return [f"ml_trend_filter_unavailable:{exc.__class__.__name__}"]
    model = _ML_TREND_MODEL_CACHE.get(profile.ml_trend_model_path)
    if model is None:
        try:
            from bfa.strategy.ml_trend_filter import load_persisted_model

            model = load_persisted_model(profile.ml_trend_model_path)
            _ML_TREND_MODEL_CACHE[profile.ml_trend_model_path] = model
        except Exception as exc:  # pragma: no cover - defensive
            return [f"ml_trend_model_load_failed:{exc.__class__.__name__}"]
    feature_snapshot = {
        "ema_spread": _float(features.get("ema_spread_percent")),
        "rsi": _float(features.get("rsi")),
        "atr_percent": _float(features.get("atr_percent")),
        "realized_vol": _float(features.get("realized_volatility_percent")),
        "mom_6": _float(features.get("kline_momentum_percent")),
        "mom_12": _float(features.get("kline_momentum_percent")),
        "micro_mom": _float(features.get("kline_micro_momentum_percent")),
        "close_position": _float(features.get("kline_close_position_percent")),
        "vol_change": _float(features.get("kline_quote_volume_change_percent")),
        "taker_ratio": _float(features.get("taker_buy_sell_ratio")),
        "rsi_15m": _float(features.get("mtf_15m_rsi")) or _float(features.get("rsi")),
        "ema_spread_15m": _float(features.get("mtf_15m_ema_spread_percent"))
        or _float(features.get("ema_spread_percent")),
        "mom_15m": _float(features.get("mtf_15m_momentum_percent"))
        or _float(features.get("kline_momentum_percent")),
        "hour_of_day": _hour_of_day(features),
    }
    accept, proba, reasons = ml_trend_filter_verdict(
        feature_snapshot,
        model=model,
        threshold=profile.ml_trend_threshold,
    )
    # Stash the probability so downstream diagnostics/price_basis can surface it.
    features_ref = dict(features) if isinstance(features, Mapping) else {}
    features_ref.setdefault("ml_trend_probability", round(proba, 4))
    if accept:
        return []
    return reasons or [f"ml_trend_rejected:{proba:.4f}"]


def _hour_of_day(features: Mapping[str, Any]) -> float:
    """Extract hour-of-day from the latest market timestamp, defaulting to 12."""
    for key in ("latest_market_at", "occurred_at", "generated_at", "reference_time"):
        value = features.get(key)
        if isinstance(value, str) and "T" in value:
            try:
                hour = int(value[11:13])
                return float(hour)
            except (ValueError, IndexError):
                continue
    return 12.0


def _profile_rejections(symbol: str, features: Mapping[str, Any], side: str, profile: TradeSetupProfile) -> list[str]:
    rejections: list[str] = []
    signal_mode = str(features.get("setup_signal_mode") or "trend_follow")
    is_range_reversion = signal_mode == "orderly_range_reversion"
    if side.lower() in {item.lower() for item in profile.disabled_sides}:
        rejections.append("side_disabled_by_profile")
    if symbol.upper() in {item.upper() for item in profile.excluded_symbols}:
        rejections.append("symbol_excluded_by_profile")
    sample_size = int(_float(features.get("indicator_sample_size")) or 0)
    if sample_size < profile.min_indicator_sample_size:
        rejections.append("indicator_sample_below_profile_min")
    trend = _float(features.get("ema_spread_percent"))
    if profile.require_trend_alignment and trend is not None and not is_range_reversion:
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
    if profile.require_open_interest and _float(features.get("open_interest_value")) is None and _float(features.get("open_interest")) is None:
        rejections.append("missing_open_interest")
    min_quote_volume = _float(profile.min_quote_volume_usdt)
    quote_volume = _float(features.get("quote_volume"))
    if min_quote_volume is not None and (quote_volume is None or quote_volume < min_quote_volume):
        rejections.append("quote_volume_below_profile_min")
    min_momentum = _float(profile.min_abs_momentum_percent)
    if min_momentum is not None and not is_range_reversion and _abs_momentum(features) < min_momentum:
        rejections.append("momentum_below_profile_min")
    min_volume_impulse = _float(profile.min_volume_impulse_percent)
    volume_impulse = _float(features.get("kline_quote_volume_change_percent"))
    if min_volume_impulse is not None and not is_range_reversion:
        if volume_impulse is None:
            rejections.append("missing_volume_impulse")
        elif volume_impulse < min_volume_impulse:
            rejections.append("volume_impulse_below_profile_min")
    max_volatility = _float(profile.max_volatility_percent)
    volatility = _volatility_percent(features)
    if max_volatility is not None:
        if volatility is None:
            rejections.append("missing_volatility")
        elif volatility > max_volatility:
            rejections.append("volatility_above_profile_max")
    min_flow_edge = _float(profile.min_directional_taker_flow_edge)
    taker_ratio = _float(features.get("taker_buy_sell_ratio"))
    if min_flow_edge is not None and not is_range_reversion:
        if taker_ratio is None:
            rejections.append("missing_directional_taker_flow")
        elif side == "long" and taker_ratio < 1.0 + min_flow_edge:
            rejections.append("taker_flow_not_aligned")
        elif side == "short" and taker_ratio > 1.0 - min_flow_edge:
            rejections.append("taker_flow_not_aligned")
    if profile.block_adverse_trend_vwap and not is_range_reversion and _adverse_trend_vwap(features, side):
        rejections.append("adverse_trend_vwap_alignment")
    adverse_micro = _float(profile.max_adverse_micro_momentum_percent)
    micro_momentum = _float(features.get("kline_micro_momentum_percent"))
    if adverse_micro is not None and micro_momentum is not None and not is_range_reversion:
        limit = abs(adverse_micro)
        if side == "long" and micro_momentum < -limit:
            rejections.append("micro_momentum_against_side")
        if side == "short" and micro_momentum > limit:
            rejections.append("micro_momentum_against_side")
    min_rsi_for_long = _float(profile.min_rsi_for_long)
    max_rsi_for_short = _float(profile.max_rsi_for_short)
    if min_rsi_for_long is not None and rsi is not None and side == "long" and rsi < min_rsi_for_long and not is_range_reversion:
        rejections.append("rsi_below_long_profile_min")
    if max_rsi_for_short is not None and rsi is not None and side == "short" and rsi > max_rsi_for_short and not is_range_reversion:
        rejections.append("rsi_above_short_profile_max")
    if profile.block_hot_micro_reversal and not is_range_reversion and _hot_micro_reversal(features, side):
        rejections.append("hot_move_micro_reversal")
    if profile.block_volume_fade and not is_range_reversion and _volume_fade_against_trade(features, side):
        rejections.append("volume_fade_against_trade")
    if profile.block_trend_edge_exhaustion and not is_range_reversion:
        rejections.extend(_trend_edge_exhaustion_rejections(features, side, profile))
    if profile.block_spike_reversal_conflict and not is_range_reversion:
        rejections.extend(_spike_reversal_conflict_rejections(features, side))
    min_confluence = int(_float(profile.min_directional_confluence) or 0)
    if not is_range_reversion and (profile.require_directional_confluence or min_confluence > 0):
        required = max(min_confluence, 1)
        confluence = _directional_confluence_score(features, side)
        if confluence < required:
            rejections.append(f"directional_confluence_below_profile_min:{confluence}/{required}")
    min_mtf = int(_float(profile.min_mtf_alignment_score) or 0)
    if not is_range_reversion and (profile.require_mtf_alignment or min_mtf > 0):
        required = max(min_mtf, 1)
        mtf = _mtf_alignment_diagnostics(features, side, profile)
        if not mtf["available"]:
            rejections.append("missing_mtf_confirmation")
        elif int(mtf["score"]) < required:
            rejections.append(f"mtf_alignment_below_profile_min:{mtf['score']}/{required}")
    return _dedupe(rejections)


def _trend_edge_exhaustion_rejections(
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> list[str]:
    close_position = _float(features.get("kline_close_position_percent"))
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    micro_momentum = _float(features.get("kline_micro_momentum_percent"))
    momentum = _float(features.get("kline_momentum_percent"))
    if close_position is None or volume_change is None or micro_momentum is None or momentum is None:
        return []
    if volume_change > profile.trend_edge_exhaustion_volume_fade_percent:
        return []
    zone = max(50.0, min(95.0, profile.trend_edge_exhaustion_zone_percent))
    micro_limit = abs(profile.trend_edge_exhaustion_micro_adverse_percent)
    if side == "long" and momentum > 0 and close_position >= zone and micro_momentum <= -micro_limit:
        return ["trend_long_edge_exhaustion"]
    if side == "short" and momentum < 0 and close_position <= 100.0 - zone and micro_momentum >= micro_limit:
        return ["trend_short_edge_exhaustion"]
    return []


def _post_cost_rejections(target_distance_percent: float, profile: TradeSetupProfile) -> list[str]:
    diagnostics = _post_cost_diagnostics(target_distance_percent, profile)
    minimum = _float(profile.min_post_cost_edge_ratio) or 0.0
    if minimum <= 0:
        return []
    ratio = _float(diagnostics.get("target_to_cost_ratio"))
    if ratio is None or ratio < minimum:
        return ["post_cost_edge_below_profile_min"]
    return []


def _post_cost_diagnostics(target_distance_percent: float, profile: TradeSetupProfile) -> dict[str, Any]:
    fee_bps = max(_float(profile.fee_bps) or 0.0, 0.0)
    slippage_bps = max(_float(profile.slippage_bps) or 0.0, 0.0)
    minimum = _float(profile.min_post_cost_edge_ratio) or 0.0
    round_trip_cost_percent = 2.0 * (fee_bps + slippage_bps) / 100.0
    ratio = target_distance_percent / round_trip_cost_percent if round_trip_cost_percent > 0 else None
    return {
        "target_distance_percent": round(target_distance_percent, 8),
        "fee_bps_per_side": fee_bps,
        "slippage_bps_per_side": slippage_bps,
        "round_trip_cost_percent": round(round_trip_cost_percent, 8),
        "target_to_cost_ratio": round(ratio, 8) if ratio is not None else None,
        "min_post_cost_edge_ratio": minimum,
        "passed": True if minimum <= 0 else ratio is not None and ratio >= minimum,
    }


def _signal_quality_rejections(signal_diagnostics: Mapping[str, Any], profile: TradeSetupProfile) -> list[str]:
    mode = str(signal_diagnostics.get("mode") or "trend_follow")
    if mode in {"counter_signal", "orderly_range_reversion"}:
        return []
    if not profile.require_entry_quality:
        return []
    required = max(1, int(_float(profile.min_entry_quality_score) or 1))
    entry_quality = _mapping(signal_diagnostics.get("entry_quality"))
    score = int(_float(entry_quality.get("score")) or 0)
    if score < required:
        return [f"entry_quality_below_profile_min:{score}/{required}"]
    return []


def _limit_entry_quality_rejections(
    entry_basis: Mapping[str, Any],
    features: Mapping[str, Any],
    side: str,
    signal_diagnostics: Mapping[str, Any],
    profile: TradeSetupProfile,
) -> list[str]:
    if not profile.require_limit_entry_quality:
        return []
    if str(signal_diagnostics.get("mode") or "trend_follow") != "trend_follow":
        return []
    required = max(1, int(_float(profile.min_limit_entry_quality_score) or 1))
    diagnostics = _limit_entry_quality_diagnostics(entry_basis, features, side, profile)
    score = int(_float(diagnostics.get("score")) or 0)
    if score < required:
        return [f"limit_entry_quality_below_profile_min:{score}/{required}"]
    return []


def _limit_entry_quality_diagnostics(
    entry_basis: Mapping[str, Any],
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> dict[str, Any]:
    if side not in {"long", "short"}:
        return {"side": side, "score": 0, "max_score": 0, "checks": []}
    order_type = str(entry_basis.get("order_type") or "market").lower()
    anchor = str(entry_basis.get("anchor") or "")
    actual_offset = _float(entry_basis.get("offset_percent"))
    min_offset = max(_float(entry_basis.get("min_offset_percent")) or profile.limit_entry_min_offset_percent, 0.0)
    max_offset = max(_float(entry_basis.get("max_offset_percent")) or profile.limit_entry_max_offset_percent, min_offset)
    vol_basis = max(_float(entry_basis.get("volatility_basis_percent")) or 0.0, min_offset)
    close_position = _float(features.get("kline_close_position_percent"))
    candidates = entry_basis.get("candidate_prices") if isinstance(entry_basis.get("candidate_prices"), list) else []
    candidate_anchors = {str(item.get("anchor") or "") for item in candidates if isinstance(item, Mapping)}
    structural_anchors = {
        "vwap_pullback",
        "vwap_retest",
        "support_retest",
        "resistance_retest",
        "range_low_reversion",
        "range_high_reversion",
    }
    has_structural_candidate = bool(candidate_anchors & structural_anchors)
    selected_structural = anchor in structural_anchors
    pullback_floor = max(min_offset, min(max_offset, vol_basis * 0.06))
    anti_chase_floor = max(min_offset, min(max_offset, 0.08))
    if close_position is None:
        avoids_late_extreme = True
    elif side == "long":
        avoids_late_extreme = close_position <= 92.0 or (actual_offset or 0.0) >= max(anti_chase_floor, 0.12)
    else:
        avoids_late_extreme = close_position >= 8.0 or (actual_offset or 0.0) >= max(anti_chase_floor, 0.12)
    checks = [
        {"name": "limit_order", "passed": order_type == "limit", "value": order_type},
        {"name": "offset_available", "passed": actual_offset is not None, "value": actual_offset},
        {
            "name": "pullback_not_chasing",
            "passed": actual_offset is not None and actual_offset >= pullback_floor,
            "value": actual_offset,
        },
        {
            "name": "offset_within_bounds",
            "passed": actual_offset is not None and min_offset <= actual_offset <= max_offset,
            "value": actual_offset,
        },
        {
            "name": "structural_anchor_or_enough_pullback",
            "passed": selected_structural or has_structural_candidate or (actual_offset is not None and actual_offset >= anti_chase_floor),
            "value": anchor,
        },
        {"name": "avoids_late_extreme", "passed": avoids_late_extreme, "value": close_position},
    ]
    score = sum(1 for item in checks if item["passed"])
    return {
        "side": side,
        "anchor": anchor,
        "score": score,
        "max_score": len(checks),
        "offset_percent": round(actual_offset, 8) if actual_offset is not None else None,
        "pullback_floor_percent": round(pullback_floor, 8),
        "anti_chase_floor_percent": round(anti_chase_floor, 8),
        "candidate_anchors": sorted(item for item in candidate_anchors if item),
        "checks": _normalised_checks(checks),
    }


def _exit_policy_basis(profile: TradeSetupProfile) -> dict[str, Any]:
    return {
        "time_exit_enabled": bool(profile.time_exit_enabled),
        "time_exit_only_when_not_profitable": bool(profile.time_exit_only_when_not_profitable),
        "time_exit_use_config_max_hold_only": bool(profile.time_exit_use_config_max_hold_only),
        "early_exit_enabled": bool(profile.early_exit_enabled),
        "early_exit_min_seconds": max(1, int(_float(profile.early_exit_min_seconds) or 1)),
        "early_exit_min_favorable_r": max(_float(profile.early_exit_min_favorable_r) or 0.0, 0.0),
        "early_exit_max_adverse_r": max(_float(profile.early_exit_max_adverse_r) or 0.0, 0.0),
        "early_exit_min_adverse_votes": max(1, int(_float(profile.early_exit_min_adverse_votes) or 1)),
        "early_exit_flow_edge": max(_float(profile.early_exit_flow_edge) or 0.0, 0.0),
    }


def _signal_side_adjustment(
    features: Mapping[str, Any],
    selected_side: str,
    edge: float,
    profile: TradeSetupProfile,
) -> tuple[str, float, dict[str, Any]]:
    entry_quality = _entry_quality_diagnostics(features, selected_side, profile)
    counter_side = "short" if selected_side == "long" else "long" if selected_side == "short" else "flat"
    counter_signal = _counter_signal_diagnostics(features, counter_side, profile)
    orderly_range = _orderly_range_diagnostics(features, profile)
    diagnostics: dict[str, Any] = {
        "mode": "trend_follow",
        "original_side": selected_side,
        "selected_side": selected_side,
        "entry_quality": entry_quality,
        "counter_signal": counter_signal,
        "orderly_range": orderly_range,
    }

    if profile.enable_orderly_range and orderly_range["score"] >= max(1, int(_float(profile.min_orderly_range_score) or 1)):
        range_side = str(orderly_range.get("side") or "flat")
        if range_side in {"long", "short"}:
            adjusted_edge = max(edge, profile.min_edge + float(orderly_range["score"]))
            diagnostics.update({"mode": "orderly_range_reversion", "selected_side": range_side, "edge_adjustment": adjusted_edge - edge})
            return range_side, adjusted_edge, diagnostics

    if (
        profile.allow_counter_signal
        and selected_side in {"long", "short"}
        and counter_side in {"long", "short"}
        and counter_signal["score"] >= max(1, int(_float(profile.min_counter_signal_score) or 1))
        and entry_quality["score"] < max(1, int(_float(profile.min_entry_quality_score) or 1))
    ):
        adjusted_edge = max(edge, profile.min_edge + float(counter_signal["score"]))
        diagnostics.update({"mode": "counter_signal", "selected_side": counter_side, "edge_adjustment": adjusted_edge - edge})
        return counter_side, adjusted_edge, diagnostics

    return selected_side, edge, diagnostics


def _entry_quality_diagnostics(features: Mapping[str, Any], side: str, profile: TradeSetupProfile) -> dict[str, Any]:
    if side not in {"long", "short"}:
        return {"side": side, "score": 0, "max_score": 0, "checks": []}
    flow_edge = max(_float(profile.min_directional_taker_flow_edge) or 0.02, 0.0)
    checks = _direction_checks(features, side, flow_edge=flow_edge)
    score = sum(1 for item in checks if item["passed"])
    return {
        "side": side,
        "score": score,
        "max_score": len(checks),
        "checks": _normalised_checks(checks),
    }


def _counter_signal_diagnostics(features: Mapping[str, Any], side: str, profile: TradeSetupProfile) -> dict[str, Any]:
    if side not in {"long", "short"}:
        return {"side": side, "score": 0, "max_score": 0, "checks": []}
    flow_edge = max(_float(profile.min_directional_taker_flow_edge) or 0.02, 0.0)
    checks = _direction_checks(features, side, flow_edge=flow_edge)
    mtf = _mtf_alignment_diagnostics(features, side, profile)
    if mtf["available"]:
        checks.append({"name": "counter_mtf_alignment", "passed": int(mtf["score"]) >= 3, "value": mtf["score"]})
    score = sum(1 for item in checks if item["passed"])
    return {
        "side": side,
        "score": score,
        "max_score": len(checks),
        "checks": _normalised_checks(checks),
    }


def _direction_checks(features: Mapping[str, Any], side: str, *, flow_edge: float) -> list[dict[str, Any]]:
    trend = _float(features.get("ema_spread_percent"))
    reference = _float(features.get("reference_price"))
    vwap = _float(features.get("vwap"))
    micro = _float(features.get("kline_micro_momentum_percent"))
    window = _float(features.get("kline_momentum_percent"))
    taker_ratio = _float(features.get("taker_buy_sell_ratio"))
    taker_change = _float(features.get("taker_buy_sell_ratio_change"))
    close_position = _float(features.get("kline_close_position_percent"))
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    vwap_delta = _percent_delta(vwap, reference) if vwap is not None and reference is not None else None

    if side == "long":
        return [
            {"name": "ema_trend", "passed": trend is not None and trend >= 0.08, "value": trend},
            {"name": "micro_momentum", "passed": micro is not None and micro >= 0.05, "value": micro},
            {"name": "window_momentum", "passed": window is not None and window >= 0.25, "value": window},
            {"name": "vwap_side", "passed": vwap_delta is not None and vwap_delta >= 0.0, "value": vwap_delta},
            {"name": "taker_flow", "passed": taker_ratio is not None and taker_ratio >= 1.0 + flow_edge, "value": taker_ratio},
            {"name": "taker_acceleration", "passed": taker_change is not None and taker_change >= -0.02, "value": taker_change},
            {"name": "close_position", "passed": close_position is not None and close_position >= 45.0, "value": close_position},
            {"name": "volume_not_fading", "passed": volume_change is not None and volume_change >= -15.0, "value": volume_change},
        ]
    return [
        {"name": "ema_trend", "passed": trend is not None and trend <= -0.08, "value": trend},
        {"name": "micro_momentum", "passed": micro is not None and micro <= -0.05, "value": micro},
        {"name": "window_momentum", "passed": window is not None and window <= -0.25, "value": window},
        {"name": "vwap_side", "passed": vwap_delta is not None and vwap_delta <= 0.0, "value": vwap_delta},
        {"name": "taker_flow", "passed": taker_ratio is not None and taker_ratio <= 1.0 - flow_edge, "value": taker_ratio},
        {"name": "taker_acceleration", "passed": taker_change is not None and taker_change <= 0.02, "value": taker_change},
        {"name": "close_position", "passed": close_position is not None and close_position <= 55.0, "value": close_position},
        {"name": "volume_not_fading", "passed": volume_change is not None and volume_change >= -15.0, "value": volume_change},
    ]


def _orderly_range_diagnostics(features: Mapping[str, Any], profile: TradeSetupProfile) -> dict[str, Any]:
    reference = _positive_float(features.get("reference_price"))
    width = _float(features.get("range_width_percent"))
    trend = abs(_float(features.get("ema_spread_percent")) or 0.0)
    volume_cv = _float(features.get("range_volume_cv"))
    lower_touches = int(_float(features.get("range_lower_touch_count")) or 0)
    upper_touches = int(_float(features.get("range_upper_touch_count")) or 0)
    path_efficiency = _float(features.get("range_path_efficiency"))
    edge_alternations = int(_float(features.get("range_edge_alternation_count")) or 0)
    mid_cross_count = int(_float(features.get("range_mid_cross_count")) or 0)
    close_position = _float(features.get("range_close_position_percent"))
    if close_position is None:
        close_position = _float(features.get("kline_close_position_percent"))
    round_trip_cost_percent = 2.0 * (max(_float(profile.fee_bps) or 0.0, 0.0) + max(_float(profile.slippage_bps) or 0.0, 0.0)) / 100.0
    width_cost_ratio = width / round_trip_cost_percent if width is not None and round_trip_cost_percent > 0 else None
    range_side = "flat"
    if close_position is not None:
        if close_position <= profile.orderly_range_low_zone_percent:
            range_side = "long"
        elif close_position >= profile.orderly_range_high_zone_percent:
            range_side = "short"
    checks = [
        {
            "name": "range_width_tradeable",
            "passed": width is not None
            and profile.orderly_range_min_width_percent <= width <= profile.orderly_range_max_width_percent,
            "value": width,
        },
        {
            "name": "trend_flat_enough",
            "passed": trend <= profile.orderly_range_max_trend_abs_percent,
            "value": trend,
        },
        {
            "name": "volume_stable",
            "passed": volume_cv is not None and volume_cv <= profile.orderly_range_max_volume_cv,
            "value": volume_cv,
        },
        {
            "name": "two_sided_touches",
            "passed": lower_touches >= profile.orderly_range_min_touch_count
            and upper_touches >= profile.orderly_range_min_touch_count,
            "value": min(lower_touches, upper_touches),
        },
        {
            "name": "path_choppy_not_trending",
            "passed": path_efficiency is not None and path_efficiency <= profile.orderly_range_max_path_efficiency,
            "value": path_efficiency,
        },
        {
            "name": "edges_alternate_cleanly",
            "passed": edge_alternations >= profile.orderly_range_min_edge_alternations,
            "value": edge_alternations,
        },
        {
            "name": "range_crosses_midline",
            "passed": mid_cross_count >= profile.orderly_range_min_mid_cross_count,
            "value": mid_cross_count,
        },
        {
            "name": "range_width_covers_cost",
            "passed": profile.orderly_range_min_width_cost_ratio <= 0
            or (width_cost_ratio is not None and width_cost_ratio >= profile.orderly_range_min_width_cost_ratio),
            "value": width_cost_ratio,
        },
        {
            "name": "price_at_range_edge",
            "passed": range_side in {"long", "short"},
            "value": close_position,
        },
        {
            "name": "reference_available",
            "passed": reference is not None,
            "value": reference,
        },
    ]
    score = sum(1 for item in checks if item["passed"])
    return {
        "side": range_side,
        "score": score,
        "max_score": len(checks),
        "checks": _normalised_checks(checks),
    }


def _normalised_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": str(item["name"]),
            "passed": bool(item["passed"]),
            "value": round(float(item["value"]), 8) if isinstance(item["value"], float) else item["value"],
        }
        for item in checks
    ]


def _mtf_alignment_diagnostics(features: Mapping[str, Any], side: str, profile: TradeSetupProfile) -> dict[str, Any]:
    del profile
    checks: list[dict[str, Any]] = []
    trend = _float(features.get("mtf_15m_ema_spread_percent"))
    momentum = _float(features.get("mtf_15m_momentum_percent"))
    micro = _float(features.get("mtf_15m_micro_momentum_percent"))
    reference = _float(features.get("mtf_15m_reference_price"))
    vwap = _float(features.get("mtf_15m_vwap"))
    taker_ratio = _float(features.get("mtf_15m_taker_buy_sell_ratio"))
    close_position = _float(features.get("mtf_15m_close_position_percent"))

    if side == "long":
        checks.append({"name": "15m_ema_trend", "passed": trend is not None and trend >= 0.05, "value": trend})
        checks.append({"name": "15m_momentum", "passed": momentum is not None and momentum >= 0.12, "value": momentum})
        checks.append({"name": "15m_micro_momentum", "passed": micro is not None and micro >= -0.05, "value": micro})
        checks.append({"name": "15m_vwap_side", "passed": reference is not None and vwap is not None and reference >= vwap, "value": _percent_delta(vwap, reference) if reference is not None and vwap is not None else None})
        checks.append({"name": "15m_taker_flow", "passed": taker_ratio is not None and taker_ratio >= 1.0, "value": taker_ratio})
        checks.append({"name": "15m_close_position", "passed": close_position is not None and close_position >= 45.0, "value": close_position})
    elif side == "short":
        checks.append({"name": "15m_ema_trend", "passed": trend is not None and trend <= -0.05, "value": trend})
        checks.append({"name": "15m_momentum", "passed": momentum is not None and momentum <= -0.12, "value": momentum})
        checks.append({"name": "15m_micro_momentum", "passed": micro is not None and micro <= 0.05, "value": micro})
        checks.append({"name": "15m_vwap_side", "passed": reference is not None and vwap is not None and reference <= vwap, "value": _percent_delta(vwap, reference) if reference is not None and vwap is not None else None})
        checks.append({"name": "15m_taker_flow", "passed": taker_ratio is not None and taker_ratio <= 1.0, "value": taker_ratio})
        checks.append({"name": "15m_close_position", "passed": close_position is not None and close_position <= 55.0, "value": close_position})

    available = any(item["value"] is not None for item in checks)
    score = sum(1 for item in checks if item["passed"])
    return {
        "available": available,
        "side": side,
        "score": score,
        "max_score": len(checks),
        "checks": [
            {
                "name": str(item["name"]),
                "passed": bool(item["passed"]),
                "value": round(float(item["value"]), 8) if isinstance(item["value"], float) else item["value"],
            }
            for item in checks
        ],
    }


def _adverse_trend_vwap(features: Mapping[str, Any], side: str) -> bool:
    trend = _float(features.get("ema_spread_percent"))
    reference = _float(features.get("reference_price"))
    vwap = _float(features.get("vwap"))
    if trend is None or reference is None or vwap is None or vwap <= 0:
        return False
    vwap_delta = ((reference - vwap) / vwap) * 100.0
    if side == "long":
        return trend < 0 and vwap_delta < 0
    return trend > 0 and vwap_delta > 0


def _hot_micro_reversal(features: Mapping[str, Any], side: str) -> bool:
    change_24h = _float(features.get("price_change_percent"))
    window = _float(features.get("kline_momentum_percent"))
    micro = _float(features.get("kline_micro_momentum_percent"))
    if change_24h is None or micro is None:
        return False
    window_value = window or 0.0
    if side == "long":
        return (change_24h >= 8.0 or window_value >= 1.2) and micro < -0.05
    return (change_24h <= -8.0 or window_value <= -1.2) and micro > 0.05


def _volume_fade_against_trade(features: Mapping[str, Any], side: str) -> bool:
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    momentum = _float(features.get("kline_micro_momentum_percent"))
    if momentum is None:
        momentum = _float(features.get("kline_momentum_percent"))
    if volume_change is None or momentum is None:
        return False
    if volume_change >= -20.0:
        return False
    if side == "long":
        return momentum <= 0.15
    return momentum >= -0.15


def _spike_reversal_conflict_rejections(features: Mapping[str, Any], side: str) -> list[str]:
    signal = str(features.get("spike_reversal_signal") or "").lower()
    if signal not in {"long", "short"}:
        return []
    if signal != side:
        return ["spike_reversal_against_side"]

    trend = _float(features.get("ema_spread_percent"))
    reference = _float(features.get("reference_price"))
    vwap = _float(features.get("vwap"))
    window = _float(features.get("kline_momentum_percent"))
    micro = _float(features.get("kline_micro_momentum_percent"))
    close_position = _float(features.get("kline_close_position_percent"))
    volume_change = _float(features.get("kline_quote_volume_change_percent"))
    taker_ratio = _float(features.get("taker_buy_sell_ratio"))
    rsi = _float(features.get("rsi"))
    vwap_delta = ((reference - vwap) / vwap) * 100.0 if reference is not None and vwap is not None and vwap > 0 else None

    if side == "long":
        countertrend = (
            (trend is not None and trend <= -0.2)
            or (window is not None and window <= -0.8)
            or (vwap_delta is not None and vwap_delta <= -0.2)
            or (rsi is not None and rsi < 40.0)
        )
        confirmed = (
            (micro is not None and micro >= 0.2)
            and (close_position is not None and close_position >= 60.0)
            and (volume_change is not None and volume_change >= 10.0)
            and (taker_ratio is not None and taker_ratio >= 1.05)
        )
        return ["unconfirmed_countertrend_spike_reversal"] if countertrend and not confirmed else []

    countertrend = (
        (trend is not None and trend >= 0.2)
        or (window is not None and window >= 0.8)
        or (vwap_delta is not None and vwap_delta >= 0.2)
        or (rsi is not None and rsi > 60.0)
    )
    confirmed = (
        (micro is not None and micro <= -0.2)
        and (close_position is not None and close_position <= 40.0)
        and (volume_change is not None and volume_change >= 10.0)
        and (taker_ratio is not None and taker_ratio <= 0.95)
    )
    return ["unconfirmed_countertrend_spike_reversal"] if countertrend and not confirmed else []


def _directional_confluence_score(features: Mapping[str, Any], side: str) -> int:
    score = 0
    trend = _float(features.get("ema_spread_percent"))
    reference = _float(features.get("reference_price"))
    vwap = _float(features.get("vwap"))
    window = _float(features.get("kline_momentum_percent"))
    micro = _float(features.get("kline_micro_momentum_percent"))
    taker_ratio = _float(features.get("taker_buy_sell_ratio"))
    rsi = _float(features.get("rsi"))
    volume_change = _float(features.get("kline_quote_volume_change_percent"))

    if side == "long":
        score += int(trend is not None and trend >= 0.1)
        score += int(reference is not None and vwap is not None and vwap > 0 and reference >= vwap)
        score += int(window is not None and window >= 0.35)
        score += int(micro is not None and micro >= 0.0)
        score += int(taker_ratio is not None and taker_ratio >= 1.02)
        score += int(rsi is not None and rsi >= 45.0)
        score += int(volume_change is not None and volume_change >= 0.0)
        return score

    score += int(trend is not None and trend <= -0.1)
    score += int(reference is not None and vwap is not None and vwap > 0 and reference <= vwap)
    score += int(window is not None and window <= -0.35)
    score += int(micro is not None and micro <= 0.0)
    score += int(taker_ratio is not None and taker_ratio <= 0.98)
    score += int(rsi is not None and rsi <= 55.0)
    score += int(volume_change is not None and volume_change >= 0.0)
    return score


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
        if "blocked_factor_reasons" in values:
            values["blocked_factor_reasons"] = tuple(str(item) for item in _sequence(values["blocked_factor_reasons"]))
        if "blocked_setup_reasons" in values:
            values["blocked_setup_reasons"] = tuple(str(item) for item in _sequence(values["blocked_setup_reasons"]))
        if "blocked_factor_names" in values:
            values["blocked_factor_names"] = tuple(str(item) for item in _sequence(values["blocked_factor_names"]))
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


def _factor_guard_rejections(factors: list[FactorScore], profile: TradeSetupProfile) -> list[str]:
    blocked = {item.lower() for item in profile.blocked_factor_reasons}
    blocked_names = {item.lower() for item in profile.blocked_factor_names}
    if not blocked and not blocked_names:
        return []
    reasons: list[str] = []
    for factor in factors:
        if factor.name.lower() in blocked_names and factor.weighted_score < 0:
            reasons.append(f"profile_blocked_factor_name:{factor.name}")
        for reason in factor.reasons:
            if reason.lower() in blocked:
                reasons.append(f"forward_paper_guard_factor:{reason}")
    return _dedupe(reasons)


def _setup_reason_rejections(reasons: list[str], profile: TradeSetupProfile) -> list[str]:
    blocked = {item.lower() for item in profile.blocked_setup_reasons}
    if not blocked:
        return []
    return [f"profile_blocked_setup_reason:{reason}" for reason in reasons if reason.lower() in blocked]


def _factor_summary(
    *,
    factors: list[FactorScore],
    long_score: float,
    short_score: float,
    edge: float,
    selected_side: str,
    confidence: float,
    profile: TradeSetupProfile,
    features: Mapping[str, Any],
) -> dict[str, Any]:
    missing_inputs = sorted(
        {
            reason
            for factor in factors
            for reason in factor.reasons
            if reason.startswith("missing_")
        }
        | {str(note) for note in _sequence(features.get("quality_notes")) if str(note).startswith("missing_")}
    )
    group_totals: dict[str, dict[str, float]] = {}
    factor_rows: list[dict[str, Any]] = []
    for factor in factors:
        group = _factor_group(factor.name)
        group_totals.setdefault(group, {"long": 0.0, "short": 0.0, "both": 0.0, "net": 0.0})
        weighted = factor.weighted_score
        if factor.direction == "both":
            group_totals[group]["both"] += weighted
        elif weighted >= 0:
            group_totals[group]["long"] += weighted
        else:
            group_totals[group]["short"] += abs(weighted)
        group_totals[group]["net"] += weighted
        factor_rows.append(
            {
                "name": factor.name,
                "group": group,
                "direction": factor.direction,
                "polarity": _factor_polarity(factor),
                "weighted_score": round(weighted, 4),
                "reasons": list(factor.reasons),
            }
        )
    supportive = sorted(factor_rows, key=lambda item: abs(float(item["weighted_score"])), reverse=True)
    threshold_checks = {
        "min_edge": profile.min_edge,
        "edge_passed": edge >= profile.min_edge,
        "min_confidence": profile.min_confidence,
        "confidence_passed": confidence >= profile.min_confidence,
        "missing_input_count": len(missing_inputs),
        "factor_count": len(factors),
    }
    return {
        "schema": "bfa_factor_summary_v1",
        "selected_side": selected_side,
        "long_score": round(long_score, 4),
        "short_score": round(short_score, 4),
        "edge_score": round(edge, 4),
        "confidence": round(confidence, 4),
        "coverage_ratio": round((len(factors) - len([f for f in factors if any(r.startswith("missing_") for r in f.reasons)])) / len(factors), 4)
        if factors
        else 0.0,
        "missing_inputs": missing_inputs,
        "threshold_checks": threshold_checks,
        "group_totals": {
            key: {inner_key: round(inner_value, 4) for inner_key, inner_value in value.items()}
            for key, value in sorted(group_totals.items())
        },
        "top_factors": supportive[:5],
    }


def _factor_group(name: str) -> str:
    groups = {
        "momentum": "trend_momentum",
        "trend_structure": "trend_momentum",
        "rsi_regime": "trend_momentum",
        "volume_impulse": "volume",
        "open_interest": "positioning",
        "taker_flow": "flow",
        "funding": "positioning",
        "volatility": "volatility_range",
        "spike_reversal": "volatility_range",
        "liquidity": "liquidity_tradability",
        "tradability": "liquidity_tradability",
        "narrative": "narrative_heat",
    }
    return groups.get(name, "other")


def _factor_polarity(factor: FactorScore) -> str:
    weighted = factor.weighted_score
    if abs(weighted) < 1e-9:
        return "neutral"
    if factor.direction == "both":
        return "both_supportive" if weighted > 0 else "both_caution"
    if weighted > 0:
        return f"supports_{factor.direction}"
    return "supports_short" if factor.direction == "long" else "supports_long"


def _liquidation_diagnostics(*, entry: float, stop: float, side: str, risk_limits: RiskLimits) -> dict[str, Any]:
    leverage = max(_float(risk_limits.max_leverage) or 1.0, 1.0)
    liquidation_distance_percent = 100.0 / leverage
    liquidation_price = entry * (1.0 - liquidation_distance_percent / 100.0) if side == "long" else entry * (1.0 + liquidation_distance_percent / 100.0)
    stop_distance_percent = abs(entry - stop) / entry * 100.0
    return {
        "model": "approx_entry_inverse_leverage_v1",
        "max_leverage": leverage,
        "approx_liquidation_price": round(liquidation_price, 8),
        "approx_liquidation_distance_percent": round(liquidation_distance_percent, 4),
        "stop_distance_percent": round(stop_distance_percent, 4),
        "stop_before_liquidation": stop_distance_percent < liquidation_distance_percent,
        "conservative": True,
    }


def _missing_geometry_inputs(features: Mapping[str, Any]) -> list[str]:
    checks = {
        "missing_support_price": features.get("support_price") is None,
        "missing_resistance_price": features.get("resistance_price") is None,
        "missing_vwap": features.get("vwap") is None,
        "missing_atr_percent": features.get("atr_percent") is None,
        "missing_realized_volatility": features.get("realized_volatility_percent") is None,
        "missing_close_position": features.get("kline_close_position_percent") is None,
        "missing_min_executable_notional": features.get("min_executable_notional") is None,
    }
    return [name for name, missing in checks.items() if missing]


def _rounded_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    rounded: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, float):
            rounded[key] = round(value, 8)
        else:
            rounded[key] = value
    return rounded


def _abs_momentum(features: Mapping[str, Any]) -> float:
    values = [
        abs(value)
        for value in (
            _float(features.get("price_change_percent")),
            _float(features.get("kline_momentum_percent")),
            _float(features.get("kline_micro_momentum_percent")),
        )
        if value is not None
    ]
    return max(values, default=0.0)


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


def _percent_delta(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return ((end - start) / start) * 100.0


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
