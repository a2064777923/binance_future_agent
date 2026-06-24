"""Research orderly range-reversion on Binance USD-M 1m klines.

The script has two phases:

1. Learn a conservative range profile from a training window.
2. Replay a later test window as a multi-symbol portfolio that scans every
   minute, chooses the best current candidates, and compounds realized equity.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from bfa.backtest.models import BacktestBar


KLINE_ARCHIVE_URL = "https://data.binance.vision/data/futures/um/daily/klines"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
ONE_MINUTE_MS = 60_000


@dataclass(frozen=True)
class RangeProfile:
    lookback_minutes: int = 45
    min_width_percent: float = 0.75
    max_width_percent: float = 3.0
    max_path_efficiency: float = 0.3
    max_volume_cv: float = 0.35
    max_trend_abs_percent: float = 0.22
    min_touch_count: int = 2
    min_edge_alternations: int = 2
    min_mid_cross_count: int = 1
    max_recent_edge_push_efficiency: float = 0.72
    max_recent_volume_expansion: float = 2.2
    low_zone_percent: float = 20.0
    high_zone_percent: float = 80.0
    min_width_cost_ratio: float = 5.0
    min_quote_volume_usdt: float = 500_000.0
    entry_edge_fraction: float = 0.14
    stop_range_fraction: float = 0.3
    target_range_fraction: float = 0.5
    limit_wait_minutes: int = 3
    min_hold_minutes: int = 1
    max_hold_minutes: int = 20
    trailing_activate_r: float = 0.25
    trailing_lock_r: float = 0.06
    trailing_giveback_r: float = 0.14
    min_trailing_lock_cost_ratio: float = 1.2
    reentry_cooldown_minutes: int = 8
    breakout_buffer_fraction: float = 0.1
    trend_exit_path_efficiency: float = 0.62
    fee_bps: float = 4.0
    slippage_bps: float = 3.0

    @property
    def round_trip_cost_percent(self) -> float:
        return 2.0 * (max(self.fee_bps, 0.0) + max(self.slippage_bps, 0.0)) / 100.0


@dataclass(frozen=True)
class RangeFeatures:
    width_percent: float
    close_position_percent: float
    lower_touch_count: int
    upper_touch_count: int
    edge_alternation_count: int
    mid_cross_count: int
    volume_cv: float | None
    path_efficiency: float
    trend_percent: float
    recent_trend_percent: float
    recent_path_efficiency: float
    recent_volume_expansion: float | None
    quote_volume_mean: float
    low_price: float
    high_price: float
    reference_price: float

    @property
    def abs_trend_percent(self) -> float:
        return abs(self.trend_percent)


@dataclass(frozen=True)
class RangeSignal:
    symbol: str
    side: str
    signal_index: int
    score: float
    entry_price: float
    stop_price: float
    target_price: float
    range_low_price: float
    range_high_price: float
    features: RangeFeatures
    reason_codes: list[str]


@dataclass(frozen=True)
class ResearchTrade:
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


@dataclass(frozen=True)
class PendingOrder:
    signal: RangeSignal
    created_index: int
    expires_index: int


@dataclass(frozen=True)
class OpenPosition:
    signal: RangeSignal
    entry_index: int
    entry_time: str
    entry_price: float
    raw_entry_price: float
    quantity: float
    notional_usdt: float
    dynamic_stop_price: float
    best_price: float
    worst_price: float
    fees_entry_usdt: float
    slippage_entry_usdt: float


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
    parser.add_argument("--training-stride-minutes", type=int, default=3)
    parser.add_argument("--min-train-trades", type=int, default=25)
    parser.add_argument("--validation-days", type=int, default=5)
    parser.add_argument("--min-validation-trades", type=int, default=5)
    parser.add_argument("--max-grid-profiles", type=int, default=48)
    parser.add_argument("--test-leaderboard-profiles", type=int, default=0)
    parser.add_argument("--profile-json", help="optional profile JSON file to skip grid learning")
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
    if args.profile_json:
        profile = RangeProfile(**json.loads(Path(args.profile_json).read_text(encoding="utf-8")))
        leaderboard: list[dict[str, Any]] = []
        train_summary = {"skipped": "profile_json_supplied"}
    else:
        profile, leaderboard, train_summary = learn_profile(
            fit_bars,
            validation_bars_by_symbol=validation_bars,
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
        "schema": "bfa_orderly_range_research_v1",
        "method": {
            "data_source": "Binance USD-M public daily 1m kline archives",
            "training": "grid-search profile selection on the training window using independent quick range-reversion trades",
            "validation": (
                "when validation-days is positive, the final validation slice of the training window is used for "
                "profile selection after minimum fit-sample checks"
            ),
            "test_replay": "minute-by-minute multi-symbol portfolio scan with pending limit fills, one side per symbol, dynamic equity sizing, fees, and slippage",
            "no_future_leak": "signals at minute t use only completed bars before t; exits use later bars only after entry",
        },
        "symbols": symbols,
        "train_window": {"start_date": train_start.isoformat(), "end_date": train_end.isoformat()},
        "test_window": {"start_date": test_start.isoformat(), "end_date": test_end.isoformat()},
        "profile": asdict(profile),
        "train_summary": train_summary,
        "leaderboard": leaderboard[:20],
        "test_leaderboard": test_leaderboard,
        "test_summary": test_result["summary"],
        "test_trades": test_result["trades"],
        "diagnostics": {
            "train_selected_profile": scan_signal_diagnostics(
                fit_bars,
                profile=profile,
                stride=max(1, args.training_stride_minutes),
            ),
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


def parse_symbols(value: str | None) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def resolve_top_symbols(top_n: int, min_quote_volume: float) -> list[str]:
    exchange = json.loads(urlopen(EXCHANGE_INFO_URL, timeout=30).read().decode("utf-8"))
    valid = {
        str(item.get("symbol", "")).upper()
        for item in exchange.get("symbols", [])
        if item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
        and item.get("status") == "TRADING"
    }
    tickers = json.loads(urlopen(TICKER_24H_URL, timeout=30).read().decode("utf-8"))
    ranked: list[tuple[float, float, str]] = []
    for item in tickers:
        symbol = str(item.get("symbol", "")).upper()
        if symbol not in valid:
            continue
        quote_volume = _float(item.get("quoteVolume")) or 0.0
        if quote_volume < min_quote_volume:
            continue
        change = abs(_float(item.get("priceChangePercent")) or 0.0)
        ranked.append((quote_volume, change, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, _, symbol in ranked[: max(1, top_n)]]


def load_many_symbol_klines(
    symbols: list[str],
    start: date,
    end: date,
    cache_dir: Path,
) -> dict[str, list[BacktestBar]]:
    return {
        symbol: bars
        for symbol in symbols
        if (bars := load_symbol_klines(symbol, start, end, cache_dir))
    }


def split_validation_bars(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    train_end: date,
    validation_days: int,
) -> tuple[dict[str, list[BacktestBar]], dict[str, list[BacktestBar]]]:
    if validation_days <= 0:
        return bars_by_symbol, {}
    validation_start = train_end - timedelta(days=validation_days - 1)
    cutoff_ms = int(datetime.combine(validation_start, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    fit: dict[str, list[BacktestBar]] = {}
    validation: dict[str, list[BacktestBar]] = {}
    for symbol, bars in bars_by_symbol.items():
        fit_bars = [bar for bar in bars if bar.open_time < cutoff_ms]
        validation_symbol_bars = [bar for bar in bars if bar.open_time >= cutoff_ms]
        if fit_bars:
            fit[symbol] = fit_bars
        if validation_symbol_bars:
            validation[symbol] = validation_symbol_bars
    return fit, validation


def load_symbol_klines(symbol: str, start: date, end: date, cache_dir: Path) -> list[BacktestBar]:
    bars: list[BacktestBar] = []
    current = start
    while current <= end:
        try:
            rows = read_daily_kline_zip(fetch_daily_kline_zip(symbol, current, cache_dir))
        except Exception:
            current += timedelta(days=1)
            continue
        bars.extend(BacktestBar.from_binance_kline(symbol, row) for row in rows)
        current += timedelta(days=1)
    return sorted(bars, key=lambda item: item.open_time)


def fetch_daily_kline_zip(symbol: str, day: date, cache_dir: Path, *, interval: str = "1m") -> Path:
    symbol_dir = cache_dir / symbol.upper() / interval
    symbol_dir.mkdir(parents=True, exist_ok=True)
    name = f"{symbol.upper()}-{interval}-{day.isoformat()}.zip"
    path = symbol_dir / name
    if path.exists() and path.stat().st_size > 0:
        return path
    url = f"{KLINE_ARCHIVE_URL}/{symbol.upper()}/{interval}/{name}"
    with urlopen(url, timeout=60) as response:
        path.write_bytes(response.read())
    return path


def read_daily_kline_zip(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8")
            rows: list[list[str]] = []
            for row in csv.reader(text):
                if len(row) < 8 or not row[0].strip().isdigit():
                    continue
                rows.append(row)
            return rows


def learn_profile(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    validation_bars_by_symbol: dict[str, list[BacktestBar]] | None = None,
    training_stride_minutes: int,
    min_train_trades: int,
    min_validation_trades: int,
    max_grid_profiles: int | None = None,
) -> tuple[RangeProfile, list[dict[str, Any]], dict[str, Any]]:
    base = RangeProfile()
    grid = profile_grid(base, max_profiles=max_grid_profiles)
    leaderboard: list[dict[str, Any]] = []
    best_profile: RangeProfile | None = None
    best_score = -math.inf
    best_fallback_profile: RangeProfile | None = None
    best_fallback_score = -math.inf
    has_validation = bool(validation_bars_by_symbol)
    for profile in grid:
        fit_trades = independent_training_trades(
            bars_by_symbol,
            profile=profile,
            stride=max(1, training_stride_minutes),
        )
        fit_summary = summarize_trades(fit_trades, initial_capital=30.0)
        validation_summary: dict[str, Any] | None = None
        selection_summary = fit_summary
        required_selection_trades = min_train_trades
        if has_validation:
            validation_trades = independent_training_trades(
                validation_bars_by_symbol or {},
                profile=profile,
                stride=max(1, training_stride_minutes),
            )
            validation_summary = summarize_trades(validation_trades, initial_capital=30.0)
            selection_summary = validation_summary
            required_selection_trades = min_validation_trades
        score = profile_selection_score(selection_summary, min_train_trades=required_selection_trades)
        fit_trade_count = int(fit_summary.get("trade_count") or 0)
        validation_trade_count = int((validation_summary or {}).get("trade_count") or 0)
        eligible_for_selection = fit_trade_count >= min_train_trades and (
            not has_validation or validation_trade_count >= min_validation_trades
        )
        row = {
            "score": round(score, 8),
            "eligible_for_selection": eligible_for_selection,
            "profile": asdict(profile),
            "summary": selection_summary,
            "fit_summary": fit_summary,
            "validation_summary": validation_summary,
        }
        leaderboard.append(row)
        if score > best_fallback_score:
            best_fallback_score = score
            best_fallback_profile = profile
        if not eligible_for_selection:
            continue
        if best_profile is None or score > best_score:
            best_score = score
            best_profile = profile
    leaderboard.sort(key=lambda item: item["score"], reverse=True)
    selected = best_profile or best_fallback_profile or base
    selected_summary = next(
        (row["summary"] for row in leaderboard if row["profile"] == asdict(selected)),
        leaderboard[0]["summary"] if leaderboard else {},
    )
    return selected, leaderboard, selected_summary


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
        profile_payload = row.get("profile")
        if not isinstance(profile_payload, dict):
            continue
        key = json.dumps(profile_payload, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        profile = RangeProfile(**profile_payload)
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
                "profile": profile_payload,
                "fit_summary": row.get("fit_summary"),
                "validation_summary": row.get("validation_summary"),
                "test_summary": result["summary"],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def profile_grid(base: RangeProfile, *, max_profiles: int | None = None) -> list[RangeProfile]:
    profiles: list[RangeProfile] = []
    for lookback in (20, 30, 45, 60):
        for min_width in (0.45, 0.6, 0.8, 1.0):
            for max_width in (2.5, 3.5, 5.0):
                for max_path in (0.24, 0.32, 0.42, 0.52):
                    for max_volume_cv in (0.25, 0.4, 0.6):
                        for max_trend_abs in (0.22, 0.35, 0.5):
                            for alternations in (2, 3):
                                for mid_cross in (1, 2):
                                    profiles.append(
                                        replace(
                                            base,
                                            lookback_minutes=lookback,
                                            min_width_percent=min_width,
                                            max_width_percent=max_width,
                                            max_path_efficiency=max_path,
                                            max_volume_cv=max_volume_cv,
                                            max_trend_abs_percent=max_trend_abs,
                                            min_edge_alternations=alternations,
                                            min_mid_cross_count=mid_cross,
                                        )
                                    )
    if max_profiles is None or max_profiles <= 0:
        return profiles
    if max_profiles >= len(profiles):
        return profiles
    if max_profiles == 1:
        return [profiles[0]]
    step = (len(profiles) - 1) / (max_profiles - 1)
    selected_indexes = sorted({round(index * step) for index in range(max_profiles)})
    return [profiles[index] for index in selected_indexes]


def independent_training_trades(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RangeProfile,
    stride: int,
) -> list[ResearchTrade]:
    trades: list[ResearchTrade] = []
    next_allowed_index: dict[tuple[str, str], int] = {}
    for symbol, bars in bars_by_symbol.items():
        for signal_index in range(profile.lookback_minutes, len(bars), stride):
            signal = build_range_signal(symbol, bars, signal_index, profile)
            if signal is None:
                continue
            cooldown_key = (signal.symbol, signal.side)
            if signal_index < next_allowed_index.get(cooldown_key, -1):
                continue
            trade = simulate_independent_trade(bars, signal, profile, notional_usdt=20.0)
            if trade is not None:
                trades.append(trade)
                next_allowed_index[cooldown_key] = signal_index + profile.reentry_cooldown_minutes
    return trades


def build_range_signal(
    symbol: str,
    bars: list[BacktestBar],
    signal_index: int,
    profile: RangeProfile,
) -> RangeSignal | None:
    if signal_index < profile.lookback_minutes or signal_index >= len(bars):
        return None
    features = range_features(bars[signal_index - profile.lookback_minutes : signal_index])
    if features is None or not features_pass_profile(features, profile):
        return None
    if features.close_position_percent <= profile.low_zone_percent:
        side = "long"
        span = features.high_price - features.low_price
        entry = features.low_price + span * profile.entry_edge_fraction
        stop = entry - span * profile.stop_range_fraction
        target = entry + span * profile.target_range_fraction
    elif features.close_position_percent >= profile.high_zone_percent:
        side = "short"
        span = features.high_price - features.low_price
        entry = features.high_price - span * profile.entry_edge_fraction
        stop = entry + span * profile.stop_range_fraction
        target = entry - span * profile.target_range_fraction
    else:
        return None
    score = score_features(features, profile)
    return RangeSignal(
        symbol=symbol.upper(),
        side=side,
        signal_index=signal_index,
        score=score,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        range_low_price=features.low_price,
        range_high_price=features.high_price,
        features=features,
        reason_codes=[
            "signal_mode:orderly_range_reversion",
            f"range_width_percent:{round(features.width_percent, 4)}",
            f"range_edge_alternations:{features.edge_alternation_count}",
            f"range_mid_crosses:{features.mid_cross_count}",
        ],
    )


def range_features(window: list[BacktestBar]) -> RangeFeatures | None:
    if len(window) < 3:
        return None
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    reference = window[-1].close
    if high <= low or reference <= 0:
        return None
    span = high - low
    lower_zone = low + span * 0.22
    upper_zone = high - span * 0.22
    volumes = [bar.quote_volume for bar in window if bar.quote_volume > 0]
    travel = sum(abs(current.close - previous.close) for previous, current in zip(window, window[1:]))
    displacement = abs(window[-1].close - window[0].open)
    return RangeFeatures(
        width_percent=span / reference * 100.0,
        close_position_percent=(reference - low) / span * 100.0,
        lower_touch_count=sum(1 for bar in window if bar.low <= lower_zone),
        upper_touch_count=sum(1 for bar in window if bar.high >= upper_zone),
        edge_alternation_count=range_edge_alternations(window, lower_zone=lower_zone, upper_zone=upper_zone),
        mid_cross_count=range_mid_cross_count(window, midpoint=low + span * 0.5),
        volume_cv=coefficient_of_variation(volumes),
        path_efficiency=displacement / travel if travel > 0 else 0.0,
        trend_percent=percent_delta(window[0].open, window[-1].close),
        recent_trend_percent=recent_trend_percent(window),
        recent_path_efficiency=recent_path_efficiency(window),
        recent_volume_expansion=recent_volume_expansion(window),
        quote_volume_mean=sum(volumes) / len(volumes) if volumes else 0.0,
        low_price=low,
        high_price=high,
        reference_price=reference,
    )


def features_pass_profile(features: RangeFeatures, profile: RangeProfile) -> bool:
    return not profile_rejection_reasons(features, profile)


def profile_rejection_reasons(features: RangeFeatures, profile: RangeProfile) -> list[str]:
    reasons: list[str] = []
    if not (profile.min_width_percent <= features.width_percent <= profile.max_width_percent):
        reasons.append("range_width_outside_profile")
    if features.path_efficiency > profile.max_path_efficiency:
        reasons.append("path_too_directional")
    if features.abs_trend_percent > profile.max_trend_abs_percent:
        reasons.append("trend_too_large")
    if features.volume_cv is None or features.volume_cv > profile.max_volume_cv:
        reasons.append("volume_too_irregular")
    if min(features.lower_touch_count, features.upper_touch_count) < profile.min_touch_count:
        reasons.append("not_enough_edge_touches")
    if features.edge_alternation_count < profile.min_edge_alternations:
        reasons.append("not_enough_edge_alternations")
    if features.mid_cross_count < profile.min_mid_cross_count:
        reasons.append("not_enough_mid_crosses")
    recent_push_is_adverse = (
        features.close_position_percent <= profile.low_zone_percent
        and features.recent_trend_percent < 0
        and features.recent_path_efficiency > profile.max_recent_edge_push_efficiency
    ) or (
        features.close_position_percent >= profile.high_zone_percent
        and features.recent_trend_percent > 0
        and features.recent_path_efficiency > profile.max_recent_edge_push_efficiency
    )
    if recent_push_is_adverse:
        reasons.append("recent_edge_push_too_directional")
    if (
        recent_push_is_adverse
        and features.recent_volume_expansion is not None
        and features.recent_volume_expansion > profile.max_recent_volume_expansion
    ):
        reasons.append("recent_edge_push_volume_expansion")
    if features.quote_volume_mean < profile.min_quote_volume_usdt:
        reasons.append("liquidity_too_low")
    cost_ratio = features.width_percent / profile.round_trip_cost_percent if profile.round_trip_cost_percent > 0 else math.inf
    if cost_ratio < profile.min_width_cost_ratio:
        reasons.append("range_too_narrow_for_cost")
    if not (features.close_position_percent <= profile.low_zone_percent or features.close_position_percent >= profile.high_zone_percent):
        reasons.append("price_not_near_range_edge")
    return reasons


def score_features(features: RangeFeatures, profile: RangeProfile) -> float:
    cost_ratio = features.width_percent / profile.round_trip_cost_percent if profile.round_trip_cost_percent > 0 else 0.0
    edge_position = min(features.close_position_percent, 100.0 - features.close_position_percent)
    edge_bonus = max(0.0, 25.0 - edge_position) / 25.0
    volume_penalty = features.volume_cv or 1.0
    return (
        cost_ratio
        + features.edge_alternation_count * 0.8
        + features.mid_cross_count * 0.45
        + edge_bonus * 2.0
        - features.path_efficiency * 4.0
        - features.recent_path_efficiency * 1.2
        - volume_penalty * 2.0
        - features.abs_trend_percent * 1.5
    )


def simulate_independent_trade(
    bars: list[BacktestBar],
    signal: RangeSignal,
    profile: RangeProfile,
    *,
    notional_usdt: float,
) -> ResearchTrade | None:
    fill_index = find_limit_fill_index(bars, signal, profile)
    if fill_index is None:
        return None
    return simulate_open_position_to_exit(
        bars,
        OpenPosition(
            signal=signal,
            entry_index=fill_index,
            entry_time=bars[fill_index].open_time_iso,
            entry_price=signal.entry_price,
            raw_entry_price=signal.entry_price,
            quantity=notional_usdt / signal.entry_price,
            notional_usdt=notional_usdt,
            dynamic_stop_price=signal.stop_price,
            best_price=signal.entry_price,
            worst_price=signal.entry_price,
            fees_entry_usdt=notional_usdt * profile.fee_bps / 10_000.0,
            slippage_entry_usdt=0.0,
        ),
        profile=profile,
    )


def run_portfolio_backtest(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RangeProfile,
    initial_capital: float,
    max_open_positions: int,
    max_new_entries_per_minute: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> dict[str, Any]:
    if not bars_by_symbol:
        return {"summary": summarize_trades([], initial_capital=initial_capital), "trades": []}
    time_index: dict[int, dict[str, int]] = {}
    for symbol, bars in bars_by_symbol.items():
        for index, bar in enumerate(bars):
            time_index.setdefault(bar.open_time, {})[symbol] = index
    equity = initial_capital
    open_positions: list[OpenPosition] = []
    pending: list[PendingOrder] = []
    trades: list[ResearchTrade] = []
    next_allowed_index: dict[tuple[str, str], int] = {}
    for open_time in sorted(time_index):
        index_by_symbol = time_index[open_time]
        still_pending: list[PendingOrder] = []
        for order in pending:
            current_index = index_by_symbol.get(order.signal.symbol)
            if current_index is None or current_index > order.expires_index:
                continue
            if limit_fills_on_bar(indexed_bar(bars_by_symbol, order.signal.symbol, current_index), order.signal):
                notional = position_notional(
                    equity=equity,
                    entry_price=order.signal.entry_price,
                    stop_price=order.signal.stop_price,
                    risk_per_trade_fraction=risk_per_trade_fraction,
                    max_notional_fraction=max_notional_fraction,
                )
                if notional > 0:
                    open_positions.append(
                        OpenPosition(
                            signal=order.signal,
                            entry_index=current_index,
                            entry_time=indexed_bar(bars_by_symbol, order.signal.symbol, current_index).open_time_iso,
                            entry_price=order.signal.entry_price,
                            raw_entry_price=order.signal.entry_price,
                            quantity=notional / order.signal.entry_price,
                            notional_usdt=notional,
                            dynamic_stop_price=order.signal.stop_price,
                            best_price=order.signal.entry_price,
                            worst_price=order.signal.entry_price,
                            fees_entry_usdt=notional * profile.fee_bps / 10_000.0,
                            slippage_entry_usdt=0.0,
                        )
                    )
                continue
            still_pending.append(order)
        pending = still_pending

        next_open_positions: list[OpenPosition] = []
        for position in open_positions:
            current_index = index_by_symbol.get(position.signal.symbol)
            if current_index is None or current_index <= position.entry_index:
                next_open_positions.append(position)
                continue
            maybe_trade, updated = update_position_on_bar(
                bars_by_symbol[position.signal.symbol],
                current_index,
                position,
                profile,
            )
            if maybe_trade is None:
                next_open_positions.append(updated)
                continue
            equity += maybe_trade.net_pnl_usdt
            trades.append(maybe_trade)
            next_allowed_index[(position.signal.symbol, position.signal.side)] = current_index + profile.reentry_cooldown_minutes
        open_positions = next_open_positions

        active_symbols = {position.signal.symbol for position in open_positions} | {order.signal.symbol for order in pending}
        capacity = max_open_positions - len(open_positions) - len(pending)
        if capacity <= 0:
            continue
        candidates: list[RangeSignal] = []
        for symbol, bars in bars_by_symbol.items():
            if symbol in active_symbols:
                continue
            signal_index = index_by_symbol.get(symbol)
            if signal_index is None:
                continue
            signal = build_range_signal(symbol, bars, signal_index, profile)
            if signal is not None:
                if signal_index < next_allowed_index.get((signal.symbol, signal.side), -1):
                    continue
                candidates.append(signal)
        candidates.sort(key=lambda item: item.score, reverse=True)
        for signal in candidates[: min(capacity, max_new_entries_per_minute)]:
            pending.append(
                PendingOrder(
                    signal=signal,
                    created_index=signal.signal_index,
                    expires_index=min(len(bars_by_symbol[signal.symbol]) - 1, signal.signal_index + profile.limit_wait_minutes - 1),
                )
            )
    for position in open_positions:
        bars = bars_by_symbol[position.signal.symbol]
        if position.entry_index < len(bars):
            trades.append(close_position(position, bars[-1], profile, exit_reason="data_end"))
    return {
        "summary": summarize_trades(trades, initial_capital=initial_capital),
        "trades": [trade.to_dict() for trade in trades],
    }


def indexed_bar(bars_by_symbol: dict[str, list[BacktestBar]], symbol: str, index: int) -> BacktestBar:
    return bars_by_symbol[symbol][index]


def position_notional(
    *,
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
) -> float:
    stop_fraction = abs(entry_price - stop_price) / entry_price
    if equity <= 0 or stop_fraction <= 0:
        return 0.0
    risk_notional = equity * risk_per_trade_fraction / stop_fraction
    cap_notional = equity * max_notional_fraction
    return max(0.0, min(risk_notional, cap_notional))


def find_limit_fill_index(bars: list[BacktestBar], signal: RangeSignal, profile: RangeProfile) -> int | None:
    end_index = min(len(bars) - 1, signal.signal_index + profile.limit_wait_minutes - 1)
    for index in range(signal.signal_index, end_index + 1):
        if limit_fills_on_bar(bars[index], signal):
            return index
    return None


def limit_fills_on_bar(bar: BacktestBar, signal: RangeSignal) -> bool:
    if signal.side == "long":
        return bar.low <= signal.entry_price
    return bar.high >= signal.entry_price


def update_position_on_bar(
    bars: list[BacktestBar],
    index: int,
    position: OpenPosition,
    profile: RangeProfile,
) -> tuple[ResearchTrade | None, OpenPosition]:
    bar = bars[index]
    signal = position.signal
    dynamic_stop = position.dynamic_stop_price
    best_price = position.best_price
    worst_price = position.worst_price
    risk_per_unit = abs(position.entry_price - signal.stop_price)
    if signal.side == "long":
        excursion_best_price = max(best_price, bar.high)
        excursion_worst_price = min(worst_price, bar.low)
    else:
        excursion_best_price = min(best_price, bar.low)
        excursion_worst_price = max(worst_price, bar.high)
    excursion_position = replace(
        position,
        best_price=excursion_best_price,
        worst_price=excursion_worst_price,
    )
    if signal.side == "long":
        hit_stop = bar.low <= dynamic_stop
        hit_target = bar.high >= signal.target_price
    else:
        hit_stop = bar.high >= dynamic_stop
        hit_target = bar.low <= signal.target_price
    if hit_stop:
        exit_reason = "trailing_stop" if stop_has_moved(position.signal.side, dynamic_stop, signal.stop_price) else "stop_loss"
        return close_position(excursion_position, bar, profile, exit_price=dynamic_stop, exit_reason=exit_reason), position
    if hit_target:
        return close_position(excursion_position, bar, profile, exit_price=signal.target_price, exit_reason="take_profit"), position

    if risk_per_unit > 0:
        if signal.side == "long":
            best_price = excursion_best_price
            worst_price = excursion_worst_price
            dynamic_stop = max(dynamic_stop, trailing_stop_price(signal.side, position.entry_price, best_price, risk_per_unit, profile))
        else:
            best_price = excursion_best_price
            worst_price = excursion_worst_price
            dynamic_stop = min(dynamic_stop, trailing_stop_price(signal.side, position.entry_price, best_price, risk_per_unit, profile))
    if should_exit_for_breakout_or_trend(bars, index, position, profile):
        return close_position(excursion_position, bar, profile, exit_price=bar.close, exit_reason="range_invalid_exit"), position
    if index - position.entry_index + 1 >= profile.max_hold_minutes:
        return close_position(excursion_position, bar, profile, exit_price=bar.close, exit_reason="max_hold_safety_exit"), position
    return None, replace(position, dynamic_stop_price=dynamic_stop, best_price=best_price, worst_price=worst_price)


def trailing_stop_price(
    side: str,
    entry_price: float,
    best_price: float,
    risk_per_unit: float,
    profile: RangeProfile,
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


def stop_has_moved(side: str, dynamic_stop: float, initial_stop: float) -> bool:
    if side == "long":
        return dynamic_stop > initial_stop
    return dynamic_stop < initial_stop


def should_exit_for_breakout_or_trend(
    bars: list[BacktestBar],
    index: int,
    position: OpenPosition,
    profile: RangeProfile,
) -> bool:
    if index - position.entry_index + 1 < profile.min_hold_minutes:
        return False
    signal = position.signal
    bar = bars[index]
    span = signal.range_high_price - signal.range_low_price
    if span <= 0:
        return True
    buffer = span * profile.breakout_buffer_fraction
    if signal.side == "long" and bar.close < signal.range_low_price - buffer:
        return True
    if signal.side == "short" and bar.close > signal.range_high_price + buffer:
        return True
    recent = bars[max(position.entry_index, index - profile.lookback_minutes + 1) : index + 1]
    features = range_features(recent)
    if features is None or features.path_efficiency < profile.trend_exit_path_efficiency:
        return False
    if signal.side == "long":
        return features.trend_percent < 0
    return features.trend_percent > 0


def simulate_open_position_to_exit(
    bars: list[BacktestBar],
    position: OpenPosition,
    *,
    profile: RangeProfile,
) -> ResearchTrade:
    current = position
    end = min(len(bars) - 1, current.entry_index + profile.max_hold_minutes - 1)
    for index in range(current.entry_index + 1, end + 1):
        trade, current = update_position_on_bar(bars, index, current, profile)
        if trade is not None:
            return trade
    return close_position(current, bars[end], profile, exit_reason="max_hold_safety_exit")


def close_position(
    position: OpenPosition,
    bar: BacktestBar,
    profile: RangeProfile,
    *,
    exit_price: float | None = None,
    exit_reason: str,
) -> ResearchTrade:
    raw_exit = bar.close if exit_price is None else exit_price
    slip_rate = profile.slippage_bps / 10_000.0
    if position.signal.side == "long":
        exit_fill = raw_exit * (1.0 - slip_rate)
        gross_pnl = position.quantity * (exit_fill - position.entry_price)
        exit_slippage = position.quantity * max(raw_exit - exit_fill, 0.0)
    else:
        exit_fill = raw_exit * (1.0 + slip_rate)
        gross_pnl = position.quantity * (position.entry_price - exit_fill)
        exit_slippage = position.quantity * max(exit_fill - raw_exit, 0.0)
    exit_fee = position.quantity * exit_fill * profile.fee_bps / 10_000.0
    fees = position.fees_entry_usdt + exit_fee
    slippage = position.slippage_entry_usdt + exit_slippage
    if position.signal.side == "long":
        mfe_percent = percent_delta(position.entry_price, position.best_price)
        mae_percent = percent_delta(position.entry_price, position.worst_price)
    else:
        mfe_percent = percent_delta(position.best_price, position.entry_price)
        mae_percent = percent_delta(position.worst_price, position.entry_price)
    initial_risk_per_unit = abs(position.entry_price - position.signal.stop_price)
    risk_usdt = initial_risk_per_unit * position.quantity
    net_pnl = gross_pnl - fees
    return ResearchTrade(
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
        mfe_percent=round(mfe_percent, 8),
        mae_percent=round(mae_percent, 8),
        realized_r=round(net_pnl / risk_usdt, 8) if risk_usdt > 0 else 0.0,
        exit_reason=exit_reason,
        reason_codes=[*position.signal.reason_codes, f"exit_policy:{exit_reason}"],
    )


def hold_minutes(position: OpenPosition, exit_bar: BacktestBar) -> int:
    entry_open_time = int(datetime.fromisoformat(position.entry_time.replace("Z", "+00:00")).timestamp() * 1000)
    return max(1, int((exit_bar.close_time - entry_open_time) / ONE_MINUTE_MS) + 1)

def summarize_trades(trades: list[ResearchTrade], *, initial_capital: float) -> dict[str, Any]:
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


def profile_selection_score(summary: dict[str, Any], *, min_train_trades: int) -> float:
    trade_count = int(summary.get("trade_count") or 0)
    if trade_count <= 0:
        return -1_000_000.0
    pf = summary.get("profit_factor")
    pf_value = 4.0 if pf == "inf" else float(pf or 0.0)
    sample_penalty = 0.0 if trade_count >= min_train_trades else (min_train_trades - trade_count) / max(min_train_trades, 1)
    score = (
        float(summary.get("return_percent") or 0.0)
        + pf_value * 3.0
        + float(summary.get("win_rate") or 0.0) * 2.0
        - float(summary.get("max_drawdown_percent_of_initial") or 0.0) * 1.5
    )
    if trade_count < min_train_trades:
        score -= 1_000.0 + sample_penalty * 100.0
    return score


def scan_signal_diagnostics(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    profile: RangeProfile,
    stride: int,
) -> dict[str, Any]:
    evaluated = 0
    signal_count = 0
    rejection_counts: dict[str, int] = {}
    symbol_signal_counts: dict[str, int] = {}
    symbol_evaluated_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    for symbol, bars in bars_by_symbol.items():
        for signal_index in range(profile.lookback_minutes, len(bars), max(1, stride)):
            evaluated += 1
            symbol_evaluated_counts[symbol] = symbol_evaluated_counts.get(symbol, 0) + 1
            features = range_features(bars[signal_index - profile.lookback_minutes : signal_index])
            if features is None:
                rejection_counts["feature_unavailable"] = rejection_counts.get("feature_unavailable", 0) + 1
                continue
            reasons = profile_rejection_reasons(features, profile)
            if reasons:
                for reason in reasons:
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                continue
            side = "long" if features.close_position_percent <= profile.low_zone_percent else "short"
            signal_count += 1
            side_counts[side] = side_counts.get(side, 0) + 1
            symbol_signal_counts[symbol] = symbol_signal_counts.get(symbol, 0) + 1
    return {
        "symbols": len(bars_by_symbol),
        "stride": max(1, stride),
        "evaluated_windows": evaluated,
        "signal_count": signal_count,
        "signal_rate": round(signal_count / evaluated, 8) if evaluated else 0.0,
        "side_counts": dict(sorted(side_counts.items())),
        "symbol_signal_counts": dict(sorted(symbol_signal_counts.items())),
        "symbol_evaluated_counts": dict(sorted(symbol_evaluated_counts.items())),
        "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)),
    }


def coverage_summary(bars_by_symbol: dict[str, list[BacktestBar]]) -> dict[str, Any]:
    return {
        symbol: {
            "bars": len(bars),
            "start": bars[0].open_time_iso if bars else None,
            "end": bars[-1].close_time_iso if bars else None,
        }
        for symbol, bars in sorted(bars_by_symbol.items())
    }


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def range_edge_alternations(
    bars: list[BacktestBar],
    *,
    lower_zone: float,
    upper_zone: float,
) -> int:
    sequence: list[str] = []
    for bar in bars:
        lower = bar.low <= lower_zone
        upper = bar.high >= upper_zone
        if lower and upper:
            ordered = ("lower", "upper") if bar.close >= bar.open else ("upper", "lower")
            for item in ordered:
                if not sequence or sequence[-1] != item:
                    sequence.append(item)
            continue
        if lower and (not sequence or sequence[-1] != "lower"):
            sequence.append("lower")
        if upper and (not sequence or sequence[-1] != "upper"):
            sequence.append("upper")
    return sum(1 for previous, current in zip(sequence, sequence[1:]) if previous != current)


def range_mid_cross_count(bars: list[BacktestBar], *, midpoint: float) -> int:
    states: list[int] = []
    for bar in bars:
        state = 1 if bar.close > midpoint else -1 if bar.close < midpoint else 0
        if state == 0:
            continue
        if not states or states[-1] != state:
            states.append(state)
    return sum(1 for previous, current in zip(states, states[1:]) if previous != current)


def coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return (variance ** 0.5) / mean


def recent_trend_percent(window: list[BacktestBar], *, recent_bars: int = 4) -> float:
    recent = window[-max(2, recent_bars) :]
    return percent_delta(recent[0].open, recent[-1].close) if len(recent) >= 2 else 0.0


def recent_path_efficiency(window: list[BacktestBar], *, recent_bars: int = 4) -> float:
    recent = window[-max(2, recent_bars) :]
    if len(recent) < 2:
        return 0.0
    travel = sum(abs(current.close - previous.close) for previous, current in zip(recent, recent[1:]))
    displacement = abs(recent[-1].close - recent[0].open)
    return displacement / travel if travel > 0 else 0.0


def recent_volume_expansion(window: list[BacktestBar], *, recent_bars: int = 4) -> float | None:
    if len(window) < recent_bars + 2:
        return None
    recent = [bar.quote_volume for bar in window[-recent_bars:] if bar.quote_volume > 0]
    baseline = [bar.quote_volume for bar in window[:-recent_bars] if bar.quote_volume > 0]
    if not recent or not baseline:
        return None
    baseline_mean = sum(baseline) / len(baseline)
    if baseline_mean <= 0:
        return None
    return (sum(recent) / len(recent)) / baseline_mean


def percent_delta(start: float, end: float) -> float:
    return ((end - start) / start) * 100.0 if start > 0 else 0.0


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
