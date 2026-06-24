"""Research maker-limit range rhythm reversal on Binance USD-M 1m klines.

This script is deliberately narrower than the generic feature-label research:
it only studies the range strategy the operator described. A candidate is not
a trade until a maker-style limit price is actually touched; unfilled orders
expire with no PnL.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bfa.backtest.models import BacktestBar


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_orderly_range_research import (  # noqa: E402
    ONE_MINUTE_MS,
    coefficient_of_variation,
    count_by,
    coverage_summary,
    load_many_symbol_klines,
    parse_symbols,
    percent_delta,
    resolve_top_symbols,
    split_validation_bars,
)


@dataclass(frozen=True)
class RhythmProfile:
    trade_direction_mode: str = "reversion"
    lookback_minutes: int = 90
    band_quantile: float = 8.0
    min_width_percent: float = 0.55
    max_width_percent: float = 5.5
    min_width_cost_ratio: float = 4.0
    max_path_efficiency: float = 0.45
    max_abs_trend_percent: float = 1.0
    max_band_shift_ratio: float = 0.32
    max_volume_cv: float = 1.6
    max_recent_volume_ratio: float = 3.8
    max_adverse_edge_push_percent: float = 0.38
    max_adverse_edge_push_efficiency: float = 0.7
    max_adverse_edge_push_volume_ratio: float = 2.0
    edge_touch_zone_fraction: float = 0.18
    min_edge_touches_per_side: int = 2
    min_edge_alternations: int = 3
    min_mid_crosses: int = 2
    reaction_window_minutes: int = 12
    min_reaction_success_rate: float = 0.38
    max_touch_interval_cv: float = 1.45
    low_zone_percent: float = 30.0
    high_zone_percent: float = 70.0
    rejection_confirm_zone_percent: float = 55.0
    min_rejection_wick_fraction: float = 0.0
    entry_band_fraction: float = 0.08
    needle_extension_fraction: float = 0.0
    stop_outside_fraction: float = 0.16
    target_range_fraction: float = 0.45
    target_edge_buffer_fraction: float = 0.12
    min_risk_reward: float = 1.05
    min_reward_cost_ratio: float = 2.2
    limit_wait_minutes: int = 4
    min_hold_minutes: int = 1
    max_hold_minutes: int = 45
    time_exit_enabled: bool = True
    same_bar_exit_policy: str = "stop_only"
    breakout_buffer_fraction: float = 0.08
    trend_exit_path_efficiency: float = 0.62
    trailing_activate_r: float = 0.55
    trailing_lock_r: float = 0.08
    trailing_giveback_r: float = 0.22
    min_trailing_lock_cost_ratio: float = 1.2
    reentry_cooldown_minutes: int = 4
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 4.0
    exit_slippage_bps: float = 1.0

    @property
    def round_trip_cost_percent(self) -> float:
        entry_fee = self.taker_fee_bps if self.trade_direction_mode == "continuation" else self.maker_fee_bps
        return (
            max(entry_fee, 0.0)
            + max(self.taker_fee_bps, 0.0)
            + max(self.exit_slippage_bps, 0.0)
        ) / 100.0


@dataclass(frozen=True)
class RhythmFeatures:
    support_price: float
    resistance_price: float
    span_percent: float
    close_position_percent: float
    lower_touch_count: int
    upper_touch_count: int
    edge_alternation_count: int
    mid_cross_count: int
    reaction_success_rate: float
    reaction_sample_count: int
    touch_interval_cv: float | None
    band_shift_ratio: float
    path_efficiency: float
    trend_percent: float
    recent_trend_percent: float
    recent_path_efficiency: float
    volume_cv: float | None
    recent_volume_ratio: float | None
    quote_volume_mean: float
    lower_needle_fraction: float
    upper_needle_fraction: float
    last_lower_rejection: bool
    last_upper_rejection: bool
    last_lower_wick_fraction: float
    last_upper_wick_fraction: float
    reference_price: float

    @property
    def abs_trend_percent(self) -> float:
        return abs(self.trend_percent)


@dataclass(frozen=True)
class RhythmSignal:
    symbol: str
    side: str
    signal_index: int
    score: float
    entry_price: float
    stop_price: float
    target_price: float
    range_low_price: float
    range_high_price: float
    features: RhythmFeatures
    reason_codes: list[str]


@dataclass(frozen=True)
class PendingLimitOrder:
    signal: RhythmSignal
    created_index: int
    expires_index: int


@dataclass(frozen=True)
class RhythmPosition:
    signal: RhythmSignal
    entry_index: int
    entry_time: str
    entry_price: float
    quantity: float
    notional_usdt: float
    dynamic_stop_price: float
    best_price: float
    worst_price: float
    fees_entry_usdt: float


@dataclass(frozen=True)
class RhythmTrade:
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
    hold_minutes: int
    mfe_percent: float
    mae_percent: float
    realized_r: float
    exit_reason: str
    reason_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--train-end", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--test-start", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--test-end", required=True, help="inclusive UTC date, YYYY-MM-DD")
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
    parser.add_argument("--training-stride-minutes", type=int, default=5)
    parser.add_argument("--validation-days", type=int, default=7)
    parser.add_argument("--min-train-trades", type=int, default=30)
    parser.add_argument("--min-validation-trades", type=int, default=12)
    parser.add_argument("--max-grid-profiles", type=int, default=72)
    parser.add_argument("--test-leaderboard-profiles", type=int, default=0)
    parser.add_argument("--profile-json", help="optional profile JSON file to skip grid learning")
    parser.add_argument("--time-exit", choices=("on", "off"), default="on")
    parser.add_argument("--trade-direction-mode", choices=("reversion", "continuation"), default="reversion")
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--exit-slippage-bps", type=float, default=1.0)
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
    base_profile = RhythmProfile(
        trade_direction_mode=args.trade_direction_mode,
        time_exit_enabled=args.time_exit == "on",
        maker_fee_bps=args.maker_fee_bps,
        taker_fee_bps=args.taker_fee_bps,
        exit_slippage_bps=args.exit_slippage_bps,
    )
    if args.profile_json:
        profile = RhythmProfile(**json.loads(Path(args.profile_json).read_text(encoding="utf-8")))
        leaderboard: list[dict[str, Any]] = []
        train_summary: dict[str, Any] = {"skipped": "profile_json_supplied"}
        selection = {"validation_passed": None, "reason": "profile_json_supplied"}
    else:
        profile, leaderboard, train_summary, selection = learn_profile(
            fit_bars,
            validation_bars_by_symbol=validation_bars,
            base_profile=base_profile,
            training_stride_minutes=args.training_stride_minutes,
            min_train_trades=args.min_train_trades,
            min_validation_trades=args.min_validation_trades,
            max_grid_profiles=args.max_grid_profiles,
        )

    test_result = run_portfolio_backtest(
        test_bars,
        profile=profile,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        max_new_entries_per_minute=args.max_new_entries_per_minute,
        risk_per_trade_fraction=args.risk_per_trade_fraction,
        max_notional_fraction=args.max_notional_fraction,
    )
    test_leaderboard = run_test_leaderboard(
        leaderboard,
        test_bars,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        max_new_entries_per_minute=args.max_new_entries_per_minute,
        risk_per_trade_fraction=args.risk_per_trade_fraction,
        max_notional_fraction=args.max_notional_fraction,
        limit=args.test_leaderboard_profiles,
    )
    payload = {
        "schema": "bfa_limit_range_rhythm_research_v1",
        "method": {
            "data_source": "Binance USD-M public daily 1m kline archives",
            "signal": "detect stable rhythmic ranges from completed lookback bars, then place maker-style limits near support/resistance",
        "fill_model": "reversion candidates use maker-style edge limits; continuation candidates use conservative trigger/taker fills; unfilled orders expire with no PnL",
            "exit_model": "stop/target/trailing/range-invalid exits with compounding portfolio sizing; time exit can be disabled",
            "no_future_leak": "features at minute t use bars strictly before t; fills/exits use bars at or after t",
        },
        "symbols": symbols,
        "train_window": {"start_date": train_start.isoformat(), "end_date": train_end.isoformat()},
        "test_window": {"start_date": test_start.isoformat(), "end_date": test_end.isoformat()},
        "profile": asdict(profile),
        "selection": selection,
        "train_summary": train_summary,
        "leaderboard": leaderboard[:20],
        "test_leaderboard": test_leaderboard,
        "test_summary": test_result["summary"],
        "test_order_stats": test_result["order_stats"],
        "test_failure_summary": failure_summary(test_result["trades"], profile=profile),
        "test_trades": test_result["trades"],
        "diagnostics": {
            "fit_selected_profile": scan_signal_diagnostics(fit_bars, profile=profile, stride=max(1, args.training_stride_minutes)),
            "validation_selected_profile": scan_signal_diagnostics(validation_bars, profile=profile, stride=max(1, args.training_stride_minutes)),
            "test_selected_profile": scan_signal_diagnostics(test_bars, profile=profile, stride=1),
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


def learn_profile(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    validation_bars_by_symbol: dict[str, list[BacktestBar]] | None,
    base_profile: RhythmProfile,
    training_stride_minutes: int,
    min_train_trades: int,
    min_validation_trades: int,
    max_grid_profiles: int | None,
) -> tuple[RhythmProfile, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    leaderboard: list[dict[str, Any]] = []
    best_profile = base_profile
    best_score = -math.inf
    has_validation = bool(validation_bars_by_symbol)
    for profile in profile_grid(base_profile, max_profiles=max_grid_profiles):
        fit_trades = independent_training_trades(bars_by_symbol, profile=profile, stride=max(1, training_stride_minutes))
        fit_summary = summarize_trades(fit_trades, initial_capital=30.0)
        validation_summary: dict[str, Any] | None = None
        selection_summary = fit_summary
        required_trades = min_train_trades
        if has_validation:
            validation_trades = independent_training_trades(
                validation_bars_by_symbol or {},
                profile=profile,
                stride=max(1, training_stride_minutes),
            )
            validation_summary = summarize_trades(validation_trades, initial_capital=30.0)
            selection_summary = validation_summary
            required_trades = min_validation_trades
        score = profile_selection_score(selection_summary, min_trades=required_trades)
        eligible = int(fit_summary.get("trade_count") or 0) >= min_train_trades and (
            not has_validation or int((validation_summary or {}).get("trade_count") or 0) >= min_validation_trades
        )
        if not eligible:
            score -= 1_000.0
        row = {
            "score": round(score, 8),
            "eligible_for_selection": eligible,
            "profile": asdict(profile),
            "summary": selection_summary,
            "fit_summary": fit_summary,
            "validation_summary": validation_summary,
        }
        leaderboard.append(row)
        if score > best_score:
            best_score = score
            best_profile = profile
    leaderboard.sort(key=lambda item: item["score"], reverse=True)
    selected_summary = next(
        (row["summary"] for row in leaderboard if row["profile"] == asdict(best_profile)),
        leaderboard[0]["summary"] if leaderboard else {},
    )
    required_selected_trades = min_validation_trades if has_validation else min_train_trades
    selected_trade_count = int(selected_summary.get("trade_count") or 0)
    selected_return = float(selected_summary.get("return_percent") or 0.0)
    selected_pf = profit_factor_value(selected_summary.get("profit_factor"))
    validation_passed = selected_trade_count >= required_selected_trades and selected_return > 0.0 and selected_pf > 1.0
    failed_reasons: list[str] = []
    if selected_trade_count < required_selected_trades:
        failed_reasons.append("not_enough_validation_trades")
    if selected_return <= 0.0:
        failed_reasons.append("validation_return_not_positive")
    if selected_pf <= 1.0:
        failed_reasons.append("validation_profit_factor_not_above_one")
    selection = {
        "validation_passed": validation_passed,
        "required_validation_trades": required_selected_trades,
        "failed_reasons": failed_reasons,
        "selected_score": round(best_score, 8),
        "selected_summary": selected_summary,
        "live_promotion_note": (
            "validation-positive candidate" if validation_passed else "research-only; do not promote to live without better validation"
        ),
    }
    return best_profile, leaderboard, selected_summary, selection


def profile_grid(base: RhythmProfile, *, max_profiles: int | None = None) -> list[RhythmProfile]:
    profiles: list[RhythmProfile] = []
    for lookback in (45, 60, 90, 120):
        for min_width in (0.45, 0.7, 1.0):
            for max_path in (0.32, 0.45, 0.58):
                for max_trend in (0.45, 0.75, 1.1):
                    for reaction_rate in (0.32, 0.42, 0.52):
                        for entry_fraction in (0.0, 0.04, 0.08):
                            for needle_fraction in (0.0, 0.04, 0.08):
                                for rejection_wick in (0.0, 0.03, 0.06):
                                    for stop_fraction in (0.16, 0.24, 0.34):
                                        for target_fraction in (0.34, 0.48, 0.62):
                                            profiles.append(
                                                replace(
                                                    base,
                                                    lookback_minutes=lookback,
                                                    min_width_percent=min_width,
                                                    max_path_efficiency=max_path,
                                                    max_abs_trend_percent=max_trend,
                                                    min_reaction_success_rate=reaction_rate,
                                                    entry_band_fraction=entry_fraction,
                                                    needle_extension_fraction=needle_fraction,
                                                    min_rejection_wick_fraction=rejection_wick,
                                                    stop_outside_fraction=stop_fraction,
                                                    target_range_fraction=target_fraction,
                                                )
                                            )
    if max_profiles is None or max_profiles <= 0 or max_profiles >= len(profiles):
        return profiles
    if max_profiles == 1:
        return [profiles[0]]
    step = (len(profiles) - 1) / (max_profiles - 1)
    indexes = sorted({round(index * step) for index in range(max_profiles)})
    return [profiles[index] for index in indexes]


def run_test_leaderboard(
    leaderboard: list[dict[str, Any]],
    test_bars: dict[str, list[BacktestBar]],
    *,
    initial_capital: float,
    max_open_positions: int,
    max_new_entries_per_minute: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in leaderboard:
        payload = row.get("profile")
        if not isinstance(payload, dict):
            continue
        key = json.dumps(payload, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        profile = RhythmProfile(**payload)
        result = run_portfolio_backtest(
            test_bars,
            profile=profile,
            initial_capital=initial_capital,
            max_open_positions=max_open_positions,
            max_new_entries_per_minute=max_new_entries_per_minute,
            risk_per_trade_fraction=risk_per_trade_fraction,
            max_notional_fraction=max_notional_fraction,
        )
        rows.append(
            {
                "training_score": row.get("score"),
                "eligible_for_selection": row.get("eligible_for_selection"),
                "profile": payload,
                "fit_summary": row.get("fit_summary"),
                "validation_summary": row.get("validation_summary"),
                "test_summary": result["summary"],
                "test_order_stats": result["order_stats"],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def independent_training_trades(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RhythmProfile,
    stride: int,
) -> list[RhythmTrade]:
    trades: list[RhythmTrade] = []
    next_allowed_index: dict[tuple[str, str], int] = {}
    for symbol, bars in bars_by_symbol.items():
        for signal_index in range(profile.lookback_minutes, len(bars), max(1, stride)):
            signal = build_rhythm_signal(symbol, bars, signal_index, profile)
            if signal is None:
                continue
            cooldown_key = (signal.symbol, signal.side)
            if signal_index < next_allowed_index.get(cooldown_key, -1):
                continue
            fill_index = find_limit_fill_index(bars, signal, profile)
            if fill_index is None:
                continue
            trade = simulate_filled_trade(
                bars,
                signal,
                fill_index=fill_index,
                profile=profile,
                notional_usdt=20.0,
            )
            trades.append(trade)
            next_allowed_index[cooldown_key] = fill_index + profile.reentry_cooldown_minutes
    return trades


def build_rhythm_signal(
    symbol: str,
    bars: list[BacktestBar],
    signal_index: int,
    profile: RhythmProfile,
) -> RhythmSignal | None:
    signal, _ = evaluate_rhythm_signal(symbol, bars, signal_index, profile)
    return signal


def evaluate_rhythm_signal(
    symbol: str,
    bars: list[BacktestBar],
    signal_index: int,
    profile: RhythmProfile,
) -> tuple[RhythmSignal | None, list[str]]:
    if signal_index < profile.lookback_minutes or signal_index >= len(bars):
        return None, ["insufficient_lookback"]
    window = bars[signal_index - profile.lookback_minutes : signal_index]
    features = rhythm_features(window, profile)
    if features is None:
        return None, ["feature_unavailable"]
    reasons = profile_rejection_reasons(features, profile)
    if reasons:
        return None, reasons
    span = features.resistance_price - features.support_price
    mode = profile.trade_direction_mode
    if features.close_position_percent <= profile.low_zone_percent and mode == "reversion":
        side = "long"
        entry = features.support_price + span * profile.entry_band_fraction - span * profile.needle_extension_fraction
        stop = features.support_price - span * profile.stop_outside_fraction
        target = min(entry + span * profile.target_range_fraction, features.resistance_price - span * profile.target_edge_buffer_fraction)
        maker_ok = entry < features.reference_price
        reward = target - entry
        risk = entry - stop
    elif features.close_position_percent >= profile.high_zone_percent and mode == "reversion":
        side = "short"
        entry = features.resistance_price - span * profile.entry_band_fraction + span * profile.needle_extension_fraction
        stop = features.resistance_price + span * profile.stop_outside_fraction
        target = max(entry - span * profile.target_range_fraction, features.support_price + span * profile.target_edge_buffer_fraction)
        maker_ok = entry > features.reference_price
        reward = entry - target
        risk = stop - entry
    elif features.close_position_percent <= profile.low_zone_percent and mode == "continuation":
        side = "short"
        entry = features.support_price - span * max(profile.entry_band_fraction, 0.0)
        stop = features.support_price + span * profile.stop_outside_fraction
        target = entry - span * profile.target_range_fraction
        maker_ok = entry < features.reference_price
        reward = entry - target
        risk = stop - entry
    elif features.close_position_percent >= profile.high_zone_percent and mode == "continuation":
        side = "long"
        entry = features.resistance_price + span * max(profile.entry_band_fraction, 0.0)
        stop = features.resistance_price - span * profile.stop_outside_fraction
        target = entry + span * profile.target_range_fraction
        maker_ok = entry > features.reference_price
        reward = target - entry
        risk = entry - stop
    else:
        return None, ["price_not_near_range_edge"]
    side_reasons = side_rejection_reasons(features, profile, side=side)
    if side_reasons:
        return None, side_reasons
    signal_reasons: list[str] = []
    if not maker_ok:
        signal_reasons.append("limit_not_passive_vs_last_close")
    if risk <= 0 or reward <= 0:
        signal_reasons.append("invalid_risk_reward_geometry")
    risk_reward = reward / risk if risk > 0 else 0.0
    if risk_reward < profile.min_risk_reward:
        signal_reasons.append("risk_reward_too_low")
    reward_percent = reward / entry * 100.0 if entry > 0 else 0.0
    if profile.round_trip_cost_percent > 0 and reward_percent / profile.round_trip_cost_percent < profile.min_reward_cost_ratio:
        signal_reasons.append("reward_does_not_cover_cost")
    if signal_reasons:
        return None, signal_reasons
    signal = RhythmSignal(
        symbol=symbol.upper(),
        side=side,
        signal_index=signal_index,
        score=score_features(features, profile, side=side),
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        range_low_price=features.support_price,
        range_high_price=features.resistance_price,
        features=features,
        reason_codes=[
            f"signal_mode:limit_range_rhythm_{profile.trade_direction_mode}",
            f"range_span_percent:{round(features.span_percent, 4)}",
            f"edge_alternations:{features.edge_alternation_count}",
            f"mid_crosses:{features.mid_cross_count}",
            f"reaction_success_rate:{round(features.reaction_success_rate, 4)}",
            f"band_shift_ratio:{round(features.band_shift_ratio, 4)}",
        ],
    )
    return signal, []


def rhythm_features(window: list[BacktestBar], profile: RhythmProfile) -> RhythmFeatures | None:
    if len(window) < max(8, profile.lookback_minutes // 3):
        return None
    lows = [bar.low for bar in window if bar.low > 0]
    highs = [bar.high for bar in window if bar.high > 0]
    if not lows or not highs:
        return None
    support = percentile(lows, profile.band_quantile)
    resistance = percentile(highs, 100.0 - profile.band_quantile)
    reference = window[-1].close
    if support <= 0 or resistance <= support or reference <= 0:
        return None
    span = resistance - support
    lower_zone = support + span * profile.edge_touch_zone_fraction
    upper_zone = resistance - span * profile.edge_touch_zone_fraction
    sequence = edge_touch_sequence(window, lower_zone=lower_zone, upper_zone=upper_zone)
    lower_touch_count = sum(1 for _, edge in sequence if edge == "lower")
    upper_touch_count = sum(1 for _, edge in sequence if edge == "upper")
    edge_alternations = sum(1 for previous, current in zip(sequence, sequence[1:]) if previous[1] != current[1])
    intervals = [current[0] - previous[0] for previous, current in zip(sequence, sequence[1:]) if current[1] != previous[1]]
    mid = support + span * 0.5
    volumes = [bar.quote_volume for bar in window if bar.quote_volume > 0]
    travel = sum(abs(current.close - previous.close) for previous, current in zip(window, window[1:]))
    displacement = abs(window[-1].close - window[0].open)
    band_shift = band_shift_ratio(window, profile)
    reaction_success_rate, reaction_samples = reaction_stats(
        window,
        support=support,
        resistance=resistance,
        lower_zone=lower_zone,
        upper_zone=upper_zone,
        reaction_window=profile.reaction_window_minutes,
    )
    recent = window[-min(6, len(window)) :]
    recent_travel = sum(abs(current.close - previous.close) for previous, current in zip(recent, recent[1:]))
    recent_displacement = abs(recent[-1].close - recent[0].open) if len(recent) >= 2 else 0.0
    lower_needles = [max(0.0, support - bar.low) / span for bar in window]
    upper_needles = [max(0.0, bar.high - resistance) / span for bar in window]
    last = window[-1]
    last_range = last.high - last.low
    last_close_position = (last.close - last.low) / last_range if last_range > 0 else 0.5
    last_lower_wick = max(0.0, min(last.open, last.close) - last.low) / span
    last_upper_wick = max(0.0, last.high - max(last.open, last.close)) / span
    return RhythmFeatures(
        support_price=support,
        resistance_price=resistance,
        span_percent=span / reference * 100.0,
        close_position_percent=(reference - support) / span * 100.0,
        lower_touch_count=lower_touch_count,
        upper_touch_count=upper_touch_count,
        edge_alternation_count=edge_alternations,
        mid_cross_count=mid_cross_count(window, midpoint=mid),
        reaction_success_rate=reaction_success_rate,
        reaction_sample_count=reaction_samples,
        touch_interval_cv=coefficient_of_variation([float(value) for value in intervals]) if len(intervals) >= 2 else None,
        band_shift_ratio=band_shift,
        path_efficiency=displacement / travel if travel > 0 else 0.0,
        trend_percent=percent_delta(window[0].open, window[-1].close),
        recent_trend_percent=percent_delta(recent[0].open, recent[-1].close) if len(recent) >= 2 else 0.0,
        recent_path_efficiency=recent_displacement / recent_travel if recent_travel > 0 else 0.0,
        volume_cv=coefficient_of_variation(volumes),
        recent_volume_ratio=recent_volume_ratio(window),
        quote_volume_mean=sum(volumes) / len(volumes) if volumes else 0.0,
        lower_needle_fraction=percentile(lower_needles, 90),
        upper_needle_fraction=percentile(upper_needles, 90),
        last_lower_rejection=last.low <= lower_zone and last_close_position >= profile.rejection_confirm_zone_percent / 100.0,
        last_upper_rejection=last.high >= upper_zone and last_close_position <= 1.0 - profile.rejection_confirm_zone_percent / 100.0,
        last_lower_wick_fraction=last_lower_wick,
        last_upper_wick_fraction=last_upper_wick,
        reference_price=reference,
    )


def profile_rejection_reasons(features: RhythmFeatures, profile: RhythmProfile) -> list[str]:
    reasons: list[str] = []
    if not (profile.min_width_percent <= features.span_percent <= profile.max_width_percent):
        reasons.append("range_width_outside_profile")
    if profile.round_trip_cost_percent > 0 and features.span_percent / profile.round_trip_cost_percent < profile.min_width_cost_ratio:
        reasons.append("range_too_narrow_for_cost")
    if features.path_efficiency > profile.max_path_efficiency:
        reasons.append("path_too_directional")
    if features.abs_trend_percent > profile.max_abs_trend_percent:
        reasons.append("trend_too_large")
    if features.band_shift_ratio > profile.max_band_shift_ratio:
        reasons.append("bands_not_stable")
    if features.volume_cv is None or features.volume_cv > profile.max_volume_cv:
        reasons.append("volume_too_irregular")
    if features.recent_volume_ratio is not None and features.recent_volume_ratio > profile.max_recent_volume_ratio:
        reasons.append("recent_volume_spike")
    if min(features.lower_touch_count, features.upper_touch_count) < profile.min_edge_touches_per_side:
        reasons.append("not_enough_two_sided_touches")
    if features.edge_alternation_count < profile.min_edge_alternations:
        reasons.append("not_enough_edge_alternations")
    if features.mid_cross_count < profile.min_mid_crosses:
        reasons.append("not_enough_mid_crosses")
    if features.reaction_sample_count <= 0 or features.reaction_success_rate < profile.min_reaction_success_rate:
        reasons.append("weak_historical_reactions")
    if features.touch_interval_cv is not None and features.touch_interval_cv > profile.max_touch_interval_cv:
        reasons.append("touch_timing_too_irregular")
    if not (features.close_position_percent <= profile.low_zone_percent or features.close_position_percent >= profile.high_zone_percent):
        reasons.append("price_not_near_range_edge")
    return reasons


def side_rejection_reasons(features: RhythmFeatures, profile: RhythmProfile, *, side: str) -> list[str]:
    reasons: list[str] = []
    if profile.trade_direction_mode == "continuation":
        return continuation_rejection_reasons(features, profile, side=side)
    recent_volume = features.recent_volume_ratio or 1.0
    if side == "long":
        adverse_push = (
            features.recent_trend_percent < -profile.max_adverse_edge_push_percent
            and features.recent_path_efficiency > profile.max_adverse_edge_push_efficiency
        )
        adverse_volume_push = adverse_push and recent_volume > profile.max_adverse_edge_push_volume_ratio
        if adverse_push:
            reasons.append("long_edge_recent_down_push")
        if adverse_volume_push:
            reasons.append("long_edge_down_push_volume_expansion")
        if profile.min_rejection_wick_fraction > 0 and not features.last_lower_rejection:
            reasons.append("long_edge_no_rejection_close")
        if features.last_lower_wick_fraction < profile.min_rejection_wick_fraction:
            reasons.append("long_edge_lower_wick_too_small")
    else:
        adverse_push = (
            features.recent_trend_percent > profile.max_adverse_edge_push_percent
            and features.recent_path_efficiency > profile.max_adverse_edge_push_efficiency
        )
        adverse_volume_push = adverse_push and recent_volume > profile.max_adverse_edge_push_volume_ratio
        if adverse_push:
            reasons.append("short_edge_recent_up_push")
        if adverse_volume_push:
            reasons.append("short_edge_up_push_volume_expansion")
        if profile.min_rejection_wick_fraction > 0 and not features.last_upper_rejection:
            reasons.append("short_edge_no_rejection_close")
        if features.last_upper_wick_fraction < profile.min_rejection_wick_fraction:
            reasons.append("short_edge_upper_wick_too_small")
    return reasons


def continuation_rejection_reasons(features: RhythmFeatures, profile: RhythmProfile, *, side: str) -> list[str]:
    reasons: list[str] = []
    recent_volume = features.recent_volume_ratio or 1.0
    if side == "short":
        supportive_push = (
            features.recent_trend_percent < -profile.max_adverse_edge_push_percent
            and features.recent_path_efficiency > profile.max_adverse_edge_push_efficiency
        )
        if profile.max_adverse_edge_push_percent > 0 and not supportive_push:
            reasons.append("short_breakdown_push_not_confirmed")
        if recent_volume > profile.max_recent_volume_ratio:
            reasons.append("short_breakdown_volume_spike_too_extreme")
    else:
        supportive_push = (
            features.recent_trend_percent > profile.max_adverse_edge_push_percent
            and features.recent_path_efficiency > profile.max_adverse_edge_push_efficiency
        )
        if profile.max_adverse_edge_push_percent > 0 and not supportive_push:
            reasons.append("long_breakout_push_not_confirmed")
        if recent_volume > profile.max_recent_volume_ratio:
            reasons.append("long_breakout_volume_spike_too_extreme")
    return reasons


def score_features(features: RhythmFeatures, profile: RhythmProfile, *, side: str) -> float:
    edge_distance = (
        features.close_position_percent
        if side == "long"
        else 100.0 - features.close_position_percent
    )
    edge_bonus = max(0.0, min(profile.low_zone_percent, profile.high_zone_percent - 50.0) - edge_distance) / max(
        profile.low_zone_percent,
        1.0,
    )
    cost_ratio = features.span_percent / profile.round_trip_cost_percent if profile.round_trip_cost_percent > 0 else 0.0
    rhythm = features.edge_alternation_count * 0.8 + features.mid_cross_count * 0.35 + features.reaction_success_rate * 3.0
    penalties = (
        features.path_efficiency * 4.0
        + features.band_shift_ratio * 5.0
        + features.abs_trend_percent * 1.4
        + (features.volume_cv or 1.0) * 0.5
        + features.recent_path_efficiency * 0.8
    )
    return cost_ratio * 0.35 + rhythm + edge_bonus * 1.6 - penalties


def run_portfolio_backtest(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RhythmProfile,
    initial_capital: float,
    max_open_positions: int,
    max_new_entries_per_minute: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> dict[str, Any]:
    if not bars_by_symbol:
        return {
            "summary": summarize_trades([], initial_capital=initial_capital),
            "trades": [],
            "order_stats": empty_order_stats(),
        }
    time_index: dict[int, dict[str, int]] = {}
    for symbol, bars in bars_by_symbol.items():
        for index, bar in enumerate(bars):
            time_index.setdefault(bar.open_time, {})[symbol] = index
    equity = initial_capital
    pending: list[PendingLimitOrder] = []
    positions: list[RhythmPosition] = []
    trades: list[RhythmTrade] = []
    stats = empty_order_stats()
    next_allowed_index: dict[tuple[str, str], int] = {}
    for open_time in sorted(time_index):
        index_by_symbol = time_index[open_time]
        next_positions: list[RhythmPosition] = []
        for position in positions:
            current_index = index_by_symbol.get(position.signal.symbol)
            if current_index is None or current_index <= position.entry_index:
                next_positions.append(position)
                continue
            maybe_trade, updated = update_position_on_bar(
                bars_by_symbol[position.signal.symbol],
                current_index,
                position,
                profile,
            )
            if maybe_trade is None:
                next_positions.append(updated)
                continue
            equity += maybe_trade.net_pnl_usdt
            trades.append(maybe_trade)
            next_allowed_index[(position.signal.symbol, position.signal.side)] = current_index + profile.reentry_cooldown_minutes
        positions = next_positions

        still_pending: list[PendingLimitOrder] = []
        active_symbols = {position.signal.symbol for position in positions}
        for order in pending:
            current_index = index_by_symbol.get(order.signal.symbol)
            if current_index is None:
                still_pending.append(order)
                continue
            if current_index > order.expires_index:
                stats["orders_expired"] += 1
                continue
            if order.signal.symbol in active_symbols:
                stats["orders_canceled_symbol_active"] += 1
                continue
            filled, maybe_position, maybe_trade = try_fill_order(
                order,
                bars_by_symbol[order.signal.symbol],
                current_index=current_index,
                equity=equity,
                profile=profile,
                risk_per_trade_fraction=risk_per_trade_fraction,
                max_notional_fraction=max_notional_fraction,
            )
            if filled:
                stats["orders_filled"] += 1
                if maybe_trade is not None:
                    equity += maybe_trade.net_pnl_usdt
                    trades.append(maybe_trade)
                    next_allowed_index[(order.signal.symbol, order.signal.side)] = current_index + profile.reentry_cooldown_minutes
                elif maybe_position is not None:
                    positions.append(maybe_position)
                    active_symbols.add(order.signal.symbol)
                else:
                    stats["orders_rejected_sizing"] += 1
                continue
            if current_index >= order.expires_index:
                stats["orders_expired"] += 1
                continue
            still_pending.append(order)
        pending = still_pending

        capacity = max_open_positions - len(positions) - len(pending)
        if capacity <= 0:
            continue
        active_symbols = {position.signal.symbol for position in positions} | {order.signal.symbol for order in pending}
        candidates: list[RhythmSignal] = []
        for symbol, bars in bars_by_symbol.items():
            if symbol in active_symbols:
                continue
            signal_index = index_by_symbol.get(symbol)
            if signal_index is None:
                continue
            signal = build_rhythm_signal(symbol, bars, signal_index, profile)
            if signal is None:
                continue
            if signal_index < next_allowed_index.get((signal.symbol, signal.side), -1):
                continue
            candidates.append(signal)
        candidates.sort(key=lambda item: item.score, reverse=True)
        for signal in candidates[: min(capacity, max_new_entries_per_minute)]:
            stats["signals_selected"] += 1
            order = PendingLimitOrder(
                signal=signal,
                created_index=signal.signal_index,
                expires_index=min(len(bars_by_symbol[signal.symbol]) - 1, signal.signal_index + profile.limit_wait_minutes - 1),
            )
            stats["orders_created"] += 1
            filled, maybe_position, maybe_trade = try_fill_order(
                order,
                bars_by_symbol[signal.symbol],
                current_index=signal.signal_index,
                equity=equity,
                profile=profile,
                risk_per_trade_fraction=risk_per_trade_fraction,
                max_notional_fraction=max_notional_fraction,
            )
            if filled:
                stats["orders_filled"] += 1
                if maybe_trade is not None:
                    equity += maybe_trade.net_pnl_usdt
                    trades.append(maybe_trade)
                    next_allowed_index[(signal.symbol, signal.side)] = signal.signal_index + profile.reentry_cooldown_minutes
                elif maybe_position is not None:
                    positions.append(maybe_position)
                else:
                    stats["orders_rejected_sizing"] += 1
            elif signal.signal_index >= order.expires_index:
                stats["orders_expired"] += 1
            else:
                pending.append(order)
    for order in pending:
        stats["orders_expired"] += 1
    for position in positions:
        bars = bars_by_symbol[position.signal.symbol]
        trades.append(close_position(position, bars[-1], profile, exit_reason="data_end"))
    stats["fill_rate"] = round(stats["orders_filled"] / stats["orders_created"], 8) if stats["orders_created"] else 0.0
    return {
        "summary": summarize_trades(trades, initial_capital=initial_capital),
        "trades": [trade.to_dict() for trade in trades],
        "order_stats": stats,
    }


def try_fill_order(
    order: PendingLimitOrder,
    bars: list[BacktestBar],
    *,
    current_index: int,
    equity: float,
    profile: RhythmProfile,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> tuple[bool, RhythmPosition | None, RhythmTrade | None]:
    if current_index >= len(bars) or not order_fills_on_bar(bars[current_index], order.signal, profile):
        return False, None, None
    notional = position_notional(
        equity=equity,
        entry_price=order.signal.entry_price,
        stop_price=order.signal.stop_price,
        risk_per_trade_fraction=risk_per_trade_fraction,
        max_notional_fraction=max_notional_fraction,
    )
    if notional <= 0:
        return True, None, None
    position = RhythmPosition(
        signal=order.signal,
        entry_index=current_index,
        entry_time=bars[current_index].open_time_iso,
        entry_price=order.signal.entry_price,
        quantity=notional / order.signal.entry_price,
        notional_usdt=notional,
        dynamic_stop_price=order.signal.stop_price,
        best_price=order.signal.entry_price,
        worst_price=order.signal.entry_price,
        fees_entry_usdt=notional * entry_fee_bps(profile) / 10_000.0,
    )
    if profile.same_bar_exit_policy == "stop_only" and stop_hit_on_bar(bars[current_index], position.signal.side, position.dynamic_stop_price):
        if position.signal.side == "long":
            position = replace(position, worst_price=min(position.worst_price, bars[current_index].low), best_price=max(position.best_price, bars[current_index].high))
        else:
            position = replace(position, worst_price=max(position.worst_price, bars[current_index].high), best_price=min(position.best_price, bars[current_index].low))
        return True, None, close_position(position, bars[current_index], profile, exit_price=position.dynamic_stop_price, exit_reason="same_bar_stop_loss")
    return True, position, None


def simulate_filled_trade(
    bars: list[BacktestBar],
    signal: RhythmSignal,
    *,
    fill_index: int,
    profile: RhythmProfile,
    notional_usdt: float,
) -> RhythmTrade:
    position = RhythmPosition(
        signal=signal,
        entry_index=fill_index,
        entry_time=bars[fill_index].open_time_iso,
        entry_price=signal.entry_price,
        quantity=notional_usdt / signal.entry_price,
        notional_usdt=notional_usdt,
        dynamic_stop_price=signal.stop_price,
        best_price=signal.entry_price,
        worst_price=signal.entry_price,
        fees_entry_usdt=notional_usdt * entry_fee_bps(profile) / 10_000.0,
    )
    if profile.same_bar_exit_policy == "stop_only" and stop_hit_on_bar(bars[fill_index], signal.side, signal.stop_price):
        return close_position(position, bars[fill_index], profile, exit_price=signal.stop_price, exit_reason="same_bar_stop_loss")
    current = position
    end = len(bars) - 1
    if profile.time_exit_enabled and profile.max_hold_minutes > 0:
        end = min(end, fill_index + profile.max_hold_minutes - 1)
    for index in range(fill_index + 1, end + 1):
        trade, current = update_position_on_bar(bars, index, current, profile)
        if trade is not None:
            return trade
    return close_position(current, bars[end], profile, exit_reason="max_hold_exit" if profile.time_exit_enabled else "data_end")


def update_position_on_bar(
    bars: list[BacktestBar],
    index: int,
    position: RhythmPosition,
    profile: RhythmProfile,
) -> tuple[RhythmTrade | None, RhythmPosition]:
    bar = bars[index]
    side = position.signal.side
    if side == "long":
        best_price = max(position.best_price, bar.high)
        worst_price = min(position.worst_price, bar.low)
    else:
        best_price = min(position.best_price, bar.low)
        worst_price = max(position.worst_price, bar.high)
    excursion = replace(position, best_price=best_price, worst_price=worst_price)
    if stop_hit_on_bar(bar, side, position.dynamic_stop_price):
        reason = "trailing_stop" if stop_has_moved(side, position.dynamic_stop_price, position.signal.stop_price) else "stop_loss"
        return close_position(excursion, bar, profile, exit_price=position.dynamic_stop_price, exit_reason=reason), position
    if target_hit_on_bar(bar, side, position.signal.target_price):
        return close_position(excursion, bar, profile, exit_price=position.signal.target_price, exit_reason="take_profit"), position
    dynamic_stop = trailing_stop_price(side, position.entry_price, best_price, abs(position.entry_price - position.signal.stop_price), profile)
    if side == "long":
        dynamic_stop = max(position.dynamic_stop_price, dynamic_stop)
    else:
        dynamic_stop = min(position.dynamic_stop_price, dynamic_stop)
    updated = replace(excursion, dynamic_stop_price=dynamic_stop)
    if should_exit_for_range_invalid(bars, index, updated, profile):
        return close_position(updated, bar, profile, exit_price=bar.close, exit_reason="range_invalid_exit"), position
    if profile.time_exit_enabled and profile.max_hold_minutes > 0 and index - position.entry_index + 1 >= profile.max_hold_minutes:
        return close_position(updated, bar, profile, exit_price=bar.close, exit_reason="max_hold_exit"), position
    return None, updated


def close_position(
    position: RhythmPosition,
    bar: BacktestBar,
    profile: RhythmProfile,
    *,
    exit_reason: str,
    exit_price: float | None = None,
) -> RhythmTrade:
    raw_exit = bar.close if exit_price is None else exit_price
    slip_rate = profile.exit_slippage_bps / 10_000.0
    if position.signal.side == "long":
        exit_fill = raw_exit * (1.0 - slip_rate)
        gross_pnl = position.quantity * (exit_fill - position.entry_price)
        slippage = position.quantity * max(raw_exit - exit_fill, 0.0)
        mfe = percent_delta(position.entry_price, position.best_price)
        mae = percent_delta(position.entry_price, position.worst_price)
    else:
        exit_fill = raw_exit * (1.0 + slip_rate)
        gross_pnl = position.quantity * (position.entry_price - exit_fill)
        slippage = position.quantity * max(exit_fill - raw_exit, 0.0)
        mfe = percent_delta(position.best_price, position.entry_price)
        mae = percent_delta(position.worst_price, position.entry_price)
    exit_fee = position.quantity * exit_fill * profile.taker_fee_bps / 10_000.0
    fees = position.fees_entry_usdt + exit_fee
    net_pnl = gross_pnl - fees
    risk_usdt = abs(position.entry_price - position.signal.stop_price) * position.quantity
    return RhythmTrade(
        symbol=position.signal.symbol,
        side=position.signal.side,
        entry_time=position.entry_time,
        exit_time=bar.close_time_iso,
        entry_price=round(position.entry_price, 8),
        exit_price=round(exit_fill, 8),
        notional_usdt=round(position.notional_usdt, 8),
        gross_pnl_usdt=round(gross_pnl, 8),
        fees_usdt=round(fees, 8),
        slippage_usdt=round(slippage, 8),
        net_pnl_usdt=round(net_pnl, 8),
        hold_minutes=hold_minutes(position, bar),
        mfe_percent=round(mfe, 8),
        mae_percent=round(mae, 8),
        realized_r=round(net_pnl / risk_usdt, 8) if risk_usdt > 0 else 0.0,
        exit_reason=exit_reason,
        reason_codes=[*position.signal.reason_codes, f"exit_policy:{exit_reason}"],
    )


def should_exit_for_range_invalid(
    bars: list[BacktestBar],
    index: int,
    position: RhythmPosition,
    profile: RhythmProfile,
) -> bool:
    if index - position.entry_index + 1 < profile.min_hold_minutes:
        return False
    signal = position.signal
    span = signal.range_high_price - signal.range_low_price
    if span <= 0:
        return True
    bar = bars[index]
    buffer = span * profile.breakout_buffer_fraction
    if signal.side == "long" and bar.close < signal.range_low_price - buffer:
        return True
    if signal.side == "short" and bar.close > signal.range_high_price + buffer:
        return True
    recent = bars[max(position.entry_index, index - min(profile.lookback_minutes, 30) + 1) : index + 1]
    if len(recent) < 4:
        return False
    travel = sum(abs(current.close - previous.close) for previous, current in zip(recent, recent[1:]))
    displacement = abs(recent[-1].close - recent[0].open)
    efficiency = displacement / travel if travel > 0 else 0.0
    trend = percent_delta(recent[0].open, recent[-1].close)
    if efficiency < profile.trend_exit_path_efficiency:
        return False
    return trend < 0 if signal.side == "long" else trend > 0


def trailing_stop_price(
    side: str,
    entry_price: float,
    best_price: float,
    risk_per_unit: float,
    profile: RhythmProfile,
) -> float:
    if risk_per_unit <= 0:
        return entry_price
    min_profit_percent = profile.round_trip_cost_percent * profile.min_trailing_lock_cost_ratio
    if side == "long":
        current_r = (best_price - entry_price) / risk_per_unit
        min_profitable_stop = entry_price * (1.0 + min_profit_percent / 100.0)
        if current_r < profile.trailing_activate_r or best_price < min_profitable_stop:
            return entry_price - risk_per_unit
        return max(
            min_profitable_stop,
            entry_price + risk_per_unit * profile.trailing_lock_r,
            best_price - risk_per_unit * profile.trailing_giveback_r,
        )
    current_r = (entry_price - best_price) / risk_per_unit
    min_profitable_stop = entry_price * (1.0 - min_profit_percent / 100.0)
    if current_r < profile.trailing_activate_r or best_price > min_profitable_stop:
        return entry_price + risk_per_unit
    return min(
        min_profitable_stop,
        entry_price - risk_per_unit * profile.trailing_lock_r,
        best_price + risk_per_unit * profile.trailing_giveback_r,
    )


def stop_hit_on_bar(bar: BacktestBar, side: str, stop_price: float) -> bool:
    return bar.low <= stop_price if side == "long" else bar.high >= stop_price


def target_hit_on_bar(bar: BacktestBar, side: str, target_price: float) -> bool:
    return bar.high >= target_price if side == "long" else bar.low <= target_price


def stop_has_moved(side: str, dynamic_stop: float, initial_stop: float) -> bool:
    return dynamic_stop > initial_stop if side == "long" else dynamic_stop < initial_stop


def find_limit_fill_index(bars: list[BacktestBar], signal: RhythmSignal, profile: RhythmProfile) -> int | None:
    end = min(len(bars) - 1, signal.signal_index + profile.limit_wait_minutes - 1)
    for index in range(signal.signal_index, end + 1):
        if order_fills_on_bar(bars[index], signal, profile):
            return index
    return None


def limit_fills_on_bar(bar: BacktestBar, signal: RhythmSignal) -> bool:
    return bar.low <= signal.entry_price if signal.side == "long" else bar.high >= signal.entry_price


def order_fills_on_bar(bar: BacktestBar, signal: RhythmSignal, profile: RhythmProfile) -> bool:
    if profile.trade_direction_mode == "continuation":
        return bar.high >= signal.entry_price if signal.side == "long" else bar.low <= signal.entry_price
    return limit_fills_on_bar(bar, signal)


def entry_fee_bps(profile: RhythmProfile) -> float:
    return profile.taker_fee_bps if profile.trade_direction_mode == "continuation" else profile.maker_fee_bps


def position_notional(
    *,
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> float:
    if equity <= 0 or entry_price <= 0:
        return 0.0
    stop_fraction = abs(entry_price - stop_price) / entry_price
    if stop_fraction <= 0:
        return 0.0
    risk_notional = equity * risk_per_trade_fraction / stop_fraction
    cap_notional = equity * max_notional_fraction
    return max(0.0, min(risk_notional, cap_notional))


def summarize_trades(trades: list[RhythmTrade], *, initial_capital: float) -> dict[str, Any]:
    equity = initial_capital
    peak = initial_capital
    max_drawdown = 0.0
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    for trade in sorted(trades, key=lambda item: item.exit_time):
        equity += trade.net_pnl_usdt
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if trade.net_pnl_usdt > 0:
            wins += 1
            gross_profit += trade.net_pnl_usdt
        elif trade.net_pnl_usdt < 0:
            losses += 1
            gross_loss += abs(trade.net_pnl_usdt)
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
        "fees_usdt": round(sum(trade.fees_usdt for trade in trades), 8),
        "slippage_usdt": round(sum(trade.slippage_usdt for trade in trades), 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "max_drawdown_percent_of_initial": round(max_drawdown / initial_capital * 100.0, 8) if initial_capital else 0.0,
        "exit_reason_counts": count_by([trade.to_dict() for trade in trades], "exit_reason"),
        "side_counts": count_by([trade.to_dict() for trade in trades], "side"),
        "symbol_counts": count_by([trade.to_dict() for trade in trades], "symbol"),
    }


def failure_summary(trades: list[dict[str, Any]], *, profile: RhythmProfile) -> dict[str, Any]:
    losses = [trade for trade in trades if float(trade.get("net_pnl_usdt") or 0.0) < 0]
    buckets = {
        "direction_or_range_wrong": 0,
        "entry_or_stop_too_tight": 0,
        "profit_not_locked": 0,
        "cost_drag": 0,
    }
    cost = profile.round_trip_cost_percent
    for trade in losses:
        mfe = float(trade.get("mfe_percent") or 0.0)
        gross = float(trade.get("gross_pnl_usdt") or 0.0)
        net = float(trade.get("net_pnl_usdt") or 0.0)
        if mfe < max(cost, 0.08):
            buckets["direction_or_range_wrong"] += 1
        elif mfe >= cost * 3.0 and str(trade.get("exit_reason")) in {"stop_loss", "same_bar_stop_loss"}:
            buckets["entry_or_stop_too_tight"] += 1
        elif mfe >= cost * 3.0 and net < 0:
            buckets["profit_not_locked"] += 1
        elif gross >= 0 and net < 0:
            buckets["cost_drag"] += 1
        else:
            buckets["entry_or_stop_too_tight"] += 1
    return {
        "loss_count": len(losses),
        "bucket_counts": buckets,
        "loss_exit_reason_counts": count_by(losses, "exit_reason"),
        "loss_side_counts": count_by(losses, "side"),
        "loss_symbol_counts": count_by(losses, "symbol"),
    }


def profile_selection_score(summary: dict[str, Any], *, min_trades: int) -> float:
    trade_count = int(summary.get("trade_count") or 0)
    if trade_count <= 0:
        return -1_000_000.0
    pf = profit_factor_value(summary.get("profit_factor"))
    score = (
        float(summary.get("return_percent") or 0.0)
        + pf * 3.0
        + float(summary.get("win_rate") or 0.0) * 4.0
        - float(summary.get("max_drawdown_percent_of_initial") or 0.0) * 1.7
    )
    if trade_count < min_trades:
        score -= 1_000.0 + (min_trades - trade_count) / max(min_trades, 1) * 100.0
    if float(summary.get("return_percent") or 0.0) <= 0.0:
        score -= 25.0
    return score


def scan_signal_diagnostics(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RhythmProfile,
    stride: int,
) -> dict[str, Any]:
    evaluated = 0
    signal_count = 0
    rejection_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    symbol_signal_counts: dict[str, int] = {}
    for symbol, bars in bars_by_symbol.items():
        for index in range(profile.lookback_minutes, len(bars), max(1, stride)):
            evaluated += 1
            signal, reasons = evaluate_rhythm_signal(symbol, bars, index, profile)
            if signal is None:
                for reason in reasons:
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                continue
            signal_count += 1
            side_counts[signal.side] = side_counts.get(signal.side, 0) + 1
            symbol_signal_counts[signal.symbol] = symbol_signal_counts.get(signal.symbol, 0) + 1
    return {
        "symbols": len(bars_by_symbol),
        "stride": max(1, stride),
        "evaluated_windows": evaluated,
        "signal_count": signal_count,
        "signal_rate": round(signal_count / evaluated, 8) if evaluated else 0.0,
        "side_counts": dict(sorted(side_counts.items())),
        "symbol_signal_counts": dict(sorted(symbol_signal_counts.items())),
        "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)),
    }


def edge_touch_sequence(
    window: list[BacktestBar],
    *,
    lower_zone: float,
    upper_zone: float,
) -> list[tuple[int, str]]:
    sequence: list[tuple[int, str]] = []
    for index, bar in enumerate(window):
        lower = bar.low <= lower_zone
        upper = bar.high >= upper_zone
        if lower and upper:
            ordered = ("lower", "upper") if bar.close >= bar.open else ("upper", "lower")
            for edge in ordered:
                if not sequence or sequence[-1][1] != edge:
                    sequence.append((index, edge))
            continue
        if lower and (not sequence or sequence[-1][1] != "lower"):
            sequence.append((index, "lower"))
        if upper and (not sequence or sequence[-1][1] != "upper"):
            sequence.append((index, "upper"))
    return sequence


def reaction_stats(
    window: list[BacktestBar],
    *,
    support: float,
    resistance: float,
    lower_zone: float,
    upper_zone: float,
    reaction_window: int,
) -> tuple[float, int]:
    midpoint = support + (resistance - support) * 0.5
    samples = 0
    successes = 0
    for index, bar in enumerate(window[:-1]):
        future = window[index + 1 : min(len(window), index + 1 + max(1, reaction_window))]
        if not future:
            continue
        lower = bar.low <= lower_zone
        upper = bar.high >= upper_zone
        if lower and not upper:
            samples += 1
            if max(item.high for item in future) >= midpoint:
                successes += 1
        elif upper and not lower:
            samples += 1
            if min(item.low for item in future) <= midpoint:
                successes += 1
    return (successes / samples if samples else 0.0), samples


def mid_cross_count(window: list[BacktestBar], *, midpoint: float) -> int:
    states: list[int] = []
    for bar in window:
        state = 1 if bar.close > midpoint else -1 if bar.close < midpoint else 0
        if state == 0:
            continue
        if not states or states[-1] != state:
            states.append(state)
    return sum(1 for previous, current in zip(states, states[1:]) if previous != current)


def band_shift_ratio(window: list[BacktestBar], profile: RhythmProfile) -> float:
    if len(window) < 6:
        return 0.0
    midpoint = len(window) // 2
    first = window[:midpoint]
    second = window[midpoint:]
    first_support = percentile([bar.low for bar in first], profile.band_quantile)
    first_resistance = percentile([bar.high for bar in first], 100.0 - profile.band_quantile)
    second_support = percentile([bar.low for bar in second], profile.band_quantile)
    second_resistance = percentile([bar.high for bar in second], 100.0 - profile.band_quantile)
    span = percentile([bar.high for bar in window], 100.0 - profile.band_quantile) - percentile(
        [bar.low for bar in window],
        profile.band_quantile,
    )
    if span <= 0:
        return math.inf
    return max(abs(second_support - first_support), abs(second_resistance - first_resistance)) / span


def recent_volume_ratio(window: list[BacktestBar], *, recent_bars: int = 5) -> float | None:
    if len(window) <= recent_bars:
        return None
    recent = [bar.quote_volume for bar in window[-recent_bars:] if bar.quote_volume > 0]
    baseline = [bar.quote_volume for bar in window[:-recent_bars] if bar.quote_volume > 0]
    if not recent or not baseline:
        return None
    baseline_mean = sum(baseline) / len(baseline)
    return (sum(recent) / len(recent)) / baseline_mean if baseline_mean > 0 else None


def hold_minutes(position: RhythmPosition, exit_bar: BacktestBar) -> int:
    entry_open_time = int(datetime.fromisoformat(position.entry_time.replace("Z", "+00:00")).timestamp() * 1000)
    return max(1, int((exit_bar.close_time - entry_open_time) / ONE_MINUTE_MS) + 1)


def empty_order_stats() -> dict[str, Any]:
    return {
        "signals_selected": 0,
        "orders_created": 0,
        "orders_filled": 0,
        "orders_expired": 0,
        "orders_rejected_sizing": 0,
        "orders_canceled_symbol_active": 0,
        "fill_rate": 0.0,
    }


def profit_factor_value(value: Any) -> float:
    if value == "inf":
        return 4.0
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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


if __name__ == "__main__":
    raise SystemExit(main())
