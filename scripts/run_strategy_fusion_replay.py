"""Replay multiple strategy result files through one shared portfolio.

The input files are research/backtest JSON payloads that already contain trade
records. This script treats those records as strategy candidates, normalizes
their standalone equity scaling back to an initial-capital basis, then replays
all candidates in chronological order through one account.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bfa.strategy.regime import (
    ALLOW,
    CHOP,
    MICRO_GRID_LEG,
    RANGE,
    RANGE_REVERSION_LEG,
    SKIP_CHOP,
    TREND,
    TREND_LEG,
    allowed_legs_for_regime,
)


@dataclass(frozen=True)
class FusionCandidate:
    source: str
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    notional_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    slippage_usdt: float
    net_pnl_usdt: float
    exit_reason: str
    reason_codes: list[str]
    source_file: str
    strategy_leg: str = TREND_LEG
    regime_label: str = CHOP
    regime_confidence: float = 0.0
    regime_reason_codes: list[str] | None = None
    allowed_strategy_legs: list[str] | None = None
    route_decision: str = SKIP_CHOP
    route_shadow_only: bool = True
    intent_scale: float = 1.0
    features: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True, help="name=path/to/result.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=30.0)
    parser.add_argument("--max-open-positions", type=int, default=4)
    parser.add_argument("--max-symbol-open-positions", type=int, default=1)
    parser.add_argument("--daily-loss-fraction", type=float, default=0.0)
    parser.add_argument("--quality-filter-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--quality-lookback-hours", type=float, default=72.0)
    parser.add_argument("--quality-min-samples", type=int, default=2)
    parser.add_argument("--quality-min-profit-factor", type=float, default=0.75)
    parser.add_argument("--quality-max-stop-rate", type=float, default=0.65)
    parser.add_argument("--quality-min-scale", type=float, default=0.0)
    parser.add_argument("--source-quality-filter-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--source-quality-min-samples", type=int, default=8)
    parser.add_argument("--source-quality-min-profit-factor", type=float, default=0.80)
    parser.add_argument("--source-quality-max-stop-rate", type=float, default=0.70)
    parser.add_argument("--source-quality-min-scale", type=float, default=0.0)
    parser.add_argument("--regime-router-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--regime-router-enforced", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    sources = parse_sources(args.source)
    candidates: list[FusionCandidate] = []
    source_summaries: dict[str, Any] = {}
    for name, path in sources.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_summaries[name] = source_summary(payload, path)
        candidates.extend(load_candidates(name, path, payload))

    replay = replay_fusion(
        candidates,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        max_symbol_open_positions=args.max_symbol_open_positions,
        daily_loss_fraction=args.daily_loss_fraction,
        quality_filter_enabled=args.quality_filter_enabled,
        quality_lookback_hours=args.quality_lookback_hours,
        quality_min_samples=args.quality_min_samples,
        quality_min_profit_factor=args.quality_min_profit_factor,
        quality_max_stop_rate=args.quality_max_stop_rate,
        quality_min_scale=args.quality_min_scale,
        source_quality_filter_enabled=args.source_quality_filter_enabled,
        source_quality_min_samples=args.source_quality_min_samples,
        source_quality_min_profit_factor=args.source_quality_min_profit_factor,
        source_quality_max_stop_rate=args.source_quality_max_stop_rate,
        source_quality_min_scale=args.source_quality_min_scale,
        regime_router_enabled=args.regime_router_enabled,
        regime_router_enforced=args.regime_router_enforced,
    )

    payload = {
        "schema": "bfa_strategy_fusion_replay_v1",
        "method": {
            "input_model": "reads completed strategy result JSON files and treats their trades as candidate intents",
            "normalization": "divides each trade by its standalone equity_scale, then rescales by shared portfolio equity at entry",
            "replay_model": "chronological entry/exit event replay with shared capital, optional daily loss cap, concurrent-position cap, same-symbol cap, and rolling no-lookahead quality gates",
        },
        "sources": source_summaries,
        "config": {
            "initial_capital": args.initial_capital,
            "max_open_positions": args.max_open_positions,
            "max_symbol_open_positions": args.max_symbol_open_positions,
            "daily_loss_fraction": args.daily_loss_fraction,
            "quality_filter_enabled": args.quality_filter_enabled,
            "quality_lookback_hours": args.quality_lookback_hours,
            "quality_min_samples": args.quality_min_samples,
            "quality_min_profit_factor": args.quality_min_profit_factor,
            "quality_max_stop_rate": args.quality_max_stop_rate,
            "quality_min_scale": args.quality_min_scale,
            "source_quality_filter_enabled": args.source_quality_filter_enabled,
            "source_quality_min_samples": args.source_quality_min_samples,
            "source_quality_min_profit_factor": args.source_quality_min_profit_factor,
            "source_quality_max_stop_rate": args.source_quality_max_stop_rate,
            "source_quality_min_scale": args.source_quality_min_scale,
            "regime_router_enabled": args.regime_router_enabled,
            "regime_router_enforced": args.regime_router_enforced,
        },
        "candidate_count": len(candidates),
        "candidate_regime_attribution": attribution_summary([candidate_to_row(candidate) for candidate in candidates]),
        "portfolio_summary": replay["summary"],
        "accepted_regime_attribution": attribution_summary(replay["trades"]),
        "trades": replay["trades"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.quiet:
        print(json.dumps({"output": str(output), "portfolio_summary": replay["summary"]}, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def parse_sources(values: list[str]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--source must use name=path format: {value}")
        name, raw_path = value.split("=", 1)
        name = name.strip()
        if not name:
            raise SystemExit("--source name cannot be empty")
        path = Path(raw_path.strip())
        if not path.exists():
            raise SystemExit(f"source file does not exist: {path}")
        if name in sources:
            raise SystemExit(f"duplicate source name: {name}")
        sources[name] = path
    return sources


def source_summary(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "schema": payload.get("schema"),
        "variant": payload.get("variant"),
        "window": payload.get("window"),
        "symbols": payload.get("symbols"),
        "standalone_summary": payload.get("portfolio_summary") or payload.get("compound_summary") or payload.get("summary"),
    }


def load_candidates(source: str, path: Path, payload: dict[str, Any]) -> list[FusionCandidate]:
    rows = payload.get("trades")
    if not isinstance(rows, list):
        raise SystemExit(f"{path} does not contain a trades list")
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        equity_scale = max(float(row.get("equity_scale") or 1.0), 1e-12)
        reason_codes = [str(item) for item in row.get("reason_codes", []) if item is not None]
        intent_scale = candidate_intent_scale(row, reason_codes=reason_codes)
        route = infer_route(source, row)
        features = candidate_features_from_row(row, reason_codes=reason_codes, route=route)
        features.setdefault("intent_scale", round(intent_scale, 8))
        if intent_scale < 1.0:
            features.setdefault("trade_quality_scale", round(intent_scale, 8))
        candidates.append(
            FusionCandidate(
                source=source,
                symbol=str(row.get("symbol") or "").upper(),
                side=str(row.get("side") or ""),
                entry_time=str(row.get("entry_time") or ""),
                exit_time=str(row.get("exit_time") or ""),
                entry_price=float(row.get("entry_price") or 0.0),
                exit_price=float(row.get("exit_price") or 0.0),
                notional_usdt=float(row.get("notional_usdt") or 0.0) / equity_scale * intent_scale,
                gross_pnl_usdt=float(row.get("gross_pnl_usdt") or 0.0) / equity_scale * intent_scale,
                fees_usdt=float(row.get("fees_usdt") or 0.0) / equity_scale * intent_scale,
                slippage_usdt=float(row.get("slippage_usdt") or 0.0) / equity_scale * intent_scale,
                net_pnl_usdt=float(row.get("net_pnl_usdt") or 0.0) / equity_scale * intent_scale,
                exit_reason=str(row.get("exit_reason") or ""),
                reason_codes=reason_codes,
                source_file=str(path),
                strategy_leg=route["strategy_leg"],
                regime_label=route["regime_label"],
                regime_confidence=route["regime_confidence"],
                regime_reason_codes=route["regime_reason_codes"],
                allowed_strategy_legs=route["allowed_strategy_legs"],
                route_decision=route["route_decision"],
                route_shadow_only=route["route_shadow_only"],
                intent_scale=intent_scale,
                features=features,
            )
        )
    return [item for item in candidates if item.symbol and item.entry_time and item.exit_time]


def candidate_intent_scale(row: dict[str, Any], *, reason_codes: list[str]) -> float:
    scale = 1.0
    for key in ("trade_quality_scale",):
        value = row.get(key)
        if value is None:
            continue
        try:
            scale *= max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            continue
    if "trade_quality_scale" not in row:
        scale *= inferred_micro_quality_scale(reason_code_features(reason_codes))
    return scale


def inferred_micro_quality_scale(features: dict[str, Any]) -> float:
    if "signal_mode" not in features or str(features.get("signal_mode")) != "micro_smart_grid":
        return 1.0
    stable_width = _feature_float(features, "stable_width_percent", math.inf)
    if stable_width < 0.22:
        return 0.0
    scale = 1.0
    if str(features.get("edge_reversal_reason") or "") in {
        "upper_extreme_too_fresh",
        "lower_extreme_too_fresh",
        "entry_path_too_directional",
    }:
        return 0.0
    basket_weight = _feature_float(features, "basket_size_weight", 0.75)
    if "basket_size_weight" in features:
        if basket_weight > 1.0:
            scale *= 0.25
        elif basket_weight > 0.75:
            scale *= 0.55
    if _feature_float(features, "basket_fill_count", 1.0) > 1.0:
        scale *= 0.55
    if "wick_avg_net_percent" in features:
        wick_avg = _feature_float(features, "wick_avg_net_percent", 0.0)
        if wick_avg <= -0.04:
            scale *= 0.35
        elif wick_avg < 0.04:
            scale *= 0.75
    wick_stop = _feature_float(features, "wick_stop_rate", 0.0)
    if wick_stop > 0.45:
        scale *= 0.35
    elif wick_stop > 0.22:
        scale *= 0.65
    drift = _feature_float(features, "drift_to_width", 0.0)
    if drift > 0.85:
        scale *= 0.55
    elif drift > 0.75:
        scale *= 0.75
    recent_drift = _feature_float(features, "recent_drift_to_width", 0.0)
    if recent_drift > 1.0:
        scale *= 0.40
    elif recent_drift > 0.80:
        scale *= 0.65
    return clamp(scale, 0.0, 1.0)


def _feature_float(features: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(features.get(key, default))
    except (TypeError, ValueError):
        return default


def infer_route(source: str, row: dict[str, Any]) -> dict[str, Any]:
    features = extract_features(row)
    reason_codes = [str(item) for item in row.get("reason_codes", []) if item is not None]
    strategy_leg = normalize_strategy_leg(
        str(
            features.get("strategy_leg")
            or row.get("strategy_leg")
            or leg_from_reason_codes(reason_codes)
            or leg_from_source(source)
        )
    )
    regime_label = str(features.get("regime_label") or row.get("regime_label") or "").upper()
    if regime_label not in {TREND, RANGE, CHOP}:
        regime_label = inferred_regime_from_leg_or_source(strategy_leg, source)
    allowed = features.get("allowed_strategy_legs") or row.get("allowed_strategy_legs") or allowed_legs_for_regime(regime_label)
    if not isinstance(allowed, list):
        allowed = [str(allowed)]
    route_decision = str(features.get("route_decision") or row.get("route_decision") or "")
    if not route_decision:
        route_decision = ALLOW if strategy_leg in allowed else SKIP_CHOP if regime_label == CHOP else "skip_leg_mismatch"
    reason_values = features.get("regime_reason_codes") or row.get("regime_reason_codes") or [f"replay_inferred:{regime_label.lower()}"]
    if not isinstance(reason_values, list):
        reason_values = [str(reason_values)]
    confidence = float(features.get("regime_confidence") or row.get("regime_confidence") or replay_regime_confidence(regime_label))
    return {
        "strategy_leg": strategy_leg,
        "regime_label": regime_label,
        "regime_confidence": round(confidence, 4),
        "regime_reason_codes": [str(item) for item in reason_values],
        "allowed_strategy_legs": [normalize_strategy_leg(str(item)) for item in allowed],
        "route_decision": route_decision,
        "route_shadow_only": truthy(features.get("route_shadow_only", row.get("route_shadow_only", True))),
    }


def candidate_features_from_row(row: dict[str, Any], *, reason_codes: list[str], route: dict[str, Any]) -> dict[str, Any]:
    features = dict(extract_features(row))
    for key, value in reason_code_features(reason_codes).items():
        features.setdefault(key, value)
    for key in (
        "mfe_percent",
        "mae_percent",
        "hold_seconds",
        "realized_r",
        "initial_risk_usdt",
        "initial_margin_usdt",
        "assumed_leverage",
        "pullback_scale_cap",
        "symbol_quality_scale",
        "symbol_quality_reason",
        "trade_quality_scale",
        "trade_quality_reasons",
    ):
        if key in row:
            features.setdefault(key, row.get(key))
    features.setdefault("strategy_leg", route["strategy_leg"])
    features.setdefault("regime_label", route["regime_label"])
    features.setdefault("regime_confidence", route["regime_confidence"])
    features.setdefault("regime_reason_codes", route["regime_reason_codes"])
    features.setdefault("allowed_strategy_legs", route["allowed_strategy_legs"])
    features.setdefault("route_decision", route["route_decision"])
    features.setdefault("route_shadow_only", route["route_shadow_only"])
    return features


def reason_code_features(reason_codes: list[str]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for reason in reason_codes:
        if ":" not in reason:
            continue
        key, value = reason.split(":", 1)
        normalized_key = key.strip().replace("-", "_")
        if not normalized_key:
            continue
        features[normalized_key] = parse_reason_value(value)
    return features


def parse_reason_value(value: str) -> Any:
    stripped = str(value).strip()
    if stripped in {"True", "False"}:
        return stripped == "True"
    try:
        if stripped and all(char in "-+0123456789" for char in stripped):
            return int(stripped)
        return float(stripped)
    except ValueError:
        return stripped


def extract_features(row: dict[str, Any]) -> dict[str, Any]:
    features = row.get("features")
    if isinstance(features, dict):
        return features
    candidate = row.get("candidate")
    if isinstance(candidate, dict):
        candidate_features = candidate.get("features")
        if isinstance(candidate_features, dict):
            return candidate_features
    setup = row.get("setup")
    if isinstance(setup, dict):
        price_basis = setup.get("price_basis")
        if isinstance(price_basis, dict):
            route = price_basis.get("regime_router")
            if isinstance(route, dict):
                return route
    return {}


def leg_from_reason_codes(reason_codes: list[str]) -> str | None:
    for reason in reason_codes:
        if reason.startswith("strategy_leg:"):
            return reason.split(":", 1)[1]
        lowered = reason.lower()
        if "micro_grid" in lowered:
            return MICRO_GRID_LEG
        if "orderly_range" in lowered or "range_reversion" in lowered:
            return RANGE_REVERSION_LEG
    return None


def leg_from_source(source: str) -> str:
    lowered = source.lower()
    if "micro" in lowered or "scalp" in lowered or "grid" in lowered:
        return MICRO_GRID_LEG
    if "range" in lowered or "reversion" in lowered:
        return RANGE_REVERSION_LEG
    return TREND_LEG


def inferred_regime_from_leg_or_source(strategy_leg: str, source: str) -> str:
    if strategy_leg in {MICRO_GRID_LEG, RANGE_REVERSION_LEG}:
        return RANGE
    lowered = source.lower()
    if "chop" in lowered:
        return CHOP
    return TREND


def replay_regime_confidence(regime_label: str) -> float:
    if regime_label in {TREND, RANGE}:
        return 0.6
    return 0.5


def normalize_strategy_leg(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"micro", "microgrid", "grid", "scalp", "scalping"}:
        return MICRO_GRID_LEG
    if normalized in {"range", "orderly_range", "range_revert", "range_reversion", "orderly_range_reversion"}:
        return RANGE_REVERSION_LEG
    if normalized in {"", "trend", "normal", "quant", "quant_setup"}:
        return TREND_LEG
    return normalized


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def candidate_to_row(candidate: FusionCandidate) -> dict[str, Any]:
    return {
        "source": candidate.source,
        "symbol": candidate.symbol,
        "side": candidate.side,
        "exit_reason": candidate.exit_reason,
        "strategy_leg": candidate.strategy_leg,
        "regime_label": candidate.regime_label,
        "route_decision": candidate.route_decision,
        "intent_scale": candidate.intent_scale,
        "features": dict(candidate.features),
        "fees_usdt": candidate.fees_usdt,
        "net_pnl_usdt": candidate.net_pnl_usdt,
    }


def attribution_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "regime": summarize_by(rows, "regime_label"),
        "regime_leg": summarize_by(rows, "regime_label", "strategy_leg"),
        "regime_leg_symbol_side_exit": summarize_by(
            rows,
            "regime_label",
            "strategy_leg",
            "symbol",
            "side",
            "exit_reason",
        ),
        "route_decision_counts": count_by(rows, "route_decision"),
    }


def replay_fusion(
    candidates: list[FusionCandidate],
    *,
    initial_capital: float,
    max_open_positions: int,
    max_symbol_open_positions: int,
    daily_loss_fraction: float,
    quality_filter_enabled: bool,
    quality_lookback_hours: float,
    quality_min_samples: int,
    quality_min_profit_factor: float,
    quality_max_stop_rate: float,
    quality_min_scale: float,
    source_quality_filter_enabled: bool,
    source_quality_min_samples: int,
    source_quality_min_profit_factor: float,
    source_quality_max_stop_rate: float,
    source_quality_min_scale: float,
    regime_router_enabled: bool = False,
    regime_router_enforced: bool = False,
) -> dict[str, Any]:
    equity = initial_capital
    peak = initial_capital
    max_drawdown = 0.0
    daily_pnl: dict[str, float] = {}
    accepted: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    skip_counts = {
        "daily_loss": 0,
        "concurrency": 0,
        "symbol_conflict": 0,
        "quality": 0,
        "source_quality": 0,
        "intent_scale": 0,
        "regime_route": 0,
        "invalid": 0,
    }
    for candidate in sorted(candidates, key=lambda item: (parse_iso_ms(item.entry_time), source_priority(item.source), item.symbol)):
        entry_ms = parse_iso_ms(candidate.entry_time)
        exit_ms = parse_iso_ms(candidate.exit_time)
        if exit_ms <= entry_ms or equity <= 0:
            skip_counts["invalid"] += 1
            continue
        equity, peak, max_drawdown = close_due_positions(open_positions, accepted, equity, peak, max_drawdown, entry_ms, daily_pnl)

        if daily_loss_fraction > 0:
            day = candidate.entry_time[:10]
            if abs(min(daily_pnl.get(day, 0.0), 0.0)) >= equity * daily_loss_fraction:
                skip_counts["daily_loss"] += 1
                continue
        if len(open_positions) >= max_open_positions:
            skip_counts["concurrency"] += 1
            continue
        if count_open_symbol(open_positions, candidate.symbol) >= max_symbol_open_positions:
            skip_counts["symbol_conflict"] += 1
            continue
        if regime_router_enabled and regime_router_enforced and candidate.route_decision != ALLOW:
            skip_counts["regime_route"] += 1
            continue
        if candidate.intent_scale <= 0:
            skip_counts["intent_scale"] += 1
            continue

        quality_scale, quality_reason = rolling_quality_scale(
            accepted,
            ("source", "symbol"),
            (candidate.source, candidate.symbol),
            entry_ms,
            enabled=quality_filter_enabled,
            lookback_hours=quality_lookback_hours,
            min_samples=quality_min_samples,
            min_profit_factor=quality_min_profit_factor,
            max_stop_rate=quality_max_stop_rate,
            min_scale=quality_min_scale,
        )
        if quality_scale <= 0:
            skip_counts["quality"] += 1
            continue
        source_scale, source_reason = rolling_quality_scale(
            accepted,
            ("source",),
            (candidate.source,),
            entry_ms,
            enabled=source_quality_filter_enabled,
            lookback_hours=quality_lookback_hours,
            min_samples=source_quality_min_samples,
            min_profit_factor=source_quality_min_profit_factor,
            max_stop_rate=source_quality_max_stop_rate,
            min_scale=source_quality_min_scale,
        )
        if source_scale <= 0:
            skip_counts["source_quality"] += 1
            continue

        equity_scale = max(equity / initial_capital, 0.0) * quality_scale * source_scale
        record = scaled_record(
            candidate,
            scale=equity_scale,
            equity_before=equity,
            quality_scale=quality_scale,
            source_quality_scale=source_scale,
            quality_reason=quality_reason,
            source_quality_reason=source_reason,
        )
        open_positions.append({"exit_ms": exit_ms, "record": record})

    equity, peak, max_drawdown = close_due_positions(open_positions, accepted, equity, peak, max_drawdown, math.inf, daily_pnl)
    return {"summary": summarize(accepted, initial_capital, max_drawdown, skip_counts), "trades": accepted}


def source_priority(source: str) -> int:
    lowered = source.lower()
    if "trend" in lowered or "lana" in lowered:
        return 0
    if "micro" in lowered or "scalp" in lowered:
        return 1
    return 2


def close_due_positions(
    open_positions: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    equity: float,
    peak: float,
    max_drawdown: float,
    current_ms: float,
    daily_pnl: dict[str, float],
) -> tuple[float, float, float]:
    due = sorted(
        [position for position in open_positions if position["exit_ms"] <= current_ms],
        key=lambda item: (item["exit_ms"], item["record"]["source"], item["record"]["symbol"]),
    )
    for position in due:
        record = position["record"]
        equity += float(record["net_pnl_usdt"])
        day = str(record["exit_time"])[:10]
        daily_pnl[day] = daily_pnl.get(day, 0.0) + float(record["net_pnl_usdt"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        record["equity_after_exit_usdt"] = round(equity, 8)
        record["drawdown_after_exit_usdt"] = round(peak - equity, 8)
        accepted.append(record)
        open_positions.remove(position)
    return equity, peak, max_drawdown


def count_open_symbol(open_positions: list[dict[str, Any]], symbol: str) -> int:
    return sum(1 for position in open_positions if position["record"].get("symbol") == symbol)


def rolling_quality_scale(
    accepted: list[dict[str, Any]],
    keys: tuple[str, ...],
    values: tuple[str, ...],
    entry_ms: int,
    *,
    enabled: bool,
    lookback_hours: float,
    min_samples: int,
    min_profit_factor: float,
    max_stop_rate: float,
    min_scale: float,
) -> tuple[float, str]:
    if not enabled:
        return 1.0, "disabled"
    lookback_ms = max(0.0, lookback_hours) * 60.0 * 60.0 * 1000.0
    recent = [
        trade
        for trade in accepted
        if all(str(trade.get(key)) == value for key, value in zip(keys, values, strict=True))
        and entry_ms - parse_iso_ms(str(trade.get("exit_time"))) <= lookback_ms
    ]
    min_samples = max(1, min_samples)
    label = "+".join(f"{key}={value}" for key, value in zip(keys, values, strict=True))
    if len(recent) < min_samples:
        return 1.0, f"warming_up:{label};n={len(recent)}/{min_samples}"
    gross_profit = sum(max(0.0, float(trade.get("net_pnl_usdt") or 0.0)) for trade in recent)
    gross_loss = sum(max(0.0, -float(trade.get("net_pnl_usdt") or 0.0)) for trade in recent)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf
    stop_rate = sum(1 for trade in recent if str(trade.get("exit_reason")) in {"stop_loss", "same_bar_stop"}) / len(recent)
    win_rate = sum(1 for trade in recent if float(trade.get("net_pnl_usdt") or 0.0) > 0) / len(recent)
    stats = f"{label};n={len(recent)};pf={round(profit_factor, 4)};stop_rate={round(stop_rate, 4)};win_rate={round(win_rate, 4)}"
    if profit_factor >= min_profit_factor and stop_rate <= max_stop_rate:
        return 1.0, f"healthy:{stats}"
    return clamp(min_scale, 0.0, 1.0), f"degraded:{stats}"


def scaled_record(
    candidate: FusionCandidate,
    *,
    scale: float,
    equity_before: float,
    quality_scale: float,
    source_quality_scale: float,
    quality_reason: str,
    source_quality_reason: str,
) -> dict[str, Any]:
    return {
        "source": candidate.source,
        "source_file": candidate.source_file,
        "symbol": candidate.symbol,
        "strategy_leg": candidate.strategy_leg,
        "regime_label": candidate.regime_label,
        "regime_confidence": candidate.regime_confidence,
        "regime_reason_codes": list(candidate.regime_reason_codes or []),
        "allowed_strategy_legs": list(candidate.allowed_strategy_legs or []),
        "route_decision": candidate.route_decision,
        "route_shadow_only": candidate.route_shadow_only,
        "intent_scale": round(candidate.intent_scale, 8),
        "side": candidate.side,
        "entry_time": candidate.entry_time,
        "exit_time": candidate.exit_time,
        "entry_price": candidate.entry_price,
        "exit_price": candidate.exit_price,
        "notional_usdt": round(candidate.notional_usdt * scale, 8),
        "gross_pnl_usdt": round(candidate.gross_pnl_usdt * scale, 8),
        "fees_usdt": round(candidate.fees_usdt * scale, 8),
        "slippage_usdt": round(candidate.slippage_usdt * scale, 8),
        "net_pnl_usdt": round(candidate.net_pnl_usdt * scale, 8),
        "exit_reason": candidate.exit_reason,
        "reason_codes": list(candidate.reason_codes),
        "features": dict(candidate.features),
        "equity_before_entry_usdt": round(equity_before, 8),
        "equity_scale": round(scale, 8),
        "quality_scale": round(quality_scale, 8),
        "source_quality_scale": round(source_quality_scale, 8),
        "quality_reason": quality_reason,
        "source_quality_reason": source_quality_reason,
    }


def summarize(accepted: list[dict[str, Any]], initial_capital: float, max_drawdown: float, skip_counts: dict[str, int]) -> dict[str, Any]:
    net = sum(float(item["net_pnl_usdt"]) for item in accepted)
    wins = sum(1 for item in accepted if float(item["net_pnl_usdt"]) > 0)
    losses = sum(1 for item in accepted if float(item["net_pnl_usdt"]) < 0)
    gross_profit = sum(float(item["net_pnl_usdt"]) for item in accepted if float(item["net_pnl_usdt"]) > 0)
    gross_loss = abs(sum(float(item["net_pnl_usdt"]) for item in accepted if float(item["net_pnl_usdt"]) < 0))
    final = initial_capital + net
    return {
        "initial_capital_usdt": round(initial_capital, 8),
        "final_capital_usdt": round(final, 8),
        "net_pnl_usdt": round(net, 8),
        "return_percent": round((final / initial_capital - 1.0) * 100.0, 8) if initial_capital else 0.0,
        "trade_count": len(accepted),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(accepted), 8) if accepted else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else ("inf" if gross_profit else None),
        "expectancy_usdt": round(net / len(accepted), 8) if accepted else 0.0,
        "fees_usdt": round(sum(float(item["fees_usdt"]) for item in accepted), 8),
        "slippage_usdt": round(sum(float(item["slippage_usdt"]) for item in accepted), 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "max_drawdown_percent_of_initial": round((max_drawdown / initial_capital) * 100.0, 8) if initial_capital else 0.0,
        "skip_counts": dict(skip_counts),
        "exit_reason_counts": count_by(accepted, "exit_reason"),
        "side_counts": count_by(accepted, "side"),
        "source_counts": count_by(accepted, "source"),
        "symbol_counts": count_by(accepted, "symbol"),
        "source_summary": summarize_by(accepted, "source"),
        "source_symbol_summary": summarize_by(accepted, "source", "symbol"),
        "regime_summary": summarize_by(accepted, "regime_label"),
        "regime_leg_summary": summarize_by(accepted, "regime_label", "strategy_leg"),
        "regime_leg_symbol_side_exit_summary": summarize_by(
            accepted,
            "regime_label",
            "strategy_leg",
            "symbol",
            "side",
            "exit_reason",
        ),
    }


def summarize_by(rows: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = "|".join(str(row.get(item)) for item in keys)
        buckets.setdefault(key, []).append(row)
    summary: dict[str, Any] = {}
    for key, items in sorted(buckets.items()):
        net = sum(float(item["net_pnl_usdt"]) for item in items)
        gp = sum(float(item["net_pnl_usdt"]) for item in items if float(item["net_pnl_usdt"]) > 0)
        gl = abs(sum(float(item["net_pnl_usdt"]) for item in items if float(item["net_pnl_usdt"]) < 0))
        wins = sum(1 for item in items if float(item["net_pnl_usdt"]) > 0)
        summary[key] = {
            "trade_count": len(items),
            "wins": wins,
            "losses": sum(1 for item in items if float(item["net_pnl_usdt"]) < 0),
            "win_rate": round(wins / len(items), 8) if items else 0.0,
            "net_pnl_usdt": round(net, 8),
            "profit_factor": round(gp / gl, 8) if gl else ("inf" if gp else None),
            "fees_usdt": round(sum(float(item["fees_usdt"]) for item in items), 8),
        }
    return summary


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def parse_iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


if __name__ == "__main__":
    raise SystemExit(main())
