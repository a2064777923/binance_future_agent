"""Learn generic minute-level futures features from future path labels.

This is intentionally broader than the orderly-range research script. It does
not require a hand-authored market shape before a candidate can exist. Every
symbol/minute can produce both long and short candidates; the training phase
then learns which feature bins had favorable future paths.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any

from bfa.backtest.models import BacktestBar


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_orderly_range_research import (  # noqa: E402
    ONE_MINUTE_MS,
    coverage_summary,
    load_many_symbol_klines,
    parse_symbols,
    percent_delta,
    resolve_top_symbols,
    split_validation_bars,
)


FEATURE_NAMES = [
    "side_momentum_1m",
    "side_momentum_3m",
    "side_momentum_5m",
    "side_momentum_15m",
    "abs_momentum_5m",
    "abs_momentum_15m",
    "abs_momentum_60m",
    "range_width_15m",
    "range_width_60m",
    "path_efficiency_15m",
    "path_efficiency_60m",
    "side_reversion_edge_15m",
    "side_reversion_edge_60m",
    "side_breakout_edge_15m",
    "side_breakout_edge_60m",
    "realized_volatility_15m",
    "volume_ratio_3_30",
    "volume_cv_30m",
    "side_taker_pressure_15m",
    "last_body_percent",
    "side_rejection_wick_percent",
    "side_breakout_wick_percent",
    "hour_utc",
]


@dataclass(frozen=True)
class FuturePathLabel:
    horizon_minutes: int
    mfe_percent: float
    mae_percent: float
    close_return_percent: float
    first_hit: str
    first_favorable_minutes: int | None
    first_adverse_minutes: int | None
    opportunity_score_percent: float
    clean_win: bool


@dataclass(frozen=True)
class FeatureSample:
    symbol: str
    side: str
    signal_index: int
    entry_index: int
    signal_time: str
    entry_time: str
    entry_price: float
    features: dict[str, float]
    label: FuturePathLabel


@dataclass(frozen=True)
class BinStat:
    count: int
    mean_score: float
    win_rate: float


@dataclass(frozen=True)
class FeatureScorecard:
    feature_names: list[str]
    bin_edges: dict[str, list[float]]
    bin_stats: dict[str, BinStat]
    global_mean_score: float
    min_bin_samples: int
    prior_samples: float


@dataclass(frozen=True)
class LearnedTradingProfile:
    lookback_minutes: int
    label_horizon_minutes: int
    score_threshold: float
    target_percent: float
    stop_percent: float
    max_hold_minutes: int
    fee_bps: float
    slippage_bps: float
    enabled: bool = True

    @property
    def round_trip_cost_percent(self) -> float:
        return 2.0 * (max(self.fee_bps, 0.0) + max(self.slippage_bps, 0.0)) / 100.0


@dataclass(frozen=True)
class RangeRegimeConfig:
    enabled: bool = True
    min_width_60m: float = 0.45
    max_width_60m: float = 6.0
    min_width_cost_ratio: float = 3.0
    max_path_efficiency_60m: float = 0.58
    max_abs_return_60m: float = 1.8
    max_volume_cv_30m: float = 2.5
    max_volume_ratio_3_30: float = 4.0


@dataclass(frozen=True)
class ScoredCandidate:
    sample: FeatureSample
    score: float
    contribution_count: int


@dataclass(frozen=True)
class GenericPosition:
    candidate: ScoredCandidate
    entry_index: int
    entry_time: str
    entry_price: float
    quantity: float
    notional_usdt: float
    best_price: float
    worst_price: float
    fees_entry_usdt: float
    slippage_entry_usdt: float


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--symbols", help="comma-separated symbols; otherwise top USD-M symbols are fetched")
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--min-24h-quote-volume", type=float, default=20_000_000.0)
    parser.add_argument("--cache-dir", default="runtime/klines-cache")
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=30.0)
    parser.add_argument("--max-open-positions", type=int, default=2)
    parser.add_argument("--max-new-entries-per-minute", type=int, default=1)
    parser.add_argument("--risk-per-trade-fraction", type=float, default=0.012)
    parser.add_argument("--max-notional-fraction", type=float, default=0.9)
    parser.add_argument("--lookback-minutes", type=int, default=60)
    parser.add_argument("--label-horizon-minutes", type=int, default=30)
    parser.add_argument("--training-stride-minutes", type=int, default=5)
    parser.add_argument("--test-stride-minutes", type=int, default=1)
    parser.add_argument("--validation-days", type=int, default=5)
    parser.add_argument("--min-validation-trades", type=int, default=25)
    parser.add_argument("--max-side-imbalance", type=float, default=0.85)
    parser.add_argument("--bin-count", type=int, default=8)
    parser.add_argument("--min-bin-samples", type=int, default=40)
    parser.add_argument("--score-prior-samples", type=float, default=30.0)
    parser.add_argument("--score-threshold-percentiles", default="60,70,80,85,90,95")
    parser.add_argument("--target-grid", default="0.25,0.4,0.6,0.9")
    parser.add_argument("--stop-grid", default="0.25,0.4,0.6,0.9")
    parser.add_argument("--hold-grid", default="10,20,45,60")
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=3.0)
    parser.add_argument("--max-samples-per-symbol", type=int, default=0)
    parser.add_argument("--candidate-mode", choices=("all", "range_edge"), default="range_edge")
    parser.add_argument("--candidate-edge-zone-percent", type=float, default=30.0)
    parser.add_argument("--range-regime", choices=("on", "off"), default="on")
    parser.add_argument("--range-min-width-60m", type=float, default=0.45)
    parser.add_argument("--range-max-width-60m", type=float, default=6.0)
    parser.add_argument("--range-min-width-cost-ratio", type=float, default=3.0)
    parser.add_argument("--range-max-path-efficiency-60m", type=float, default=0.58)
    parser.add_argument("--range-max-abs-return-60m", type=float, default=1.8)
    parser.add_argument("--range-max-volume-cv-30m", type=float, default=2.5)
    parser.add_argument("--range-max-volume-ratio-3-30", type=float, default=4.0)
    args = parser.parse_args()

    train_start = date.fromisoformat(args.train_start)
    train_end = date.fromisoformat(args.train_end)
    test_start = date.fromisoformat(args.test_start)
    test_end = date.fromisoformat(args.test_end)
    if train_end < train_start or test_end < test_start:
        raise SystemExit("end dates must be on or after start dates")

    symbols = parse_symbols(args.symbols) if args.symbols else resolve_top_symbols(args.top_n, args.min_24h_quote_volume)
    cache_dir = Path(args.cache_dir)
    train_bars = load_many_symbol_klines(symbols, train_start, train_end, cache_dir)
    test_bars = load_many_symbol_klines(symbols, test_start, test_end, cache_dir)
    fit_bars, validation_bars = split_validation_bars(
        train_bars,
        train_end=train_end,
        validation_days=args.validation_days,
    )
    regime = RangeRegimeConfig(
        enabled=args.range_regime == "on",
        min_width_60m=args.range_min_width_60m,
        max_width_60m=args.range_max_width_60m,
        min_width_cost_ratio=args.range_min_width_cost_ratio,
        max_path_efficiency_60m=args.range_max_path_efficiency_60m,
        max_abs_return_60m=args.range_max_abs_return_60m,
        max_volume_cv_30m=args.range_max_volume_cv_30m,
        max_volume_ratio_3_30=args.range_max_volume_ratio_3_30,
    )

    fit_samples = build_labeled_samples(
        fit_bars,
        lookback_minutes=args.lookback_minutes,
        horizon_minutes=args.label_horizon_minutes,
        stride=max(1, args.training_stride_minutes),
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        max_samples_per_symbol=args.max_samples_per_symbol,
        regime=regime,
        candidate_mode=args.candidate_mode,
        candidate_edge_zone_percent=args.candidate_edge_zone_percent,
    )
    validation_samples = build_labeled_samples(
        validation_bars,
        lookback_minutes=args.lookback_minutes,
        horizon_minutes=args.label_horizon_minutes,
        stride=max(1, args.training_stride_minutes),
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        max_samples_per_symbol=args.max_samples_per_symbol,
        regime=regime,
        candidate_mode=args.candidate_mode,
        candidate_edge_zone_percent=args.candidate_edge_zone_percent,
    )
    test_samples = build_labeled_samples(
        test_bars,
        lookback_minutes=args.lookback_minutes,
        horizon_minutes=args.label_horizon_minutes,
        stride=max(1, args.test_stride_minutes),
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        max_samples_per_symbol=0,
        regime=regime,
        candidate_mode=args.candidate_mode,
        candidate_edge_zone_percent=args.candidate_edge_zone_percent,
    )

    scorecard = train_scorecard(
        fit_samples,
        feature_names=FEATURE_NAMES,
        bin_count=args.bin_count,
        min_bin_samples=args.min_bin_samples,
        prior_samples=args.score_prior_samples,
    )
    threshold_candidates = threshold_candidates_from_scores(
        score_samples(validation_samples, scorecard),
        parse_float_list(args.score_threshold_percentiles),
    )
    profile, validation_leaderboard = learn_trading_profile(
        validation_samples,
        validation_bars,
        scorecard=scorecard,
        base_profile=LearnedTradingProfile(
            lookback_minutes=args.lookback_minutes,
            label_horizon_minutes=args.label_horizon_minutes,
            score_threshold=scorecard.global_mean_score,
            target_percent=0.4,
            stop_percent=0.4,
            max_hold_minutes=20,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            enabled=True,
        ),
        threshold_candidates=threshold_candidates,
        target_grid=parse_float_list(args.target_grid),
        stop_grid=parse_float_list(args.stop_grid),
        hold_grid=[int(value) for value in parse_float_list(args.hold_grid)],
        min_validation_trades=args.min_validation_trades,
        max_side_imbalance=args.max_side_imbalance,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        max_new_entries_per_minute=args.max_new_entries_per_minute,
        risk_per_trade_fraction=args.risk_per_trade_fraction,
        max_notional_fraction=args.max_notional_fraction,
    )
    test_result = run_scored_portfolio_backtest(
        test_samples,
        test_bars,
        scorecard=scorecard,
        profile=profile,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        max_new_entries_per_minute=args.max_new_entries_per_minute,
        risk_per_trade_fraction=args.risk_per_trade_fraction,
        max_notional_fraction=args.max_notional_fraction,
    )
    payload = {
        "schema": "bfa_feature_label_research_v1",
        "method": {
            "data_source": "Binance USD-M public daily 1m kline archives",
            "candidate_generation": "every eligible symbol/minute emits both long and short candidates; no range-shape gate is required",
            "label": "future path MFE/MAE/close-return over the label horizon, net of estimated round-trip cost",
            "model": "side-aware quantile-bin scorecard trained on fit samples and selected on validation portfolio replay",
            "test_replay": "minute-by-minute multi-symbol portfolio replay using learned score threshold, target, stop, and max hold",
        },
        "symbols": symbols,
        "train_window": {"start_date": train_start.isoformat(), "end_date": train_end.isoformat()},
        "test_window": {"start_date": test_start.isoformat(), "end_date": test_end.isoformat()},
        "sample_counts": {
            "fit": len(fit_samples),
            "validation": len(validation_samples),
            "test": len(test_samples),
        },
        "profile": asdict(profile),
        "range_regime": asdict(regime),
        "candidate_filter": {
            "mode": args.candidate_mode,
            "edge_zone_percent": args.candidate_edge_zone_percent,
        },
        "scorecard": scorecard_summary(scorecard),
        "fit_label_summary": label_summary(fit_samples),
        "validation_label_summary": label_summary(validation_samples),
        "validation_leaderboard": validation_leaderboard[:20],
        "test_summary": test_result["summary"],
        "test_trades": test_result["trades"],
        "test_selection_summary": selection_summary(score_samples(test_samples, scorecard), profile.score_threshold),
        "regime_diagnostics": {
            "fit": regime_diagnostics(fit_bars, lookback_minutes=args.lookback_minutes, stride=max(1, args.training_stride_minutes), regime=regime, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
            "validation": regime_diagnostics(validation_bars, lookback_minutes=args.lookback_minutes, stride=max(1, args.training_stride_minutes), regime=regime, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
            "test": regime_diagnostics(test_bars, lookback_minutes=args.lookback_minutes, stride=max(1, args.test_stride_minutes), regime=regime, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
        },
        "coverage": {
            "fit": coverage_summary(fit_bars),
            "validation": coverage_summary(validation_bars),
            "train": coverage_summary(train_bars),
            "test": coverage_summary(test_bars),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def build_labeled_samples(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    lookback_minutes: int,
    horizon_minutes: int,
    stride: int,
    fee_bps: float,
    slippage_bps: float,
    max_samples_per_symbol: int,
    regime: RangeRegimeConfig | None = None,
    candidate_mode: str = "range_edge",
    candidate_edge_zone_percent: float = 30.0,
) -> list[FeatureSample]:
    samples: list[FeatureSample] = []
    for symbol, bars in bars_by_symbol.items():
        symbol_count = 0
        end = len(bars) - horizon_minutes - 1
        for signal_index in range(max(lookback_minutes, 60), max(0, end), max(1, stride)):
            features_base = feature_snapshot(bars, signal_index)
            if features_base is None:
                continue
            if regime is not None and range_regime_rejection_reasons(
                features_base,
                regime,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            ):
                continue
            allowed_sides = candidate_sides(features_base, mode=candidate_mode, edge_zone_percent=candidate_edge_zone_percent)
            if not allowed_sides:
                continue
            entry_index = signal_index + 1
            if entry_index >= len(bars):
                continue
            for side in allowed_sides:
                features = side_features(features_base, side)
                label = future_path_label(
                    bars,
                    entry_index=entry_index,
                    side=side,
                    horizon_minutes=horizon_minutes,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                )
                if label is None:
                    continue
                samples.append(
                    FeatureSample(
                        symbol=symbol,
                        side=side,
                        signal_index=signal_index,
                        entry_index=entry_index,
                        signal_time=bars[signal_index].close_time_iso,
                        entry_time=bars[entry_index].open_time_iso,
                        entry_price=bars[entry_index].open,
                        features=features,
                        label=label,
                    )
                )
                symbol_count += 1
            if max_samples_per_symbol > 0 and symbol_count >= max_samples_per_symbol:
                break
    return samples


def candidate_sides(
    features: dict[str, float],
    *,
    mode: str,
    edge_zone_percent: float,
) -> tuple[str, ...]:
    if mode == "all":
        return ("long", "short")
    if mode != "range_edge":
        return ()
    close_position = features["close_position_60m"]
    sides: list[str] = []
    zone = max(0.0, min(50.0, edge_zone_percent))
    if close_position <= zone:
        sides.append("long")
    if close_position >= 100.0 - zone:
        sides.append("short")
    return tuple(sides)


def feature_snapshot(bars: list[BacktestBar], index: int) -> dict[str, float] | None:
    if index < 60 or index >= len(bars):
        return None
    current = bars[index]
    if current.close <= 0:
        return None
    window_15 = bars[index - 14 : index + 1]
    window_30 = bars[index - 29 : index + 1]
    window_60 = bars[index - 59 : index + 1]
    values = {
        "return_1m": return_over_bars(bars, index, 1),
        "return_3m": return_over_bars(bars, index, 3),
        "return_5m": return_over_bars(bars, index, 5),
        "return_15m": return_over_bars(bars, index, 15),
        "return_60m": return_over_bars(bars, index, 60),
        "range_width_15m": range_width_percent(window_15),
        "range_width_60m": range_width_percent(window_60),
        "close_position_15m": close_position_percent(window_15),
        "close_position_60m": close_position_percent(window_60),
        "path_efficiency_15m": path_efficiency(window_15),
        "path_efficiency_60m": path_efficiency(window_60),
        "realized_volatility_15m": realized_volatility_percent(window_15),
        "volume_ratio_3_30": volume_ratio(bars, index, recent=3, baseline=30),
        "volume_cv_30m": coefficient_of_variation([bar.quote_volume for bar in window_30 if bar.quote_volume > 0]) or 0.0,
        "taker_buy_ratio_15m": taker_buy_ratio(window_15),
        "last_body_percent": abs(current.close - current.open) / current.close * 100.0,
        "upper_wick_percent": upper_wick_percent(current),
        "lower_wick_percent": lower_wick_percent(current),
        "hour_utc": float((current.open_time // (60 * ONE_MINUTE_MS)) % 24),
    }
    if any(not math.isfinite(value) for value in values.values()):
        return None
    return values


def side_features(base: dict[str, float], side: str) -> dict[str, float]:
    sign = 1.0 if side == "long" else -1.0
    close_pos_15 = base["close_position_15m"]
    close_pos_60 = base["close_position_60m"]
    if side == "long":
        reversion_15 = 100.0 - close_pos_15
        reversion_60 = 100.0 - close_pos_60
        breakout_15 = close_pos_15
        breakout_60 = close_pos_60
        taker_pressure = base["taker_buy_ratio_15m"] - 0.5
        rejection_wick = base["lower_wick_percent"]
        breakout_wick = base["upper_wick_percent"]
    else:
        reversion_15 = close_pos_15
        reversion_60 = close_pos_60
        breakout_15 = 100.0 - close_pos_15
        breakout_60 = 100.0 - close_pos_60
        taker_pressure = 0.5 - base["taker_buy_ratio_15m"]
        rejection_wick = base["upper_wick_percent"]
        breakout_wick = base["lower_wick_percent"]
    return {
        "side_momentum_1m": sign * base["return_1m"],
        "side_momentum_3m": sign * base["return_3m"],
        "side_momentum_5m": sign * base["return_5m"],
        "side_momentum_15m": sign * base["return_15m"],
        "abs_momentum_5m": abs(base["return_5m"]),
        "abs_momentum_15m": abs(base["return_15m"]),
        "abs_momentum_60m": abs(base["return_60m"]),
        "range_width_15m": base["range_width_15m"],
        "range_width_60m": base["range_width_60m"],
        "path_efficiency_15m": base["path_efficiency_15m"],
        "path_efficiency_60m": base["path_efficiency_60m"],
        "side_reversion_edge_15m": reversion_15,
        "side_reversion_edge_60m": reversion_60,
        "side_breakout_edge_15m": breakout_15,
        "side_breakout_edge_60m": breakout_60,
        "realized_volatility_15m": base["realized_volatility_15m"],
        "volume_ratio_3_30": base["volume_ratio_3_30"],
        "volume_cv_30m": base["volume_cv_30m"],
        "side_taker_pressure_15m": taker_pressure,
        "last_body_percent": base["last_body_percent"],
        "side_rejection_wick_percent": rejection_wick,
        "side_breakout_wick_percent": breakout_wick,
        "hour_utc": base["hour_utc"],
    }


def future_path_label(
    bars: list[BacktestBar],
    *,
    entry_index: int,
    side: str,
    horizon_minutes: int,
    fee_bps: float,
    slippage_bps: float,
) -> FuturePathLabel | None:
    if entry_index >= len(bars):
        return None
    entry = bars[entry_index].open
    if entry <= 0:
        return None
    future = bars[entry_index : min(len(bars), entry_index + horizon_minutes)]
    if not future:
        return None
    if side == "long":
        mfe = (max(bar.high for bar in future) - entry) / entry * 100.0
        mae = (min(bar.low for bar in future) - entry) / entry * 100.0
        close_return = (future[-1].close - entry) / entry * 100.0
    else:
        mfe = (entry - min(bar.low for bar in future)) / entry * 100.0
        mae = (entry - max(bar.high for bar in future)) / entry * 100.0
        close_return = (entry - future[-1].close) / entry * 100.0
    cost = round_trip_cost_percent(fee_bps, slippage_bps)
    trigger = max(cost * 2.2, 0.25)
    first_favorable = first_threshold_hit_minutes(future, entry=entry, side=side, threshold_percent=trigger, favorable=True)
    first_adverse = first_threshold_hit_minutes(future, entry=entry, side=side, threshold_percent=trigger, favorable=False)
    if first_favorable is None and first_adverse is None:
        first_hit = "none"
    elif first_adverse is None or (first_favorable is not None and first_favorable < first_adverse):
        first_hit = "favorable"
    elif first_favorable is None or first_adverse < first_favorable:
        first_hit = "adverse"
    else:
        first_hit = "same_bar"
    first_hit_bonus = {"favorable": 0.35, "none": 0.0, "same_bar": -0.2, "adverse": -0.55}[first_hit]
    opportunity_score = max(close_return, mfe * 0.55) - abs(min(mae, 0.0)) * 0.85 - cost + first_hit_bonus
    clean_win = first_hit == "favorable" and mfe >= cost * 2.5 and abs(min(mae, 0.0)) <= max(mfe * 0.9, cost * 1.8)
    return FuturePathLabel(
        horizon_minutes=horizon_minutes,
        mfe_percent=round(mfe, 8),
        mae_percent=round(mae, 8),
        close_return_percent=round(close_return, 8),
        first_hit=first_hit,
        first_favorable_minutes=first_favorable,
        first_adverse_minutes=first_adverse,
        opportunity_score_percent=round(opportunity_score, 8),
        clean_win=clean_win,
    )


def range_regime_rejection_reasons(
    features: dict[str, float],
    regime: RangeRegimeConfig,
    *,
    fee_bps: float,
    slippage_bps: float,
) -> list[str]:
    if not regime.enabled:
        return []
    reasons: list[str] = []
    width = features["range_width_60m"]
    if width < regime.min_width_60m:
        reasons.append("range_too_narrow")
    if width > regime.max_width_60m:
        reasons.append("range_too_wide")
    cost = round_trip_cost_percent(fee_bps, slippage_bps)
    if cost > 0 and width / cost < regime.min_width_cost_ratio:
        reasons.append("range_does_not_cover_cost")
    if features["path_efficiency_60m"] > regime.max_path_efficiency_60m:
        reasons.append("path_too_directional")
    if abs(features["return_60m"]) > regime.max_abs_return_60m:
        reasons.append("return_60m_too_directional")
    if features["volume_cv_30m"] > regime.max_volume_cv_30m:
        reasons.append("volume_too_irregular")
    if features["volume_ratio_3_30"] > regime.max_volume_ratio_3_30:
        reasons.append("recent_volume_spike")
    return reasons


def regime_diagnostics(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    lookback_minutes: int,
    stride: int,
    regime: RangeRegimeConfig,
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    evaluated = 0
    passed = 0
    rejection_counts: dict[str, int] = {}
    symbol_pass_counts: dict[str, int] = {}
    for symbol, bars in bars_by_symbol.items():
        for index in range(max(lookback_minutes, 60), len(bars), max(1, stride)):
            features = feature_snapshot(bars, index)
            if features is None:
                continue
            evaluated += 1
            reasons = range_regime_rejection_reasons(features, regime, fee_bps=fee_bps, slippage_bps=slippage_bps)
            if reasons:
                for reason in reasons:
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                continue
            passed += 1
            symbol_pass_counts[symbol] = symbol_pass_counts.get(symbol, 0) + 1
    return {
        "enabled": regime.enabled,
        "evaluated_windows": evaluated,
        "passed_windows": passed,
        "passed_rate": round(passed / evaluated, 8) if evaluated else 0.0,
        "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)),
        "symbol_pass_counts": dict(sorted(symbol_pass_counts.items())),
    }


def train_scorecard(
    samples: list[FeatureSample],
    *,
    feature_names: list[str],
    bin_count: int,
    min_bin_samples: int,
    prior_samples: float,
) -> FeatureScorecard:
    if not samples:
        return FeatureScorecard(feature_names, {}, {}, 0.0, min_bin_samples, prior_samples)
    global_mean = sum(sample.label.opportunity_score_percent for sample in samples) / len(samples)
    bin_edges = {
        feature: quantile_edges([sample.features[feature] for sample in samples], bin_count)
        for feature in feature_names
    }
    raw: dict[str, list[float]] = {}
    for sample in samples:
        for feature in feature_names:
            bin_index = assign_bin(sample.features[feature], bin_edges[feature])
            key = stat_key(sample.side, feature, bin_index)
            raw.setdefault(key, []).append(sample.label.opportunity_score_percent)
    stats = {
        key: BinStat(
            count=len(values),
            mean_score=round(sum(values) / len(values), 8),
            win_rate=round(sum(value > 0 for value in values) / len(values), 8),
        )
        for key, values in raw.items()
    }
    return FeatureScorecard(feature_names, bin_edges, stats, round(global_mean, 8), min_bin_samples, prior_samples)


def score_samples(samples: list[FeatureSample], scorecard: FeatureScorecard) -> list[ScoredCandidate]:
    return [ScoredCandidate(sample=sample, score=score_sample(sample, scorecard)[0], contribution_count=score_sample(sample, scorecard)[1]) for sample in samples]


def score_sample(sample: FeatureSample, scorecard: FeatureScorecard) -> tuple[float, int]:
    contributions: list[float] = []
    for feature in scorecard.feature_names:
        edges = scorecard.bin_edges.get(feature)
        if edges is None:
            continue
        key = stat_key(sample.side, feature, assign_bin(sample.features[feature], edges))
        stat = scorecard.bin_stats.get(key)
        if stat is None or stat.count < scorecard.min_bin_samples:
            continue
        mean = (stat.mean_score * stat.count + scorecard.global_mean_score * scorecard.prior_samples) / (
            stat.count + scorecard.prior_samples
        )
        contributions.append(mean)
    if not contributions:
        return scorecard.global_mean_score, 0
    return sum(contributions) / len(contributions), len(contributions)


def learn_trading_profile(
    validation_samples: list[FeatureSample],
    validation_bars: dict[str, list[BacktestBar]],
    *,
    scorecard: FeatureScorecard,
    base_profile: LearnedTradingProfile,
    threshold_candidates: list[float],
    target_grid: list[float],
    stop_grid: list[float],
    hold_grid: list[int],
    min_validation_trades: int,
    max_side_imbalance: float,
    initial_capital: float,
    max_open_positions: int,
    max_new_entries_per_minute: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> tuple[LearnedTradingProfile, list[dict[str, Any]]]:
    leaderboard: list[dict[str, Any]] = []
    best_profile = base_profile
    best_score = -math.inf
    scored = score_samples(validation_samples, scorecard)
    for threshold in threshold_candidates:
        for target in target_grid:
            for stop in stop_grid:
                for hold in hold_grid:
                    profile = LearnedTradingProfile(
                        lookback_minutes=base_profile.lookback_minutes,
                        label_horizon_minutes=base_profile.label_horizon_minutes,
                        score_threshold=threshold,
                        target_percent=target,
                        stop_percent=stop,
                        max_hold_minutes=hold,
                        fee_bps=base_profile.fee_bps,
                        slippage_bps=base_profile.slippage_bps,
                        enabled=True,
                    )
                    result = run_scored_portfolio_backtest(
                        validation_samples,
                        validation_bars,
                        scorecard=scorecard,
                        profile=profile,
                        initial_capital=initial_capital,
                        max_open_positions=max_open_positions,
                        max_new_entries_per_minute=max_new_entries_per_minute,
                        risk_per_trade_fraction=risk_per_trade_fraction,
                        max_notional_fraction=max_notional_fraction,
                        pre_scored=scored,
                    )
                    summary = result["summary"]
                    score = trading_profile_score(
                        summary,
                        min_trades=min_validation_trades,
                        max_side_imbalance=max_side_imbalance,
                    )
                    row = {
                        "score": round(score, 8),
                        "profile": asdict(profile),
                        "summary": summary,
                    }
                    leaderboard.append(row)
                    if score > best_score:
                        best_score = score
                        best_profile = profile
    leaderboard.sort(key=lambda row: row["score"], reverse=True)
    if best_score <= -999_999.0:
        best_profile = LearnedTradingProfile(
            lookback_minutes=base_profile.lookback_minutes,
            label_horizon_minutes=base_profile.label_horizon_minutes,
            score_threshold=math.inf,
            target_percent=base_profile.target_percent,
            stop_percent=base_profile.stop_percent,
            max_hold_minutes=base_profile.max_hold_minutes,
            fee_bps=base_profile.fee_bps,
            slippage_bps=base_profile.slippage_bps,
            enabled=False,
        )
    else:
        selected_summary = next(
            (row["summary"] for row in leaderboard if row["profile"] == asdict(best_profile)),
            {},
        )
        if float(selected_summary.get("return_percent") or 0.0) <= 0.0:
            best_profile = LearnedTradingProfile(
                lookback_minutes=base_profile.lookback_minutes,
                label_horizon_minutes=base_profile.label_horizon_minutes,
                score_threshold=math.inf,
                target_percent=base_profile.target_percent,
                stop_percent=base_profile.stop_percent,
                max_hold_minutes=base_profile.max_hold_minutes,
                fee_bps=base_profile.fee_bps,
                slippage_bps=base_profile.slippage_bps,
                enabled=False,
            )
    return best_profile, leaderboard


def run_scored_portfolio_backtest(
    samples: list[FeatureSample],
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    scorecard: FeatureScorecard,
    profile: LearnedTradingProfile,
    initial_capital: float,
    max_open_positions: int,
    max_new_entries_per_minute: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
    pre_scored: list[ScoredCandidate] | None = None,
) -> dict[str, Any]:
    scored = pre_scored if pre_scored is not None else score_samples(samples, scorecard)
    if not profile.enabled:
        return {"summary": summarize_trade_dicts([], initial_capital=initial_capital), "trades": []}
    candidates_by_time: dict[int, list[ScoredCandidate]] = {}
    for candidate in scored:
        if candidate.score < profile.score_threshold or candidate.contribution_count <= 0:
            continue
        bar = bars_by_symbol.get(candidate.sample.symbol, [])
        if candidate.sample.entry_index >= len(bar):
            continue
        candidates_by_time.setdefault(bar[candidate.sample.entry_index].open_time, []).append(candidate)

    time_index: dict[int, dict[str, int]] = {}
    for symbol, bars in bars_by_symbol.items():
        for index, bar in enumerate(bars):
            time_index.setdefault(bar.open_time, {})[symbol] = index

    equity = initial_capital
    open_positions: list[GenericPosition] = []
    trades: list[dict[str, Any]] = []
    for open_time in sorted(time_index):
        index_by_symbol = time_index[open_time]
        next_positions: list[GenericPosition] = []
        for position in open_positions:
            current_index = index_by_symbol.get(position.candidate.sample.symbol)
            if current_index is None or current_index <= position.entry_index:
                next_positions.append(position)
                continue
            maybe_trade, updated = update_generic_position(
                bars_by_symbol[position.candidate.sample.symbol],
                current_index,
                position,
                profile,
            )
            if maybe_trade is None:
                next_positions.append(updated)
                continue
            equity += maybe_trade["net_pnl_usdt"]
            trades.append(maybe_trade)
        open_positions = next_positions

        capacity = max_open_positions - len(open_positions)
        if capacity <= 0:
            continue
        active_symbols = {position.candidate.sample.symbol for position in open_positions}
        minute_candidates = [
            candidate
            for candidate in candidates_by_time.get(open_time, [])
            if candidate.sample.symbol not in active_symbols
        ]
        best_by_symbol: dict[str, ScoredCandidate] = {}
        for candidate in minute_candidates:
            existing = best_by_symbol.get(candidate.sample.symbol)
            if existing is None or candidate.score > existing.score:
                best_by_symbol[candidate.sample.symbol] = candidate
        ranked = sorted(best_by_symbol.values(), key=lambda item: item.score, reverse=True)
        for candidate in ranked[: min(capacity, max_new_entries_per_minute)]:
            notional = position_notional(
                equity=equity,
                stop_percent=profile.stop_percent,
                risk_per_trade_fraction=risk_per_trade_fraction,
                max_notional_fraction=max_notional_fraction,
            )
            if notional <= 0:
                continue
            sample = candidate.sample
            open_positions.append(
                GenericPosition(
                    candidate=candidate,
                    entry_index=sample.entry_index,
                    entry_time=sample.entry_time,
                    entry_price=sample.entry_price,
                    quantity=notional / sample.entry_price,
                    notional_usdt=notional,
                    best_price=sample.entry_price,
                    worst_price=sample.entry_price,
                    fees_entry_usdt=notional * profile.fee_bps / 10_000.0,
                    slippage_entry_usdt=notional * profile.slippage_bps / 10_000.0,
                )
            )
    for position in open_positions:
        bars = bars_by_symbol[position.candidate.sample.symbol]
        trades.append(close_generic_position(position, bars[-1], profile, exit_reason="data_end"))
    return {"summary": summarize_trade_dicts(trades, initial_capital=initial_capital), "trades": trades}


def update_generic_position(
    bars: list[BacktestBar],
    index: int,
    position: GenericPosition,
    profile: LearnedTradingProfile,
) -> tuple[dict[str, Any] | None, GenericPosition]:
    bar = bars[index]
    side = position.candidate.sample.side
    if side == "long":
        best_price = max(position.best_price, bar.high)
        worst_price = min(position.worst_price, bar.low)
        stop_price = position.entry_price * (1.0 - profile.stop_percent / 100.0)
        target_price = position.entry_price * (1.0 + profile.target_percent / 100.0)
        hit_stop = bar.low <= stop_price
        hit_target = bar.high >= target_price
    else:
        best_price = min(position.best_price, bar.low)
        worst_price = max(position.worst_price, bar.high)
        stop_price = position.entry_price * (1.0 + profile.stop_percent / 100.0)
        target_price = position.entry_price * (1.0 - profile.target_percent / 100.0)
        hit_stop = bar.high >= stop_price
        hit_target = bar.low <= target_price
    excursion = GenericPosition(
        candidate=position.candidate,
        entry_index=position.entry_index,
        entry_time=position.entry_time,
        entry_price=position.entry_price,
        quantity=position.quantity,
        notional_usdt=position.notional_usdt,
        best_price=best_price,
        worst_price=worst_price,
        fees_entry_usdt=position.fees_entry_usdt,
        slippage_entry_usdt=position.slippage_entry_usdt,
    )
    if hit_stop:
        return close_generic_position(excursion, bar, profile, exit_reason="stop_loss", exit_price=stop_price), position
    if hit_target:
        return close_generic_position(excursion, bar, profile, exit_reason="take_profit", exit_price=target_price), position
    if index - position.entry_index + 1 >= profile.max_hold_minutes:
        return close_generic_position(excursion, bar, profile, exit_reason="max_hold_exit", exit_price=bar.close), position
    return None, excursion


def close_generic_position(
    position: GenericPosition,
    bar: BacktestBar,
    profile: LearnedTradingProfile,
    *,
    exit_reason: str,
    exit_price: float | None = None,
) -> dict[str, Any]:
    raw_exit = bar.close if exit_price is None else exit_price
    slip_rate = profile.slippage_bps / 10_000.0
    side = position.candidate.sample.side
    if side == "long":
        exit_fill = raw_exit * (1.0 - slip_rate)
        entry_fill = position.entry_price * (1.0 + slip_rate)
        gross_pnl = position.quantity * (exit_fill - entry_fill)
        mfe = (position.best_price - entry_fill) / entry_fill * 100.0 if entry_fill > 0 else 0.0
        mae = (position.worst_price - entry_fill) / entry_fill * 100.0 if entry_fill > 0 else 0.0
    else:
        exit_fill = raw_exit * (1.0 + slip_rate)
        entry_fill = position.entry_price * (1.0 - slip_rate)
        gross_pnl = position.quantity * (entry_fill - exit_fill)
        mfe = (entry_fill - position.best_price) / entry_fill * 100.0 if entry_fill > 0 else 0.0
        mae = (entry_fill - position.worst_price) / entry_fill * 100.0 if entry_fill > 0 else 0.0
    exit_fee = position.quantity * exit_fill * profile.fee_bps / 10_000.0
    fees = position.fees_entry_usdt + exit_fee
    slippage = position.slippage_entry_usdt + position.quantity * raw_exit * profile.slippage_bps / 10_000.0
    net_pnl = gross_pnl - fees
    risk_usdt = position.notional_usdt * profile.stop_percent / 100.0
    return {
        "symbol": position.candidate.sample.symbol,
        "side": side,
        "entry_time": position.entry_time,
        "exit_time": bar.close_time_iso,
        "entry_price": round(entry_fill, 8),
        "exit_price": round(exit_fill, 8),
        "notional_usdt": round(position.notional_usdt, 8),
        "score": round(position.candidate.score, 8),
        "contribution_count": position.candidate.contribution_count,
        "gross_pnl_usdt": round(gross_pnl, 8),
        "fees_usdt": round(fees, 8),
        "slippage_usdt": round(slippage, 8),
        "net_pnl_usdt": round(net_pnl, 8),
        "hold_minutes": max(1, int((bar.close_time - position_entry_ms(position)) / ONE_MINUTE_MS) + 1),
        "mfe_percent": round(mfe, 8),
        "mae_percent": round(mae, 8),
        "realized_r": round(net_pnl / risk_usdt, 8) if risk_usdt > 0 else 0.0,
        "exit_reason": exit_reason,
    }


def summarize_trade_dicts(trades: list[dict[str, Any]], *, initial_capital: float) -> dict[str, Any]:
    equity = initial_capital
    peak = initial_capital
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    max_drawdown = 0.0
    for trade in sorted(trades, key=lambda item: item["exit_time"]):
        pnl = float(trade["net_pnl_usdt"])
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)
    return {
        "initial_capital_usdt": round(initial_capital, 8),
        "final_capital_usdt": round(equity, 8),
        "net_pnl_usdt": round(equity - initial_capital, 8),
        "return_percent": round((equity / initial_capital - 1.0) * 100.0, 8) if initial_capital else 0.0,
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades), 8) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else ("inf" if gross_profit else None),
        "expectancy_usdt": round((equity - initial_capital) / len(trades), 8) if trades else 0.0,
        "fees_usdt": round(sum(float(trade["fees_usdt"]) for trade in trades), 8),
        "slippage_usdt": round(sum(float(trade["slippage_usdt"]) for trade in trades), 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "max_drawdown_percent_of_initial": round(max_drawdown / initial_capital * 100.0, 8) if initial_capital else 0.0,
        "exit_reason_counts": count_by(trades, "exit_reason"),
        "side_counts": count_by(trades, "side"),
        "symbol_counts": count_by(trades, "symbol"),
    }


def trading_profile_score(summary: dict[str, Any], *, min_trades: int, max_side_imbalance: float = 1.0) -> float:
    trade_count = int(summary.get("trade_count") or 0)
    if trade_count <= 0:
        return -1_000_000.0
    pf = summary.get("profit_factor")
    pf_value = 4.0 if pf == "inf" else float(pf or 0.0)
    score = (
        float(summary.get("return_percent") or 0.0)
        + pf_value * 2.5
        + float(summary.get("win_rate") or 0.0) * 3.0
        - float(summary.get("max_drawdown_percent_of_initial") or 0.0) * 1.8
    )
    if trade_count < min_trades:
        score -= 1_000.0 + (min_trades - trade_count) / max(min_trades, 1) * 100.0
    side_counts = summary.get("side_counts") or {}
    if trade_count > 0 and max_side_imbalance < 1.0:
        dominant = max((int(value) for value in side_counts.values()), default=0) / trade_count
        if dominant > max_side_imbalance:
            return -1_000_000.0 - (dominant - max_side_imbalance) * 100.0
    return score


def scorecard_summary(scorecard: FeatureScorecard) -> dict[str, Any]:
    best_bins = sorted(
        (
            {"key": key, "count": stat.count, "mean_score": stat.mean_score, "win_rate": stat.win_rate}
            for key, stat in scorecard.bin_stats.items()
            if stat.count >= scorecard.min_bin_samples
        ),
        key=lambda item: item["mean_score"],
        reverse=True,
    )
    feature_counts: dict[str, int] = {}
    for key, stat in scorecard.bin_stats.items():
        if stat.count < scorecard.min_bin_samples:
            continue
        _, feature, _ = key.split("|")
        feature_counts[feature] = feature_counts.get(feature, 0) + 1
    return {
        "feature_names": scorecard.feature_names,
        "global_mean_score": scorecard.global_mean_score,
        "min_bin_samples": scorecard.min_bin_samples,
        "prior_samples": scorecard.prior_samples,
        "eligible_bin_count": len(best_bins),
        "best_bins": best_bins[:30],
        "eligible_bins_by_feature": dict(sorted(feature_counts.items())),
    }


def label_summary(samples: list[FeatureSample]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0}
    scores = [sample.label.opportunity_score_percent for sample in samples]
    return {
        "sample_count": len(samples),
        "clean_win_rate": round(sum(sample.label.clean_win for sample in samples) / len(samples), 8),
        "mean_opportunity_score_percent": round(sum(scores) / len(scores), 8),
        "median_opportunity_score_percent": round(percentile(scores, 50), 8),
        "p90_opportunity_score_percent": round(percentile(scores, 90), 8),
        "side_counts": count_by([asdict(sample) for sample in samples], "side"),
        "first_hit_counts": count_by([asdict(sample.label) for sample in samples], "first_hit"),
    }


def selection_summary(candidates: list[ScoredCandidate], threshold: float) -> dict[str, Any]:
    selected = [candidate for candidate in candidates if candidate.score >= threshold and candidate.contribution_count > 0]
    return {
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "selected_rate": round(len(selected) / len(candidates), 8) if candidates else 0.0,
        "threshold": round(threshold, 8),
        "score_mean": round(sum(candidate.score for candidate in candidates) / len(candidates), 8) if candidates else 0.0,
        "selected_score_mean": round(sum(candidate.score for candidate in selected) / len(selected), 8) if selected else 0.0,
        "side_counts": count_by([asdict(candidate.sample) for candidate in selected], "side"),
        "symbol_counts": count_by([asdict(candidate.sample) for candidate in selected], "symbol"),
    }


def threshold_candidates_from_scores(candidates: list[ScoredCandidate], percentiles: list[float]) -> list[float]:
    scores = [candidate.score for candidate in candidates if candidate.contribution_count > 0]
    if not scores:
        return [0.0]
    thresholds = {percentile(scores, percentile_value) for percentile_value in percentiles}
    thresholds.add(max(scores))
    thresholds.add(sum(scores) / len(scores))
    return sorted(thresholds)


def quantile_edges(values: list[float], bin_count: int) -> list[float]:
    if not values or bin_count <= 1:
        return []
    return sorted(
        {
            percentile(values, 100.0 * index / bin_count)
            for index in range(1, bin_count)
        }
    )


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(100.0, percent)) / 100.0 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def assign_bin(value: float, edges: list[float]) -> int:
    for index, edge in enumerate(edges):
        if value <= edge:
            return index
    return len(edges)


def stat_key(side: str, feature: str, bin_index: int) -> str:
    return f"{side}|{feature}|{bin_index}"


def return_over_bars(bars: list[BacktestBar], index: int, minutes: int) -> float:
    start_index = max(0, index - minutes + 1)
    return percent_delta(bars[start_index].open, bars[index].close)


def range_width_percent(window: list[BacktestBar]) -> float:
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    reference = window[-1].close
    return (high - low) / reference * 100.0 if reference > 0 else 0.0


def close_position_percent(window: list[BacktestBar]) -> float:
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    span = high - low
    if span <= 0:
        return 50.0
    return (window[-1].close - low) / span * 100.0


def path_efficiency(window: list[BacktestBar]) -> float:
    travel = sum(abs(current.close - previous.close) for previous, current in zip(window, window[1:]))
    displacement = abs(window[-1].close - window[0].open)
    return displacement / travel if travel > 0 else 0.0


def realized_volatility_percent(window: list[BacktestBar]) -> float:
    returns = [abs(percent_delta(previous.close, current.close)) for previous, current in zip(window, window[1:]) if previous.close > 0]
    return sum(returns) / len(returns) if returns else 0.0


def volume_ratio(bars: list[BacktestBar], index: int, *, recent: int, baseline: int) -> float:
    recent_window = bars[max(0, index - recent + 1) : index + 1]
    baseline_window = bars[max(0, index - baseline + 1) : index + 1]
    recent_values = [bar.quote_volume for bar in recent_window if bar.quote_volume > 0]
    baseline_values = [bar.quote_volume for bar in baseline_window if bar.quote_volume > 0]
    if not recent_values or not baseline_values:
        return 1.0
    baseline_mean = sum(baseline_values) / len(baseline_values)
    return (sum(recent_values) / len(recent_values)) / baseline_mean if baseline_mean > 0 else 1.0


def taker_buy_ratio(window: list[BacktestBar]) -> float:
    quote = sum(bar.quote_volume for bar in window)
    taker = sum(bar.taker_buy_quote_volume for bar in window)
    return taker / quote if quote > 0 else 0.5


def upper_wick_percent(bar: BacktestBar) -> float:
    top = max(bar.open, bar.close)
    return max(0.0, bar.high - top) / bar.close * 100.0 if bar.close > 0 else 0.0


def lower_wick_percent(bar: BacktestBar) -> float:
    bottom = min(bar.open, bar.close)
    return max(0.0, bottom - bar.low) / bar.close * 100.0 if bar.close > 0 else 0.0


def first_threshold_hit_minutes(
    future: list[BacktestBar],
    *,
    entry: float,
    side: str,
    threshold_percent: float,
    favorable: bool,
) -> int | None:
    if entry <= 0:
        return None
    for offset, bar in enumerate(future, start=1):
        if side == "long":
            move = (bar.high - entry) / entry * 100.0 if favorable else (entry - bar.low) / entry * 100.0
        else:
            move = (entry - bar.low) / entry * 100.0 if favorable else (bar.high - entry) / entry * 100.0
        if move >= threshold_percent:
            return offset
    return None


def coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return (variance ** 0.5) / mean


def round_trip_cost_percent(fee_bps: float, slippage_bps: float) -> float:
    return 2.0 * (max(fee_bps, 0.0) + max(slippage_bps, 0.0)) / 100.0


def position_notional(
    *,
    equity: float,
    stop_percent: float,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> float:
    if equity <= 0 or stop_percent <= 0:
        return 0.0
    risk_notional = equity * risk_per_trade_fraction / (stop_percent / 100.0)
    return max(0.0, min(risk_notional, equity * max_notional_fraction))


def position_entry_ms(position: GenericPosition) -> int:
    return int(datetime.fromisoformat(position.entry_time.replace("Z", "+00:00")).timestamp() * 1000)


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in str(value).split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
