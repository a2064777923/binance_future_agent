"""Rank historical micro-grid opportunities before expensive tick replay.

The exact micro-grid replay consumes daily aggTrades archives. Downloading and
replaying those archives for every USD-M contract is unnecessarily expensive,
and selecting a fixed symbol list does not test whether the live system could
have discovered the opportunity at the time. This script supplies that missing
discovery layer:

1. scan the whole historical crypto-perpetual universe with completed 5m bars;
2. recompute the leading candidates with completed 1m bars;
3. emit a symbol/time eligibility schedule for exact aggTrade replay.

No trade outcome, future signal-window bar, current 24h ticker rank, API key, or
signed account endpoint is used.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import io
import json
import math
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bfa.backtest.models import BacktestBar  # noqa: E402


EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
KLINE_ARCHIVE_URL = "https://data.binance.vision/data/futures/um/daily/klines"
MINUTE_MS = 60_000
COMPONENT_WEIGHTS = {
    "liquidity": 0.15,
    "cost_adjusted_range": 0.18,
    "oscillation": 0.20,
    "wick_quality": 0.20,
    "mean_reversion": 0.17,
    "recent_activity": 0.05,
    "flow_balance": 0.05,
}


@dataclass(frozen=True)
class MarketScanConfig:
    lookback_minutes: int = 360
    recent_minutes: int = 60
    selection_interval_minutes: int = 60
    signal_window_minutes: int = 60
    prefilter_interval: str = "5m"
    prefilter_top_n: int = 80
    final_interval: str = "1m"
    watch_top_n: int = 24
    min_coverage_fraction: float = 0.90
    min_lookback_quote_volume_usdt: float = 1_000_000.0
    round_trip_cost_percent: float = 0.075


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    onboard_time_ms: int


@dataclass(frozen=True)
class ScanWindow:
    signal_start_ms: int
    signal_end_ms: int
    feature_start_ms: int
    feature_end_ms: int


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="comma-separated UTC dates, YYYY-MM-DD")
    parser.add_argument("--symbols", help="optional explicit comma-separated universe")
    parser.add_argument("--exchange-info-json", help="optional cached public exchangeInfo payload")
    parser.add_argument("--cache-dir", default="runtime/market-scan-klines")
    parser.add_argument("--output", required=True)
    parser.add_argument("--lookback-minutes", type=int, default=MarketScanConfig.lookback_minutes)
    parser.add_argument("--recent-minutes", type=int, default=MarketScanConfig.recent_minutes)
    parser.add_argument("--selection-interval-minutes", type=int, default=MarketScanConfig.selection_interval_minutes)
    parser.add_argument("--signal-window-minutes", type=int, default=MarketScanConfig.signal_window_minutes)
    parser.add_argument("--prefilter-top-n", type=int, default=MarketScanConfig.prefilter_top_n)
    parser.add_argument("--watch-top-n", type=int, default=None)
    parser.add_argument("--final-top-n", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--min-coverage-fraction", type=float, default=MarketScanConfig.min_coverage_fraction)
    parser.add_argument(
        "--min-lookback-quote-volume-usdt",
        type=float,
        default=MarketScanConfig.min_lookback_quote_volume_usdt,
    )
    parser.add_argument("--round-trip-cost-percent", type=float, default=MarketScanConfig.round_trip_cost_percent)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    dates = parse_dates(args.dates)
    watch_top_n = (
        args.watch_top_n
        if args.watch_top_n is not None
        else args.final_top_n
        if args.final_top_n is not None
        else MarketScanConfig.watch_top_n
    )
    config = MarketScanConfig(
        lookback_minutes=max(60, int(args.lookback_minutes)),
        recent_minutes=max(5, int(args.recent_minutes)),
        selection_interval_minutes=max(5, int(args.selection_interval_minutes)),
        signal_window_minutes=max(5, int(args.signal_window_minutes)),
        prefilter_top_n=max(1, int(args.prefilter_top_n)),
        watch_top_n=max(1, int(watch_top_n)),
        min_coverage_fraction=clamp(float(args.min_coverage_fraction), 0.0, 1.0),
        min_lookback_quote_volume_usdt=max(0.0, float(args.min_lookback_quote_volume_usdt)),
        round_trip_cost_percent=max(0.0001, float(args.round_trip_cost_percent)),
    )
    if config.watch_top_n > config.prefilter_top_n:
        raise SystemExit("--watch-top-n cannot exceed --prefilter-top-n")

    exchange_observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    explicit_symbols = parse_symbols(args.symbols)
    exchange_payload = load_exchange_info(args.exchange_info_json)
    universe, universe_diagnostics = resolve_universe(exchange_payload, explicit_symbols=explicit_symbols)
    if not universe:
        raise SystemExit("historical universe is empty")
    windows = build_scan_windows(dates, config)
    cache_dir = Path(args.cache_dir)
    workers = max(1, int(args.workers))

    started = time.perf_counter()
    prefilter_raw, prefilter_io = collect_features(
        universe,
        windows,
        interval=config.prefilter_interval,
        config=config,
        cache_dir=cache_dir,
        workers=workers,
    )
    prefilter_ranked = rank_feature_windows(prefilter_raw, top_n=config.prefilter_top_n)
    prefilter_seconds = time.perf_counter() - started

    shortlist_by_symbol = invert_ranked_windows(prefilter_ranked)
    final_started = time.perf_counter()
    final_raw, final_io = collect_features(
        universe,
        windows,
        interval=config.final_interval,
        config=config,
        cache_dir=cache_dir,
        workers=workers,
        allowed_windows_by_symbol=shortlist_by_symbol,
    )
    final_ranked = rank_feature_windows(final_raw, top_n=config.watch_top_n)
    final_seconds = time.perf_counter() - final_started

    output_windows = build_output_windows(windows, prefilter_ranked, final_ranked)
    schedule = {
        "schema": "bfa_micro_grid_eligibility_schedule_v2",
        "selection_basis": "prior_only_market_opportunity_rank",
        "watch_top_n": config.watch_top_n,
        "pending_capacity_semantics": "independent_downstream_limit",
        "windows": [
            {
                "signal_start": row["signal_start"],
                "signal_end": row["signal_end"],
                "symbols": [candidate["symbol"] for candidate in row["selected"]],
            }
            for row in output_windows
        ],
    }
    selected_symbol_days = group_selected_symbol_days(output_windows)
    payload = {
        "schema": "bfa_micro_grid_market_scan_v1",
        "method": {
            "purpose": "historical market-wide opportunity discovery before exact micro-grid aggTrade replay",
            "universe": "current public exchangeInfo crypto USDT perpetuals, onboard-time bounded; no current 24h ticker ranking",
            "prefilter": "cross-sectional prior-only 5m feature rank; retain a broad shortlist",
            "final_rank": "recompute the same feature family from completed 1m bars and retain a broad watch universe; pending capacity is applied later",
            "features": list(COMPONENT_WEIGHTS),
            "outcome_use": "none",
            "lookahead_rule": "feature_end is strictly earlier than signal_start for every window",
        },
        "dates": [item.isoformat() for item in dates],
        "config": {**asdict(config), "component_weights": COMPONENT_WEIGHTS},
        "universe": {
            **universe_diagnostics,
            "exchange_info_observed_at": exchange_observed_at,
            "symbols": [item.symbol for item in universe],
            "survivorship_note": (
                "current exchangeInfo can omit contracts delisted before the scan was run; "
                "onboardDate prevents future listings from entering earlier windows"
            ),
        },
        "performance": {
            "worker_count": workers,
            "prefilter_seconds": round(prefilter_seconds, 6),
            "final_seconds": round(final_seconds, 6),
            "total_seconds": round(time.perf_counter() - started, 6),
            "prefilter_io": prefilter_io,
            "final_io": final_io,
        },
        "windows": output_windows,
        "eligibility_schedule": schedule,
        "selected_symbols": sorted({symbol for symbols in selected_symbol_days.values() for symbol in symbols}),
        "selected_symbol_days": selected_symbol_days,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "output": str(output),
        "dates": payload["dates"],
        "universe_count": len(universe),
        "window_count": len(output_windows),
        "selected_symbol_count": len(payload["selected_symbols"]),
        "selected_symbol_day_counts": {key: len(value) for key, value in selected_symbol_days.items()},
        "performance": payload["performance"],
    }
    print(json.dumps(summary if args.quiet else payload, indent=2, sort_keys=True))
    return 0


def parse_dates(value: str) -> list[date]:
    parsed = sorted({date.fromisoformat(item.strip()) for item in value.split(",") if item.strip()})
    if not parsed:
        raise SystemExit("--dates must include at least one date")
    return parsed


def parse_symbols(value: str | None) -> list[str]:
    return sorted({item.strip().upper() for item in str(value or "").split(",") if item.strip()})


def load_exchange_info(path: str | None) -> dict[str, Any]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        request = Request(EXCHANGE_INFO_URL, headers={"User-Agent": "bfa-market-scan"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public Binance endpoint.
            payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("exchangeInfo payload must contain a symbols list")
    return payload


def resolve_universe(
    exchange_payload: dict[str, Any],
    *,
    explicit_symbols: list[str] | None = None,
) -> tuple[list[SymbolMeta], dict[str, Any]]:
    explicit = set(explicit_symbols or [])
    selected: list[SymbolMeta] = []
    exclusion_counts: dict[str, int] = {}
    seen: set[str] = set()
    for row in exchange_payload.get("symbols", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        if explicit and symbol not in explicit:
            continue
        reason = crypto_perpetual_exclusion_reason(row)
        if reason:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        try:
            onboard = int(row.get("onboardDate") or 0)
        except (TypeError, ValueError):
            onboard = 0
        selected.append(SymbolMeta(symbol=symbol, onboard_time_ms=max(0, onboard)))
    if explicit:
        missing = sorted(explicit - {item.symbol for item in selected})
    else:
        missing = []
    selected.sort(key=lambda item: item.symbol)
    return selected, {
        "source": "explicit_symbols_plus_exchange_info" if explicit else "exchange_info_all_crypto_usdt_perpetuals",
        "eligible_symbol_count": len(selected),
        "explicit_missing_or_ineligible_symbols": missing,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
    }


def crypto_perpetual_exclusion_reason(row: dict[str, Any]) -> str | None:
    if str(row.get("status") or "").upper() != "TRADING":
        return "status_not_trading"
    if str(row.get("contractType") or "").upper() != "PERPETUAL":
        return "not_perpetual"
    if str(row.get("quoteAsset") or "").upper() != "USDT":
        return "quote_not_usdt"
    if str(row.get("marginAsset") or "").upper() != "USDT":
        return "margin_not_usdt"
    underlying_type = str(row.get("underlyingType") or "").upper()
    subtypes = {str(item).upper() for item in row.get("underlyingSubType") or []}
    if underlying_type and underlying_type != "COIN":
        return "underlying_not_coin"
    if "TRADFI" in subtypes:
        return "tradfi"
    return None


def build_scan_windows(dates: list[date], config: MarketScanConfig) -> list[ScanWindow]:
    windows: list[ScanWindow] = []
    step_ms = config.selection_interval_minutes * MINUTE_MS
    signal_span_ms = config.signal_window_minutes * MINUTE_MS
    lookback_ms = config.lookback_minutes * MINUTE_MS
    for day in dates:
        day_start = day_start_ms(day)
        day_end_exclusive = day_start_ms(day + timedelta(days=1))
        signal_start = day_start
        while signal_start < day_end_exclusive:
            signal_end = min(signal_start + signal_span_ms, day_end_exclusive) - 1
            windows.append(
                ScanWindow(
                    signal_start_ms=signal_start,
                    signal_end_ms=signal_end,
                    feature_start_ms=signal_start - lookback_ms,
                    feature_end_ms=signal_start - 1,
                )
            )
            signal_start += step_ms
    return windows


def collect_features(
    universe: list[SymbolMeta],
    windows: list[ScanWindow],
    *,
    interval: str,
    config: MarketScanConfig,
    cache_dir: Path,
    workers: int,
    allowed_windows_by_symbol: dict[str, set[int]] | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    by_window: dict[int, list[dict[str, Any]]] = {window.signal_start_ms: [] for window in windows}
    missing_archives = 0
    loaded_archives = 0
    loaded_bytes = 0
    error_samples: list[str] = []

    def submit_windows(meta: SymbolMeta) -> list[ScanWindow]:
        allowed = None if allowed_windows_by_symbol is None else allowed_windows_by_symbol.get(meta.symbol, set())
        if allowed_windows_by_symbol is not None and not allowed:
            return []
        return [window for window in windows if allowed is None or window.signal_start_ms in allowed]

    jobs = [(meta, submit_windows(meta)) for meta in universe]
    jobs = [(meta, selected_windows) for meta, selected_windows in jobs if selected_windows]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                scan_symbol_windows,
                meta,
                selected_windows,
                interval=interval,
                config=config,
                cache_dir=cache_dir,
            ): meta.symbol
            for meta, selected_windows in jobs
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve bounded research diagnostics.
                if len(error_samples) < 20:
                    error_samples.append(f"{symbol}:{type(exc).__name__}:{exc}")
                continue
            loaded_archives += int(result["io"]["loaded_archives"])
            missing_archives += int(result["io"]["missing_archives"])
            loaded_bytes += int(result["io"]["loaded_bytes"])
            for signal_start_ms, features in result["features"].items():
                by_window.setdefault(signal_start_ms, []).append(features)
            for error in result["io"]["error_samples"]:
                if len(error_samples) < 20:
                    error_samples.append(error)
    return by_window, {
        "interval": interval,
        "symbol_jobs": len(jobs),
        "loaded_archives": loaded_archives,
        "missing_archives": missing_archives,
        "loaded_bytes": loaded_bytes,
        "error_samples": error_samples,
    }


def scan_symbol_windows(
    meta: SymbolMeta,
    windows: list[ScanWindow],
    *,
    interval: str,
    config: MarketScanConfig,
    cache_dir: Path,
) -> dict[str, Any]:
    interval_minutes = interval_to_minutes(interval)
    windows = [
        window
        for window in windows
        if not meta.onboard_time_ms or meta.onboard_time_ms <= window.feature_start_ms
    ]
    if not windows:
        return {
            "features": {},
            "io": {
                "loaded_archives": 0,
                "missing_archives": 0,
                "loaded_bytes": 0,
                "error_samples": [],
            },
        }
    required_days = sorted(
        {
            current
            for window in windows
            for current in dates_between(ms_to_date(window.feature_start_ms), ms_to_date(window.feature_end_ms))
        }
    )
    bars: list[BacktestBar] = []
    missing = 0
    loaded = 0
    loaded_bytes = 0
    errors: list[str] = []
    for day in required_days:
        try:
            path = fetch_daily_kline_zip(meta.symbol, interval, day, cache_dir)
            rows = read_daily_kline_zip(path)
        except Exception as exc:  # noqa: BLE001 - archive availability is expected to vary by listing date.
            missing += 1
            if len(errors) < 3 and not (isinstance(exc, HTTPError) and exc.code == 404):
                errors.append(f"{meta.symbol}:{interval}:{day.isoformat()}:{type(exc).__name__}:{exc}")
            continue
        loaded += 1
        loaded_bytes += path.stat().st_size
        bars.extend(BacktestBar.from_binance_kline(meta.symbol, row) for row in rows)
    bars.sort(key=lambda item: item.open_time)
    times = [bar.open_time for bar in bars]
    features: dict[int, dict[str, Any]] = {}
    for window in windows:
        snapshot = opportunity_features(
            meta.symbol,
            bars,
            times,
            window,
            interval_minutes=interval_minutes,
            config=config,
        )
        if snapshot is not None:
            features[window.signal_start_ms] = snapshot
    return {
        "features": features,
        "io": {
            "loaded_archives": loaded,
            "missing_archives": missing,
            "loaded_bytes": loaded_bytes,
            "error_samples": errors,
        },
    }


def opportunity_features(
    symbol: str,
    bars: list[BacktestBar],
    times: list[int],
    window: ScanWindow,
    *,
    interval_minutes: int,
    config: MarketScanConfig,
) -> dict[str, Any] | None:
    start = bisect_left(times, window.feature_start_ms)
    end = bisect_left(times, window.signal_start_ms, lo=start)
    sample = bars[start:end]
    expected = max(1, math.ceil(config.lookback_minutes / interval_minutes))
    coverage = len(sample) / expected
    if coverage < config.min_coverage_fraction or len(sample) < 3:
        return None
    quote_volume = sum(max(0.0, bar.quote_volume) for bar in sample)
    if quote_volume < config.min_lookback_quote_volume_usdt:
        return None
    closes = [bar.close for bar in sample if bar.close > 0]
    if len(closes) != len(sample) or not closes:
        return None

    recent_count = max(2, math.ceil(config.recent_minutes / interval_minutes))
    recent = sample[-recent_count:]
    close_changes = [percent_delta(closes[index - 1], closes[index]) for index in range(1, len(closes))]
    center = statistics.median(closes)
    center_signs = [sign(close - center, center * config.round_trip_cost_percent / 400.0) for close in closes]
    turn_rate = sign_alternation_rate(close_changes, minimum_abs=config.round_trip_cost_percent / 4.0)
    center_cross_rate = sign_change_rate(center_signs)

    range_percents = [bar_range_percent(bar) for bar in sample]
    recent_range_percents = [bar_range_percent(bar) for bar in recent]
    range_p75 = percentile(range_percents, 75.0)
    cost_adjusted_range = range_p75 / config.round_trip_cost_percent
    path_efficiency = path_efficiency_percent(closes)
    total_range_percent = percent_delta(min(bar.low for bar in sample), max(bar.high for bar in sample))
    drift_percent = abs(percent_delta(closes[0], closes[-1]))
    drift_to_range = drift_percent / total_range_percent if total_range_percent > 0 else 1.0

    wick_ratios: list[float] = []
    wick_cost_ratios: list[float] = []
    wick_hits = 0
    for bar in sample:
        reference = max(abs(bar.close), 1e-12)
        body = abs(bar.close - bar.open)
        upper = max(0.0, bar.high - max(bar.open, bar.close))
        lower = max(0.0, min(bar.open, bar.close) - bar.low)
        wick = upper + lower
        range_value = max(bar.high - bar.low, reference * 1e-9)
        wick_ratios.append(min(wick / max(body, range_value * 0.05), 20.0))
        wick_percent = wick / reference * 100.0
        wick_cost_ratios.append(wick_percent / config.round_trip_cost_percent)
        if wick_percent >= config.round_trip_cost_percent * 0.50:
            wick_hits += 1
    wick_frequency = wick_hits / len(sample)
    median_wick_body_ratio = percentile(wick_ratios, 50.0)
    median_wick_cost_ratio = percentile(wick_cost_ratios, 50.0)

    recent_quote_volume = sum(max(0.0, bar.quote_volume) for bar in recent)
    expected_recent_quote = quote_volume / len(sample) * len(recent)
    recent_volume_ratio = recent_quote_volume / expected_recent_quote if expected_recent_quote > 0 else 0.0
    recent_range_ratio = (
        percentile(recent_range_percents, 75.0) / range_p75 if range_p75 > 0 and recent_range_percents else 0.0
    )
    taker_quote = sum(max(0.0, bar.taker_buy_quote_volume) for bar in sample)
    taker_buy_fraction = clamp(taker_quote / quote_volume if quote_volume > 0 else 0.5, 0.0, 1.0)
    flow_signs = [
        sign(
            (bar.taker_buy_quote_volume / bar.quote_volume if bar.quote_volume > 0 else 0.5) - 0.5,
            0.02,
        )
        for bar in sample
    ]
    flow_alternation = sign_change_rate(flow_signs)
    flow_balance = 1.0 - min(1.0, abs(taker_buy_fraction - 0.5) * 2.0)

    raw_components = {
        "liquidity": math.log1p(quote_volume),
        "cost_adjusted_range": math.log1p(max(0.0, cost_adjusted_range)),
        "oscillation": turn_rate * 0.60 + center_cross_rate * 0.40,
        "wick_quality": wick_frequency
        * math.log1p(max(0.0, median_wick_cost_ratio))
        * (
            0.50
            + 0.50
            * clamp(math.log1p(max(0.0, median_wick_body_ratio)) / math.log(21.0), 0.0, 1.0)
        ),
        "mean_reversion": (1.0 - clamp(path_efficiency, 0.0, 1.0))
        * (1.0 - clamp(drift_to_range, 0.0, 1.0)),
        "recent_activity": math.sqrt(
            clamp(recent_volume_ratio, 0.0, 4.0) * clamp(recent_range_ratio, 0.0, 4.0)
        ),
        "flow_balance": flow_balance * 0.55 + flow_alternation * 0.45,
    }
    return {
        "symbol": symbol,
        "feature_start": ms_to_iso(window.feature_start_ms),
        "feature_end": ms_to_iso(window.feature_end_ms),
        "signal_start": ms_to_iso(window.signal_start_ms),
        "coverage_fraction": round(coverage, 8),
        "quote_volume_usdt": round(quote_volume, 4),
        "range_p75_percent": round(range_p75, 8),
        "cost_adjusted_range_ratio": round(cost_adjusted_range, 8),
        "turn_rate": round(turn_rate, 8),
        "center_cross_rate": round(center_cross_rate, 8),
        "wick_frequency": round(wick_frequency, 8),
        "median_wick_body_ratio": round(median_wick_body_ratio, 8),
        "median_wick_cost_ratio": round(median_wick_cost_ratio, 8),
        "path_efficiency": round(path_efficiency, 8),
        "drift_percent": round(drift_percent, 8),
        "drift_to_range": round(drift_to_range, 8),
        "recent_volume_ratio": round(recent_volume_ratio, 8),
        "recent_range_ratio": round(recent_range_ratio, 8),
        "taker_buy_fraction": round(taker_buy_fraction, 8),
        "flow_alternation_rate": round(flow_alternation, 8),
        "raw_components": raw_components,
    }


def rank_feature_windows(
    raw_by_window: dict[int, list[dict[str, Any]]],
    *,
    top_n: int,
) -> dict[int, dict[str, Any]]:
    ranked: dict[int, dict[str, Any]] = {}
    for signal_start_ms, candidates in raw_by_window.items():
        component_ranks: dict[str, dict[str, float]] = {}
        for component in COMPONENT_WEIGHTS:
            values = {
                str(candidate["symbol"]): float(candidate["raw_components"][component])
                for candidate in candidates
            }
            component_ranks[component] = percentile_ranks(values)
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = str(candidate["symbol"])
            ranks = {component: component_ranks[component][symbol] for component in COMPONENT_WEIGHTS}
            score = sum(ranks[component] * weight for component, weight in COMPONENT_WEIGHTS.items())
            scored.append(
                {
                    **{key: value for key, value in candidate.items() if key != "raw_components"},
                    "component_percentile_ranks": {key: round(value, 8) for key, value in ranks.items()},
                    "opportunity_score": round(score, 8),
                }
            )
        scored.sort(key=lambda item: (-float(item["opportunity_score"]), str(item["symbol"])))
        ranked[signal_start_ms] = {
            "eligible_count": len(scored),
            "selected": scored[:top_n],
        }
    return ranked


def invert_ranked_windows(ranked: dict[int, dict[str, Any]]) -> dict[str, set[int]]:
    by_symbol: dict[str, set[int]] = {}
    for signal_start_ms, row in ranked.items():
        for candidate in row.get("selected", []):
            by_symbol.setdefault(str(candidate["symbol"]), set()).add(signal_start_ms)
    return by_symbol


def build_output_windows(
    windows: list[ScanWindow],
    prefilter: dict[int, dict[str, Any]],
    final: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for window in windows:
        prefilter_row = prefilter.get(window.signal_start_ms, {"eligible_count": 0, "selected": []})
        final_row = final.get(window.signal_start_ms, {"eligible_count": 0, "selected": []})
        if window.feature_end_ms >= window.signal_start_ms:
            raise AssertionError("feature window overlaps signal window")
        output.append(
            {
                "feature_start": ms_to_iso(window.feature_start_ms),
                "feature_end": ms_to_iso(window.feature_end_ms),
                "signal_start": ms_to_iso(window.signal_start_ms),
                "signal_end": ms_to_iso(window.signal_end_ms),
                "prefilter_eligible_count": int(prefilter_row["eligible_count"]),
                "prefilter_symbols": [str(item["symbol"]) for item in prefilter_row["selected"]],
                "final_eligible_count": int(final_row["eligible_count"]),
                "selected": list(final_row["selected"]),
            }
        )
    return output


def group_selected_symbol_days(windows: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = {}
    for window in windows:
        day = str(window["signal_start"])[:10]
        grouped.setdefault(day, set()).update(str(item["symbol"]) for item in window.get("selected", []))
    return {day: sorted(symbols) for day, symbols in sorted(grouped.items())}


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    if len(values) == 1:
        symbol = next(iter(values))
        return {symbol: 1.0}
    ordered = sorted(values.values())
    denominator = len(ordered) - 1
    rank_by_value: dict[float, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end] == ordered[index]:
            end += 1
        average_rank = (index + end - 1) / 2.0
        rank_by_value[ordered[index]] = average_rank / denominator
        index = end
    return {symbol: rank_by_value[value] for symbol, value in values.items()}


def fetch_daily_kline_zip(symbol: str, interval: str, day: date, cache_dir: Path) -> Path:
    symbol = symbol.upper()
    directory = cache_dir / symbol / interval
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{symbol}-{interval}-{day.isoformat()}.zip"
    path = directory / name
    if path.exists() and path.stat().st_size > 0 and zip_is_valid(path):
        return path
    if path.exists():
        path.unlink(missing_ok=True)
    url = kline_archive_url(symbol, interval, name)
    request = Request(url, headers={"User-Agent": "bfa-market-scan"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public Binance archive URL.
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise zipfile.BadZipFile(f"corrupt archive: {name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def kline_archive_url(symbol: str, interval: str, name: str) -> str:
    return (
        f"{KLINE_ARCHIVE_URL}/{quote(symbol, safe='')}/"
        f"{quote(interval, safe='')}/{quote(name, safe='')}"
    )


def read_daily_kline_zip(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with archive.open(names[0]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            return [row for row in reader if len(row) >= 11 and row[0].strip().isdigit()]


def zip_is_valid(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except (EOFError, OSError, zipfile.BadZipFile, zlib.error):
        return False


def interval_to_minutes(interval: str) -> int:
    if not interval.endswith("m") or not interval[:-1].isdigit():
        raise ValueError(f"unsupported minute interval: {interval}")
    return max(1, int(interval[:-1]))


def dates_between(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def day_start_ms(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)


def ms_to_date(value: int) -> date:
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).date()


def ms_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).isoformat()


def bar_range_percent(bar: BacktestBar) -> float:
    reference = max(abs(bar.close), 1e-12)
    return max(0.0, bar.high - bar.low) / reference * 100.0


def percent_delta(start: float, end: float) -> float:
    return (end / start - 1.0) * 100.0 if start else 0.0


def path_efficiency_percent(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    distance = abs(values[-1] - values[0])
    travel = sum(abs(values[index] - values[index - 1]) for index in range(1, len(values)))
    return clamp(distance / travel if travel > 0 else 1.0, 0.0, 1.0)


def sign(value: float, threshold: float = 0.0) -> int:
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def sign_alternation_rate(values: list[float], *, minimum_abs: float) -> float:
    return sign_change_rate([sign(value, minimum_abs) for value in values])


def sign_change_rate(values: list[int]) -> float:
    nonzero = [value for value in values if value]
    if len(nonzero) < 2:
        return 0.0
    changes = sum(1 for index in range(1, len(nonzero)) if nonzero[index] != nonzero[index - 1])
    return changes / (len(nonzero) - 1)


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = clamp(percent, 0.0, 100.0) / 100.0 * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


if __name__ == "__main__":
    raise SystemExit(main())
