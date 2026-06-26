"""Live adapter for the research micro-grid scalping leg."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from bfa.ai.schema import RiskLimits
from bfa.backtest.models import BacktestBar
from bfa.config import AppConfig
from bfa.strategy.candidates import CandidateSignal
from bfa.strategy.setup import FactorScore, TradeSetup


@dataclass(frozen=True)
class MicroGridLiveConfig:
    enabled: bool
    seconds_cache_path: Path
    max_cache_age_seconds: float
    top_n: int
    min_score: float
    notional_fraction: float
    order_type: str
    order_wait_seconds: int
    max_hold_seconds: int | None
    model_horizon_seconds: int

    @classmethod
    def from_app(cls, config: AppConfig) -> "MicroGridLiveConfig":
        raw_max_hold_seconds = _int_or_default(config.get("BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS"), 420)
        max_hold_seconds = raw_max_hold_seconds if raw_max_hold_seconds > 0 else None
        raw_model_horizon_seconds = _int_or_default(config.get("BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS"), 0)
        model_horizon_seconds = raw_model_horizon_seconds if raw_model_horizon_seconds > 0 else (
            raw_max_hold_seconds if raw_max_hold_seconds > 0 else 180
        )
        return cls(
            enabled=_truthy(config.get("BFA_LIVE_MICRO_GRID_ENABLED")),
            seconds_cache_path=Path(config.get("BFA_LIVE_MICRO_GRID_SECONDS_CACHE")),
            max_cache_age_seconds=max(_float_or_default(config.get("BFA_LIVE_MICRO_GRID_MAX_AGE_SECONDS"), 20.0), 1.0),
            top_n=max(_int_or_default(config.get("BFA_LIVE_MICRO_GRID_TOP_N"), 6), 1),
            min_score=_float_or_default(config.get("BFA_LIVE_MICRO_GRID_MIN_SCORE"), 1.0),
            notional_fraction=_clip(_float_or_default(config.get("BFA_LIVE_MICRO_GRID_NOTIONAL_FRACTION"), 0.72), 0.05, 1.0),
            order_type=(config.get("BFA_LIVE_MICRO_GRID_ORDER_TYPE") or "LIMIT").strip().upper() or "LIMIT",
            order_wait_seconds=max(_int_or_default(config.get("BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS"), 20), 1),
            max_hold_seconds=max_hold_seconds,
            model_horizon_seconds=max(model_horizon_seconds, 1),
        )


def build_micro_grid_live_candidates(
    *,
    config: AppConfig,
    scan_symbols: list[str],
    generated_at: str,
    max_position_notional_usdt: float | None,
) -> tuple[list[CandidateSignal], dict[str, Any]]:
    live_config = MicroGridLiveConfig.from_app(config)
    health: dict[str, Any] = {
        "enabled": live_config.enabled,
        "status": "disabled",
        "seconds_cache_path": str(live_config.seconds_cache_path),
        "order_wait_seconds": int(live_config.order_wait_seconds),
        "max_hold_seconds": live_config.max_hold_seconds,
        "model_horizon_seconds": int(live_config.model_horizon_seconds),
        "candidate_count": 0,
        "rejection_counts": {},
        "symbols": {},
    }
    if not live_config.enabled:
        return [], health
    cache_payload, cache_error = _read_seconds_cache(live_config.seconds_cache_path)
    if cache_error:
        health.update({"status": "cache_unavailable", "error": cache_error})
        return [], health
    updated_at_ms = _int_or_none(cache_payload.get("updated_at_ms"))
    age_seconds = _cache_age_seconds(updated_at_ms)
    health["cache_updated_at_ms"] = updated_at_ms
    health["cache_age_seconds"] = round(age_seconds, 3) if age_seconds is not None else None
    if age_seconds is None or age_seconds > live_config.max_cache_age_seconds:
        health.update({"status": "cache_stale"})
        return [], health

    research = _micro_grid_research_module()
    profile = _live_profile(research, live_config)
    candidates: list[CandidateSignal] = []
    rejection_counts: dict[str, int] = {}
    symbols_payload = cache_payload.get("symbols")
    if not isinstance(symbols_payload, Mapping):
        health.update({"status": "cache_invalid", "error": "symbols_missing"})
        return [], health

    allowed = [symbol.upper() for symbol in scan_symbols]
    for symbol in allowed:
        raw_bars = symbols_payload.get(symbol) or symbols_payload.get(symbol.lower())
        seconds = _continuous_seconds(symbol, raw_bars if isinstance(raw_bars, list) else [])
        symbol_health = {
            "bar_count": len(seconds),
            "status": "not_evaluated",
            "reasons": [],
            "order_count": 0,
        }
        health["symbols"][symbol] = symbol_health
        if len(seconds) <= profile.required_history_seconds:
            reason = "insufficient_cached_seconds"
            symbol_health.update({"status": "rejected", "reasons": [reason]})
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue
        state, reasons = research.build_micro_grid_state(seconds, len(seconds) - 1, profile)
        if state is None:
            symbol_health.update({"status": "rejected", "reasons": list(reasons)})
            for reason in reasons:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue
        orders = research.build_grid_orders(symbol, state, profile)
        if not orders:
            reasons = research.grid_order_rejection_reasons(state, profile)
            symbol_health.update({"status": "rejected", "reasons": reasons or ["no_valid_grid_orders"]})
            for reason in reasons or ["no_valid_grid_orders"]:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue
        ranked = sorted(orders, key=lambda order: _order_rank_key(order, research))
        selected = ranked[0]
        score = _order_score(selected, research)
        quality_scale, quality_reasons = research.micro_trade_quality_scale_from_reason_codes(selected.reason_codes)
        symbol_health.update(
            {
                "status": "candidate" if score >= live_config.min_score else "below_min_score",
                "score": round(score, 6),
                "trade_quality_scale": round(float(quality_scale), 6),
                "trade_quality_reasons": list(quality_reasons),
                "order_count": len(orders),
                "selected_side": selected.side,
                "entry_price": selected.entry_price,
                "stop_price": selected.stop_price,
                "target_price": selected.target_price,
            }
        )
        if score < live_config.min_score:
            rejection_counts["micro_grid_score_below_min"] = rejection_counts.get("micro_grid_score_below_min", 0) + 1
            continue
        candidates.append(
            _candidate_from_order(
                selected,
                generated_at=generated_at,
                score=score,
                quality_scale=quality_scale,
                quality_reasons=quality_reasons,
                max_position_notional_usdt=max_position_notional_usdt,
                live_config=live_config,
                cache_updated_at_ms=updated_at_ms,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.symbol))
    selected_candidates = candidates[: live_config.top_n]
    health.update(
        {
            "status": "available" if selected_candidates else "no_candidate",
            "candidate_count": len(selected_candidates),
            "raw_candidate_count": len(candidates),
            "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)),
        }
    )
    return selected_candidates, health


def micro_grid_setup_from_candidate(
    candidate: CandidateSignal,
    *,
    risk_limits: RiskLimits,
    notional_fraction: float,
    order_type: str = "LIMIT",
) -> TradeSetup:
    features = dict(candidate.features)
    symbol = candidate.symbol.upper()
    side = str(features.get("micro_grid_side") or "").lower()
    entry = _positive_float(features.get("micro_grid_entry_price"))
    stop = _positive_float(features.get("micro_grid_stop_price"))
    target = _positive_float(features.get("micro_grid_target_price"))
    if side not in {"long", "short"} or entry is None or stop is None or target is None:
        return _pass_setup(symbol, reasons=["micro_grid_candidate_missing_prices"])
    stop_distance_percent = abs(entry - stop) / entry * 100.0
    target_distance_percent = abs(target - entry) / entry * 100.0
    risk_reward = target_distance_percent / stop_distance_percent if stop_distance_percent > 0 else None
    quality_scale = _clip(_float_or_default(features.get("micro_grid_quality_scale"), 1.0), 0.0, 1.0)
    notional, sizing_reasons = _micro_notional(
        risk_limits,
        entry=entry,
        stop=stop,
        min_executable_notional=_positive_float(features.get("min_executable_notional")),
        notional_fraction=notional_fraction * quality_scale,
    )
    hold_seconds = _int_or_default(features.get("micro_grid_max_hold_seconds"), 120)
    time_exit_enabled = hold_seconds > 0
    order_wait_seconds = max(_int_or_default(features.get("micro_grid_order_wait_seconds"), 45), 1)
    confidence = _clip(0.58 + min(candidate.score, 6.0) / 24.0, 0.58, 0.86)
    reasons = _dedupe(
        [
            "strategy_leg:micro_grid",
            "entry_order_type:limit" if order_type.upper() == "LIMIT" else "entry_order_type:market",
            *(
                [
                    "entry_time_in_force:GTX",
                    f"limit_entry_max_wait_seconds:{order_wait_seconds}",
                ]
                if order_type.upper() == "LIMIT"
                else []
            ),
            "micro_grid_time_exit_enabled" if time_exit_enabled else "micro_grid_time_exit_disabled",
            *candidate.reason_codes,
            f"micro_grid_applied_quality_scale:{round(quality_scale, 6)}",
            *sizing_reasons,
        ]
    )
    if notional is None:
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
            factor_scores=[],
            long_score=0.0,
            short_score=0.0,
            edge_score=0.0,
            regime="micro_grid",
            risk_reward_ratio=round(risk_reward, 4) if risk_reward is not None else None,
            stop_distance_percent=round(stop_distance_percent, 4),
            target_distance_percent=round(target_distance_percent, 4),
            factor_summary={"schema": "bfa_micro_grid_factor_summary_v1", "edge_score": candidate.score},
            price_basis=_price_basis(features, entry=entry, stop=stop, target=target, side=side, order_type=order_type),
            reasons=_dedupe([*reasons, "micro_grid_notional_not_executable"]),
            warnings=[],
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
        hold_time_minutes=max(1, int(math.ceil(hold_seconds / 60.0))) if time_exit_enabled else None,
        factor_scores=_micro_factor_scores(features, side=side, score=candidate.score),
        long_score=round(candidate.score if side == "long" else 0.0, 4),
        short_score=round(candidate.score if side == "short" else 0.0, 4),
        edge_score=round(candidate.score, 4),
        regime="micro_grid_scalp",
        risk_reward_ratio=round(risk_reward, 4) if risk_reward is not None else None,
        stop_distance_percent=round(stop_distance_percent, 4),
        target_distance_percent=round(target_distance_percent, 4),
        factor_summary={
            "schema": "bfa_micro_grid_factor_summary_v1",
            "edge_score": round(candidate.score, 4),
            "confidence": round(confidence, 4),
            "selected_side": side,
            "coverage_ratio": 1.0,
        },
        price_basis=_price_basis(features, entry=entry, stop=stop, target=target, side=side, order_type=order_type),
        reasons=reasons,
        warnings=[],
    )


def is_micro_grid_candidate(candidate: Any) -> bool:
    features = getattr(candidate, "features", None)
    if isinstance(features, Mapping) and features.get("strategy_leg") == "micro_grid":
        return True
    return any(str(reason) == "strategy_leg:micro_grid" for reason in getattr(candidate, "reason_codes", []) or [])


def _candidate_from_order(
    order,
    *,
    generated_at: str,
    score: float,
    quality_scale: float,
    quality_reasons: list[str],
    max_position_notional_usdt: float | None,
    live_config: MicroGridLiveConfig,
    cache_updated_at_ms: int | None,
) -> CandidateSignal:
    state = order.state
    side = order.side
    signal_time_ms = _iso_to_epoch_ms(state.signal_time)
    candidate_generated_at_ms = int(time.time() * 1000)
    latency = {
        "source": "micro_grid_live",
        "signal_time": state.signal_time,
        "signal_time_ms": signal_time_ms,
        "cache_updated_at_ms": cache_updated_at_ms,
        "candidate_generated_at_ms": candidate_generated_at_ms,
        "signal_to_candidate_ms": (
            candidate_generated_at_ms - signal_time_ms if signal_time_ms is not None else None
        ),
        "cache_to_candidate_ms": (
            candidate_generated_at_ms - cache_updated_at_ms if cache_updated_at_ms is not None else None
        ),
        "ai_expected": False,
    }
    features = {
        "strategy_leg": "micro_grid",
        "strategy_source": "strategy.micro_grid",
        "setup_signal_mode": "micro_smart_grid",
        "reference_price": float(state.current_price or order.entry_price),
        "micro_grid_side": side,
        "micro_grid_entry_price": float(order.entry_price),
        "micro_grid_stop_price": float(order.stop_price),
        "micro_grid_target_price": float(order.target_price),
        "micro_grid_max_hold_seconds": int(live_config.max_hold_seconds or 0),
        "micro_grid_model_horizon_seconds": int(order.max_hold_seconds),
        "micro_grid_size_weight": float(order.size_weight),
        "micro_grid_quality_scale": float(quality_scale),
        "micro_grid_quality_reasons": list(quality_reasons),
        "micro_grid_score": round(score, 8),
        "micro_grid_order_type": live_config.order_type,
        "micro_grid_order_wait_seconds": int(live_config.order_wait_seconds),
        "micro_grid_signal_time": state.signal_time,
        "micro_grid_signal_time_ms": signal_time_ms,
        "micro_grid_candidate_generated_at_ms": candidate_generated_at_ms,
        "micro_grid_cache_updated_at_ms": cache_updated_at_ms,
        "micro_grid_latency": latency,
        "quote_volume": 50_000_000.0,
        "min_executable_notional": 5.0,
        "kline_range_percent": float(state.width_percent),
        "kline_range_mean_percent": float(state.width_percent),
        "realized_volatility_percent": float(state.instantaneous_vol_percent),
        "atr_percent": float(state.instantaneous_vol_percent),
        "taker_buy_sell_ratio": _taker_buy_sell_ratio(state.entry_taker_buy_ratio),
        "support_price": float(state.lower_price),
        "resistance_price": float(state.upper_price),
        "vwap": float(state.center_price),
        "rsi": None,
        "indicator_sample_size": int(state.signal_index),
        "micro_grid_state": {
            "signal_time": state.signal_time,
            "width_percent": state.width_percent,
            "stable_width_percent": state.stable_width_percent,
            "wick_tail_range_percent": state.wick_tail_range_percent,
            "wick_opportunity": state.wick_opportunity,
            "close_position_percent": state.close_position_percent,
            "turn_count": state.turn_count,
            "edge_alternation_count": state.edge_alternation_count,
            "reversal_response_rate": state.reversal_response_rate,
            "path_efficiency": state.path_efficiency,
            "drift_to_width": state.drift_to_width,
            "recent_path_efficiency": state.recent_path_efficiency,
            "recent_drift_to_width": state.recent_drift_to_width,
            "long_reversal_ready": state.long_reversal_ready,
            "short_reversal_ready": state.short_reversal_ready,
            "long_reversal_reason": state.long_reversal_reason,
            "short_reversal_reason": state.short_reversal_reason,
            "long_entry_reversal_fraction": state.long_entry_reversal_fraction,
            "short_entry_reversal_fraction": state.short_entry_reversal_fraction,
            "long_entry_continuation_fraction": state.long_entry_continuation_fraction,
            "short_entry_continuation_fraction": state.short_entry_continuation_fraction,
            "entry_taker_buy_ratio": state.entry_taker_buy_ratio,
            "long_pullback_quality": state.long_pullback_quality,
            "short_pullback_quality": state.short_pullback_quality,
            "wick_model": state.long_wick_model if side == "long" else state.short_wick_model,
        },
        "max_position_notional_usdt": max_position_notional_usdt,
    }
    return CandidateSignal(
        symbol=order.symbol,
        score=round(80.0 + score * 10.0, 6),
        narrative_score=0.0,
        market_score=round(score * 10.0, 6),
        reason_codes=_dedupe(
            [
                "strategy_leg:micro_grid",
                f"micro_grid_quality_scale:{round(float(quality_scale), 6)}",
                *(f"micro_grid_{reason}" for reason in quality_reasons),
                *order.reason_codes,
            ]
        ),
        data_quality_notes=[],
        source_event_ids=[],
        market_event_ids=[],
        generated_at=generated_at,
        features=features,
    )


def _continuous_seconds(symbol: str, raw_bars: list[Any]) -> list[BacktestBar]:
    parsed = [_bar_from_payload(symbol, item) for item in raw_bars if isinstance(item, Mapping)]
    bars = [bar for bar in parsed if bar is not None]
    bars.sort(key=lambda item: item.open_time)
    if not bars:
        return []
    result: list[BacktestBar] = []
    last = bars[0]
    result.append(last)
    for bar in bars[1:]:
        expected = last.open_time + 1000
        while expected < bar.open_time:
            result.append(
                BacktestBar(
                    symbol=symbol.upper(),
                    open_time=expected,
                    open=last.close,
                    high=last.close,
                    low=last.close,
                    close=last.close,
                    volume=0.0,
                    close_time=expected + 999,
                    quote_volume=0.0,
                    taker_buy_quote_volume=0.0,
                )
            )
            expected += 1000
        result.append(bar)
        last = bar
    return result


def _bar_from_payload(symbol: str, item: Mapping[str, Any]) -> BacktestBar | None:
    open_time = _int_or_none(item.get("open_time"))
    open_price = _positive_float(item.get("open"))
    high = _positive_float(item.get("high"))
    low = _positive_float(item.get("low"))
    close = _positive_float(item.get("close"))
    if open_time is None or open_price is None or high is None or low is None or close is None:
        return None
    return BacktestBar(
        symbol=symbol.upper(),
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=_float_or_default(item.get("volume"), 0.0),
        close_time=_int_or_none(item.get("close_time")) or open_time + 999,
        quote_volume=_float_or_default(item.get("quote_volume"), 0.0),
        taker_buy_quote_volume=_float_or_default(item.get("taker_buy_quote_volume"), 0.0),
    )


def _live_profile(research, live_config: MicroGridLiveConfig):
    return research.MicroGridProfile(
        signal_stride_seconds=3,
        order_wait_seconds=int(live_config.order_wait_seconds),
        max_hold_seconds=int(live_config.model_horizon_seconds),
        min_reversal_response_rate=0.46,
        edge_response_fraction=0.16,
        edge_response_max_adverse_fraction=0.2,
        grid_layer_count=3,
        grid_layer_spacing_fraction=0.42,
        min_reservation_edge_fraction=-0.36,
        dynamic_entry_edge_enabled=True,
        dynamic_entry_base_edge_fraction=-0.08,
        dynamic_entry_max_push_fraction=0.24,
        dynamic_entry_flow_push_fraction=0.08,
        dynamic_entry_momentum_push_fraction=0.07,
        dynamic_entry_volatility_push_fraction=0.04,
        dynamic_entry_wick_push_fraction=0.07,
        dynamic_entry_continuation_push_fraction=0.05,
        dynamic_exit_geometry_enabled=True,
        dynamic_exit_stop_widen_fraction=0.12,
        dynamic_exit_max_stop_fraction=0.56,
        dynamic_exit_target_mean_ratio=0.92,
        dynamic_exit_target_quality_ratio=0.08,
        dynamic_exit_target_beyond_mean_fraction=0.14,
        dynamic_exit_max_target_fraction=1.05,
        dynamic_exit_min_target_stop_ratio=0.88,
        wick_min_entry_fraction=-0.36,
        wick_max_entry_fraction=0.7,
        wick_max_stop_fraction=0.5,
        max_drift_to_width=0.9,
        min_width_percent=0.22,
        pullback_model_enabled=True,
        pullback_min_quality=0.0,
        pullback_entry_shift_fraction=0.08,
        side_flow_filter_enabled=True,
        side_flow_extreme_taker_ratio=0.64,
        side_flow_min_pullback_quality=0.4,
    )


def _micro_grid_research_module():
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "run_micro_grid_research.py"
    spec = importlib.util.spec_from_file_location("bfa_micro_grid_research_live", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load micro-grid research script: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_seconds_cache(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "cache_file_missing"
    except json.JSONDecodeError as exc:
        return {}, f"cache_json_invalid:{exc.msg}"
    except OSError as exc:
        return {}, f"cache_read_error:{exc.__class__.__name__}"
    if not isinstance(payload, dict):
        return {}, "cache_payload_not_object"
    return payload, None


def _cache_age_seconds(updated_at_ms: int | None) -> float | None:
    if updated_at_ms is None:
        return None
    return max(0.0, time.time() - updated_at_ms / 1000.0)


def _order_rank_key(order, research) -> tuple[float, int]:
    return (-_order_score(order, research), 0 if order.side == "long" else 1)


def _order_score(order, research) -> float:
    values = research.reason_code_map(order.reason_codes)
    quality_scale, _quality_reasons = research.micro_trade_quality_scale_from_reason_codes(order.reason_codes)
    if quality_scale <= 0:
        return -1_000_000.0
    side = order.side
    pullback_key = "long_pullback_quality" if side == "long" else "short_pullback_quality"
    pullback_quality = research.code_float(values, pullback_key, 0.0)
    reversal_ready = 1.0 if values.get("edge_reversal_ready") == "True" else 0.0
    entry_reversal = research.code_float(values, "entry_reversal_fraction", 0.0)
    wick_success = research.code_float(values, "wick_success_rate", 0.0)
    wick_score = research.code_float(values, "wick_score", 0.0)
    net_reward = research.code_float(values, "net_notional_reward_percent", 0.0)
    entry_continuation = research.code_float(values, "entry_continuation_fraction", 0.0)
    basket_weight = research.code_float(values, "basket_size_weight", 0.75)
    stop_fraction = research.code_float(values, "stop_span_fraction", 0.0)
    entry_edge = research.code_float(values, "entry_edge_fraction", 0.0)
    state = order.state
    side_context_score = _mean_reversion_side_context_score(order, values, research)
    raw_score = (
        max(float(state.score), 0.0)
        + pullback_quality * 1.7
        + reversal_ready * 1.05
        + min(entry_reversal, 0.6) * 1.15
        + wick_success * 1.2
        + wick_score * 0.65
        + max(net_reward, 0.0) * 2.0
        + min(max(-entry_edge, 0.0), 0.24) * 1.1
        + min(float(state.reversal_response_rate), 1.0) * 0.7
        - max(basket_weight - 0.75, 0.0) * 0.55
        - entry_continuation * 2.2
        - max(stop_fraction - 0.32, 0.0) * 0.75
    )
    return raw_score * quality_scale + side_context_score


def _mean_reversion_side_context_score(order, values: Mapping[str, str], research) -> float:
    """Prefer lower-edge longs and upper-edge shorts for live micro scalps."""

    side = str(getattr(order, "side", "")).lower()
    state = getattr(order, "state", None)
    if side not in {"long", "short"} or state is None:
        return 0.0

    close_position = _float_or_default(getattr(state, "close_position_percent", None), 50.0)
    lower_edge = 1.0 - _clip(close_position / 38.0, 0.0, 1.0)
    upper_edge = 1.0 - _clip((100.0 - close_position) / 38.0, 0.0, 1.0)
    side_edge = lower_edge if side == "long" else upper_edge
    opposite_edge = upper_edge if side == "long" else lower_edge

    side_ready = values.get("edge_reversal_ready") == "True"
    opposite_ready = bool(
        getattr(state, "short_reversal_ready", False)
        if side == "long"
        else getattr(state, "long_reversal_ready", False)
    )

    entry_reversal = research.code_float(values, "entry_reversal_fraction", 0.0)
    entry_continuation = research.code_float(values, "entry_continuation_fraction", 0.0)
    score = side_edge * 2.6 - opposite_edge * 3.4
    score += (1.25 if side_ready else -0.35)
    score += min(entry_reversal, 0.75) * 1.35
    score -= min(entry_continuation, 0.75) * 1.6
    if opposite_ready and not side_ready:
        score -= 2.2

    # Use current price displacement from the triple-EMA/center reference as a
    # second mean-reversion cue: price stretched above mean favors short, below
    # mean favors long.
    current = _positive_float(getattr(state, "current_price", None))
    ema_ref = (
        _positive_float(getattr(state, "triple_ema_mid", None))
        or _positive_float(getattr(state, "triple_ema_slow", None))
        or _positive_float(getattr(state, "center_price", None))
    )
    if current is not None and ema_ref is not None:
        deviation_percent = (current - ema_ref) / current * 100.0
        width = max(_float_or_default(getattr(state, "width_percent", None), 0.0), 0.0)
        vol = max(_float_or_default(getattr(state, "instantaneous_vol_percent", None), 0.0), 0.0)
        normalizer = max(width * 0.22, vol * 4.0, 0.04)
        mean_reversion_bias = _clip(deviation_percent / normalizer, -1.5, 1.5)
        score += (-mean_reversion_bias if side == "long" else mean_reversion_bias) * 0.95

    if close_position >= 70.0:
        edge_strength = _clip((close_position - 70.0) / 30.0, 0.0, 2.0)
        if side == "short":
            score += 7.0 + edge_strength * 4.0
        else:
            score -= 80.0 + edge_strength * 30.0
    elif close_position <= 30.0:
        edge_strength = _clip((30.0 - close_position) / 30.0, 0.0, 2.0)
        if side == "long":
            score += 7.0 + edge_strength * 4.0
        else:
            score -= 80.0 + edge_strength * 30.0
    elif 38.0 <= close_position <= 62.0 and not side_ready:
        score -= 0.65

    return score


def _micro_notional(
    risk_limits: RiskLimits,
    *,
    entry: float,
    stop: float,
    min_executable_notional: float | None,
    notional_fraction: float,
) -> tuple[float | None, list[str]]:
    stop_distance = abs(entry - stop) / entry if entry > 0 else 0.0
    if stop_distance <= 0:
        return None, ["micro_grid_invalid_stop_distance"]
    cap = max(risk_limits.max_position_notional_usdt * notional_fraction, 0.0)
    risk_cap = risk_limits.max_risk_per_trade_usdt / stop_distance
    notional = min(cap, risk_cap)
    reasons = ["micro_grid_dynamic_notional"]
    if notional < cap:
        reasons.append("micro_grid_stop_risk_capped")
    if min_executable_notional is not None and notional < min_executable_notional:
        return None, [*reasons, "micro_grid_below_min_executable_notional"]
    return round(notional, 8), reasons


def _micro_factor_scores(features: Mapping[str, Any], *, side: str, score: float) -> list[FactorScore]:
    state = features.get("micro_grid_state") if isinstance(features.get("micro_grid_state"), Mapping) else {}
    return [
        FactorScore(
            name="micro_grid_structure",
            value=_float_or_default(state.get("reversal_response_rate"), 0.0),
            score=score,
            weight=1.0,
            direction=side,
            reasons=["micro_grid_edge_structure"],
        )
    ]


def _price_basis(
    features: Mapping[str, Any],
    *,
    entry: float,
    stop: float,
    target: float,
    side: str,
    order_type: str,
) -> dict[str, Any]:
    return {
        "model": "micro_grid_live_limit_v1",
        "profile": "micro_grid_v5f_live",
        "side": side,
        "reference_price": _positive_float(features.get("reference_price")),
        "entry_price": round(entry, 8),
        "stop_price": round(stop, 8),
        "target_price": round(target, 8),
        "entry_basis": {
            "order_type": order_type.lower(),
            "anchor": "micro_grid_edge_limit",
            "limit_entry_max_wait_seconds": _int_or_default(features.get("micro_grid_order_wait_seconds"), 45),
        },
        "latency": dict(features.get("micro_grid_latency") if isinstance(features.get("micro_grid_latency"), Mapping) else {}),
        "signal_diagnostics": dict(features.get("micro_grid_state") if isinstance(features.get("micro_grid_state"), Mapping) else {}),
        "stop_distance_percent": round(abs(entry - stop) / entry * 100.0, 4),
        "target_distance_percent": round(abs(target - entry) / entry * 100.0, 4),
    }


def _pass_setup(symbol: str, *, reasons: list[str]) -> TradeSetup:
    return TradeSetup(
        symbol=symbol,
        decision="pass",
        side="flat",
        confidence=0.0,
        entry_price=None,
        stop_price=None,
        target_price=None,
        notional_usdt=None,
        hold_time_minutes=None,
        factor_scores=[],
        long_score=0.0,
        short_score=0.0,
        edge_score=0.0,
        regime="micro_grid",
        risk_reward_ratio=None,
        stop_distance_percent=None,
        target_distance_percent=None,
        reasons=list(reasons),
    )


def _taker_buy_sell_ratio(taker_buy_fraction: float) -> float | None:
    fraction = _clip(taker_buy_fraction, 0.001, 0.999)
    sell = 1.0 - fraction
    if sell <= 0:
        return None
    return fraction / sell


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _positive_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else default


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else default


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_to_epoch_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
