"""Run a second-path compound backtest from Binance USD-M aggTrades archives.

This analysis script reconstructs continuous 1-second OHLCV bars from public
aggTrades zip files, derives 5-minute signal bars from those seconds, then
simulates exits on the 1-second path.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
import zlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from bfa.backtest.engine import _generate_signals, _trailing_stop_price
from bfa.backtest.models import BacktestBar, BacktestConfig, BacktestTrade, built_in_variants


ARCHIVE_URL = "https://data.binance.vision/data/futures/um/daily/aggTrades"
SECOND_MS = 1_000
FIVE_MINUTE_SECONDS = 300
FIVE_MINUTE_MS = FIVE_MINUTE_SECONDS * SECOND_MS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="comma-separated symbols")
    parser.add_argument("--start-date", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--variant", default="quant_setup_high_frequency_flow_guarded")
    parser.add_argument("--initial-capital", type=float, default=None)
    parser.add_argument("--max-leverage", type=float, default=None)
    parser.add_argument("--max-position-notional-usdt", type=float, default=None)
    parser.add_argument("--max-risk-per-trade-usdt", type=float, default=None)
    parser.add_argument("--max-daily-loss-usdt", type=float, default=None)
    parser.add_argument("--max-open-positions", type=int, default=None)
    parser.add_argument("--cache-dir", default="runtime/aggTrades-cache")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        raise SystemExit("--symbols must include at least one symbol")
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise SystemExit("--end-date must be on or after --start-date")
    variant_config = built_in_variants()[args.variant]
    if args.initial_capital is not None:
        scale = args.initial_capital / variant_config.account_capital_usdt
        variant_config = replace(
            variant_config,
            account_capital_usdt=args.initial_capital,
            max_position_notional_usdt=variant_config.max_position_notional_usdt * scale,
            max_risk_per_trade_usdt=variant_config.max_risk_per_trade_usdt * scale,
            max_daily_loss_usdt=variant_config.max_daily_loss_usdt * scale,
        )
    variant_overrides: dict[str, Any] = {}
    if args.max_leverage is not None:
        variant_overrides["max_leverage"] = args.max_leverage
    if args.max_position_notional_usdt is not None:
        variant_overrides["max_position_notional_usdt"] = args.max_position_notional_usdt
    if args.max_risk_per_trade_usdt is not None:
        variant_overrides["max_risk_per_trade_usdt"] = args.max_risk_per_trade_usdt
    if args.max_daily_loss_usdt is not None:
        variant_overrides["max_daily_loss_usdt"] = args.max_daily_loss_usdt
    if args.max_open_positions is not None:
        variant_overrides["max_open_positions"] = args.max_open_positions
    if variant_overrides:
        variant_config = replace(variant_config, **variant_overrides)

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_candidates: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    total_rejected = 0
    simulation_status_counts: dict[str, int] = {}
    for symbol in symbols:
        seconds, symbol_coverage = load_symbol_seconds(symbol, start, end, cache_dir)
        coverage[symbol] = symbol_coverage
        signal_bars = aggregate_to_5m(seconds)
        signal_config = variant_config
        signals, rejected = _generate_signals(symbol, signal_bars, signal_config)
        total_rejected += rejected
        for signal in signals:
            trade, status = simulate_signal_on_seconds(
                symbol=symbol,
                signal_entry_time_ms=signal.entry_time_ms,
                setup=signal.setup,
                seconds=seconds,
                config=signal_config,
                reason_codes=signal.reason_codes,
            )
            simulation_status_counts[status] = simulation_status_counts.get(status, 0) + 1
            if trade is not None:
                all_candidates.append(
                    {
                        "symbol": symbol,
                        "signal_entry_time_ms": signal.entry_time_ms,
                        "trade": trade,
                    }
                )

    compound = compound_replay(
        [item["trade"] for item in all_candidates],
        config=variant_config,
    )
    payload = {
        "schema": "bfa_second_agg_compound_backtest_v1",
        "method": {
            "data_source": "Binance USD-M public daily aggTrades archives",
            "path_resolution": "1s bars reconstructed from aggTrades, flat-filled during no-trade seconds",
            "signal_resolution": "5m bars aggregated from reconstructed 1s bars",
            "entry_model": "signal uses completed 5m bars; market setups enter at next 5m open; limit setups wait on the 1s path and skip when unfilled",
            "exit_model": "1s high/low path; stop checked before target on same-second collision; optional no-time-exit and early-invalid-exit policies come from setup.price_basis.exit_policy",
            "compound_model": "realized equity scales notional, quantity, fees, slippage, and PnL on each accepted entry",
        },
        "window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "inclusive_days": (end - start).days + 1,
            "expected_seconds_per_symbol": ((end - start).days + 1) * 86_400,
        },
        "symbols": symbols,
        "variant": args.variant,
        "config": variant_config.to_dict(),
        "coverage": coverage,
        "candidate_trade_count": len(all_candidates),
        "simulation_status_counts": simulation_status_counts,
        "rejected_signal_count": total_rejected,
        "compound_summary": compound["summary"],
        "trades": compound["trades"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def load_symbol_seconds(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Path,
) -> tuple[list[BacktestBar], dict[str, Any]]:
    by_second: dict[int, dict[str, float]] = {}
    missing_dates: list[str] = []
    zip_bytes = 0
    agg_trade_rows = 0
    current = start
    while current <= end:
        try:
            path = fetch_zip(symbol, current, cache_dir)
        except Exception as exc:  # noqa: BLE001 - report missing archive details to payload.
            missing_dates.append(f"{current.isoformat()}:{type(exc).__name__}:{exc}")
            current += timedelta(days=1)
            continue
        zip_bytes += path.stat().st_size
        rows = read_aggtrade_zip(path)
        for row in rows:
            agg_trade_rows += 1
            second_ms = int(row["time_ms"] // SECOND_MS * SECOND_MS)
            price = row["price"]
            qty = row["quantity"]
            quote = price * qty
            item = by_second.get(second_ms)
            if item is None:
                by_second[second_ms] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": qty,
                    "quote_volume": quote,
                    "taker_buy_quote_volume": 0.0 if row["buyer_maker"] else quote,
                    "trade_count": 1.0,
                }
            else:
                item["high"] = max(item["high"], price)
                item["low"] = min(item["low"], price)
                item["close"] = price
                item["volume"] += qty
                item["quote_volume"] += quote
                if not row["buyer_maker"]:
                    item["taker_buy_quote_volume"] += quote
                item["trade_count"] += 1.0
        current += timedelta(days=1)

    start_ms = day_start_ms(start)
    end_exclusive_ms = day_start_ms(end + timedelta(days=1))
    expected_seconds = int((end_exclusive_ms - start_ms) / SECOND_MS)
    first_trade_second = min(by_second) if by_second else None
    last_trade_second = max(by_second) if by_second else None
    fallback_price = by_second[first_trade_second]["open"] if first_trade_second is not None else 0.0
    last_close = fallback_price
    leading_fill_seconds = 0
    empty_fill_seconds = 0
    seconds: list[BacktestBar] = []
    for index in range(expected_seconds):
        open_time = start_ms + index * SECOND_MS
        item = by_second.get(open_time)
        if item is None:
            empty_fill_seconds += 1
            if first_trade_second is not None and open_time < first_trade_second:
                leading_fill_seconds += 1
            item = {
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
                "quote_volume": 0.0,
                "taker_buy_quote_volume": 0.0,
            }
        else:
            last_close = item["close"]
        seconds.append(
            BacktestBar(
                symbol=symbol,
                open_time=open_time,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
                close_time=open_time + SECOND_MS - 1,
                quote_volume=float(item["quote_volume"]),
                taker_buy_quote_volume=float(item["taker_buy_quote_volume"]),
            )
        )

    coverage = {
        "expected_seconds": expected_seconds,
        "continuous_second_bars": len(seconds),
        "raw_trade_seconds": len(by_second),
        "raw_trade_second_coverage_percent": round((len(by_second) / expected_seconds) * 100.0, 8)
        if expected_seconds
        else 0.0,
        "empty_fill_seconds": empty_fill_seconds,
        "leading_fill_seconds": leading_fill_seconds,
        "agg_trade_rows": agg_trade_rows,
        "zip_bytes": zip_bytes,
        "missing_dates": missing_dates,
        "first_trade_time": ms_to_iso(first_trade_second) if first_trade_second is not None else None,
        "last_trade_time": ms_to_iso(last_trade_second) if last_trade_second is not None else None,
    }
    return seconds, coverage


def fetch_zip(symbol: str, day: date, cache_dir: Path) -> Path:
    symbol_dir = cache_dir / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    name = f"{symbol}-aggTrades-{day.isoformat()}.zip"
    path = symbol_dir / name
    if path.exists() and path.stat().st_size > 0:
        try:
            with zipfile.ZipFile(path) as zf:
                if zf.testzip() is None:
                    return path
        except (OSError, zipfile.BadZipFile, zlib.error):
            pass
        path.unlink(missing_ok=True)
    url = f"{ARCHIVE_URL}/{symbol}/{name}"
    with urlopen(url, timeout=60) as response:  # noqa: S310 - fixed public Binance archive URL.
        path.write_bytes(response.read())
    return path


def read_aggtrade_zip(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with zf.open(names[0]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            parsed: list[dict[str, Any]] = []
            for row in reader:
                if len(row) < 7 or not row[0].strip().lstrip("-").isdigit():
                    continue
                try:
                    price = float(row[1])
                    quantity = float(row[2])
                    time_ms = int(row[5])
                except ValueError:
                    continue
                parsed.append(
                    {
                        "price": price,
                        "quantity": quantity,
                        "time_ms": time_ms,
                        "buyer_maker": row[6].strip().lower() == "true",
                    }
                )
            return parsed


def aggregate_to_5m(seconds: list[BacktestBar]) -> list[BacktestBar]:
    bars: list[BacktestBar] = []
    for offset in range(0, len(seconds), FIVE_MINUTE_SECONDS):
        chunk = seconds[offset : offset + FIVE_MINUTE_SECONDS]
        if len(chunk) < FIVE_MINUTE_SECONDS:
            break
        bars.append(
            BacktestBar(
                symbol=chunk[0].symbol,
                open_time=chunk[0].open_time,
                open=chunk[0].open,
                high=max(item.high for item in chunk),
                low=min(item.low for item in chunk),
                close=chunk[-1].close,
                volume=sum(item.volume for item in chunk),
                close_time=chunk[-1].close_time,
                quote_volume=sum(item.quote_volume for item in chunk),
                taker_buy_quote_volume=sum(item.taker_buy_quote_volume or 0.0 for item in chunk),
            )
        )
    return bars


def simulate_signal_on_seconds(
    *,
    symbol: str,
    signal_entry_time_ms: int,
    setup,
    seconds: list[BacktestBar],
    config: BacktestConfig,
    reason_codes: list[str],
) -> tuple[BacktestTrade | None, str]:
    if setup is None or setup.entry_price is None or setup.stop_price is None or setup.target_price is None:
        return None, "invalid_setup"
    if setup.notional_usdt is None or setup.notional_usdt <= 0:
        return None, "invalid_notional"
    start_ms = seconds[0].open_time
    entry_index = int((signal_entry_time_ms - start_ms) / SECOND_MS)
    if entry_index < 0 or entry_index >= len(seconds):
        return None, "entry_out_of_range"
    side = setup.side
    stop_price = setup.stop_price
    target_price = setup.target_price
    notional = min(setup.notional_usdt, config.max_position_notional_usdt)
    if notional <= 0:
        return None, "invalid_notional"

    slippage_rate = config.slippage_bps / 10_000.0
    entry_basis = setup.price_basis.get("entry_basis", {}) if isinstance(setup.price_basis, dict) else {}
    order_type = str(entry_basis.get("order_type") or "market").lower()
    if order_type == "limit":
        fill_index = find_limit_fill_index(
            seconds=seconds,
            entry_index=entry_index,
            side=side,
            limit_price=setup.entry_price,
            max_wait_seconds=int(entry_basis.get("limit_entry_max_wait_seconds") or 0),
        )
        if fill_index is None:
            return None, "unfilled_limit_order"
        entry_index = fill_index
        entry_bar = seconds[entry_index]
        raw_entry = setup.entry_price
        entry_fill = setup.entry_price
        entry_slippage = 0.0
    else:
        entry_bar = seconds[entry_index]
        raw_entry = entry_bar.open
        entry_fill = raw_entry * (1.0 + slippage_rate) if side == "long" else raw_entry * (1.0 - slippage_rate)
        entry_slippage = abs(entry_fill - raw_entry)
    quantity = notional / entry_fill
    exit_policy = setup.price_basis.get("exit_policy", {}) if isinstance(setup.price_basis, dict) else {}
    hold_seconds = hold_seconds_from_setup(setup, config, remaining_seconds=len(seconds) - entry_index)
    time_exit_index = min(len(seconds) - 1, entry_index + hold_seconds - 1)
    conditional_time_exit = bool(exit_policy.get("time_exit_only_when_not_profitable"))
    exit_index = len(seconds) - 1 if conditional_time_exit else time_exit_index
    exit_bar = seconds[exit_index]
    exit_price = exit_bar.close
    exit_reason = "data_end" if conditional_time_exit else "time_exit" if exit_policy.get("time_exit_enabled", True) else "data_end"
    exit_time = exit_bar.close_time_iso
    actual_exit_index = exit_index
    dynamic_stop_price = stop_price
    best_price = entry_fill
    path_high = entry_fill
    path_low = entry_fill
    risk_per_unit = abs(entry_fill - stop_price)

    for index in range(entry_index, exit_index + 1):
        bar = seconds[index]
        path_high = max(path_high, bar.high)
        path_low = min(path_low, bar.low)
        if side == "long":
            hit_stop = bar.low <= dynamic_stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= dynamic_stop_price
            hit_target = bar.low <= target_price
        if hit_stop:
            exit_price = dynamic_stop_price
            exit_reason = "trailing_stop" if dynamic_stop_price != stop_price else "stop_loss"
            exit_time = bar.close_time_iso
            actual_exit_index = index
            break
        if hit_target:
            exit_price = target_price
            exit_reason = "take_profit"
            exit_time = bar.close_time_iso
            actual_exit_index = index
            break
        if conditional_time_exit and index == time_exit_index and not floating_profit(side, bar.close, entry_fill):
            exit_price = bar.close
            exit_reason = "time_exit"
            exit_time = bar.close_time_iso
            actual_exit_index = index
            break
        if config.trailing_stop_enabled and risk_per_unit > 0:
            if side == "long":
                best_price = max(best_price, bar.high)
                dynamic_stop_price = max(
                    dynamic_stop_price,
                    _trailing_stop_price(
                        side=side,
                        entry_price=entry_fill,
                        best_price=best_price,
                        risk_per_unit=risk_per_unit,
                        config=config,
                    ),
                )
            else:
                best_price = min(best_price, bar.low)
                dynamic_stop_price = min(
                    dynamic_stop_price,
                    _trailing_stop_price(
                        side=side,
                        entry_price=entry_fill,
                        best_price=best_price,
                        risk_per_unit=risk_per_unit,
                        config=config,
                    ),
                )
        if should_early_invalid_exit(
            setup=setup,
            side=side,
            entry_fill=entry_fill,
            risk_per_unit=risk_per_unit,
            best_price=best_price,
            bar=bar,
            window=seconds[entry_index : index + 1],
        ):
            exit_price = bar.close
            exit_reason = "early_invalid_exit"
            exit_time = bar.close_time_iso
            actual_exit_index = index
            break

    if side == "long":
        exit_fill = exit_price * (1.0 - slippage_rate)
        gross_pnl = quantity * (exit_fill - entry_fill)
        slippage = quantity * (entry_slippage + max(exit_price - exit_fill, 0.0))
    else:
        exit_fill = exit_price * (1.0 + slippage_rate)
        gross_pnl = quantity * (entry_fill - exit_fill)
        slippage = quantity * (entry_slippage + (exit_fill - exit_price))
    fees = quantity * entry_fill * config.taker_fee_rate + quantity * exit_fill * config.taker_fee_rate
    net_pnl = gross_pnl - fees
    mfe_percent, mae_percent = path_mfe_mae_percent(
        side=side,
        entry_fill=entry_fill,
        path_high=path_high,
        path_low=path_low,
    )
    trade_reason_codes = [*reason_codes, f"entry_order_type:{order_type}", f"exit_policy:{exit_reason}"]
    if exit_reason == "stop_loss":
        trade_reason_codes.extend(
            post_stop_path_reason_codes(
                seconds=seconds,
                exit_index=actual_exit_index,
                side=side,
                entry_price=entry_fill,
                stop_price=stop_price,
                target_price=target_price,
            )
        )
    return BacktestTrade(
        symbol=symbol,
        side=side,
        entry_time=entry_bar.open_time_iso,
        exit_time=exit_time,
        entry_price=round(entry_fill, 8),
        exit_price=round(exit_fill, 8),
        quantity=round(quantity, 8),
        notional_usdt=round(notional, 8),
        gross_pnl_usdt=round(gross_pnl, 8),
        fees_usdt=round(fees, 8),
        slippage_usdt=round(slippage, 8),
        net_pnl_usdt=round(net_pnl, 8),
        exit_reason=exit_reason,
        mfe_percent=round(mfe_percent, 8),
        mae_percent=round(mae_percent, 8),
        reason_codes=trade_reason_codes,
    ), "filled"


def find_limit_fill_index(
    *,
    seconds: list[BacktestBar],
    entry_index: int,
    side: str,
    limit_price: float,
    max_wait_seconds: int,
) -> int | None:
    wait_seconds = max(1, max_wait_seconds)
    max_index = min(len(seconds) - 1, entry_index + wait_seconds - 1)
    for index in range(entry_index, max_index + 1):
        bar = seconds[index]
        if side == "long" and bar.low <= limit_price:
            return index
        if side == "short" and bar.high >= limit_price:
            return index
    return None


def hold_seconds_from_setup(setup, config: BacktestConfig, *, remaining_seconds: int | None = None) -> int:
    exit_policy = setup.price_basis.get("exit_policy", {}) if isinstance(setup.price_basis, dict) else {}
    if not exit_policy.get("time_exit_enabled", True):
        if remaining_seconds is not None:
            return max(1, remaining_seconds)
        return 1_000_000_000
    max_hold_seconds = max(1, int(config.max_hold_bars * 5 * 60))
    if exit_policy.get("time_exit_use_config_max_hold_only") or setup.hold_time_minutes is None:
        return max_hold_seconds
    return max(1, min(max_hold_seconds, int(setup.hold_time_minutes * 60)))


def floating_profit(side: str, mark_price: float, entry_fill: float) -> bool:
    if side == "long":
        return mark_price > entry_fill
    if side == "short":
        return mark_price < entry_fill
    return False


def path_mfe_mae_percent(*, side: str, entry_fill: float, path_high: float, path_low: float) -> tuple[float, float]:
    if entry_fill <= 0:
        return 0.0, 0.0
    if side == "long":
        mfe = max(path_high - entry_fill, 0.0) / entry_fill * 100.0
        mae = min(path_low - entry_fill, 0.0) / entry_fill * 100.0
        return mfe, mae
    if side == "short":
        mfe = max(entry_fill - path_low, 0.0) / entry_fill * 100.0
        mae = min(entry_fill - path_high, 0.0) / entry_fill * 100.0
        return mfe, mae
    return 0.0, 0.0


def should_early_invalid_exit(
    *,
    setup,
    side: str,
    entry_fill: float,
    risk_per_unit: float,
    best_price: float,
    bar: BacktestBar,
    window: list[BacktestBar],
) -> bool:
    exit_policy = setup.price_basis.get("exit_policy", {}) if isinstance(setup.price_basis, dict) else {}
    if not exit_policy.get("early_exit_enabled", False) or risk_per_unit <= 0:
        return False
    min_seconds = max(1, int(exit_policy.get("early_exit_min_seconds") or 1))
    if len(window) < min_seconds:
        return False
    min_favorable_r = max(float(exit_policy.get("early_exit_min_favorable_r") or 0.0), 0.0)
    max_adverse_r = max(float(exit_policy.get("early_exit_max_adverse_r") or 0.0), 0.0)
    min_votes = max(1, int(exit_policy.get("early_exit_min_adverse_votes") or 1))
    flow_edge = max(float(exit_policy.get("early_exit_flow_edge") or 0.0), 0.0)

    if side == "long":
        favorable_r = (best_price - entry_fill) / risk_per_unit
        current_r = (bar.close - entry_fill) / risk_per_unit
    else:
        favorable_r = (entry_fill - best_price) / risk_per_unit
        current_r = (entry_fill - bar.close) / risk_per_unit
    if favorable_r >= min_favorable_r:
        return False

    votes = 0
    if current_r <= -max_adverse_r:
        votes += 1
    taker_ratio = taker_ratio_from_seconds(window)
    if taker_ratio is not None:
        if side == "long" and taker_ratio <= 1.0 - flow_edge:
            votes += 1
        if side == "short" and taker_ratio >= 1.0 + flow_edge:
            votes += 1
    reference_vwap = setup.price_basis.get("vwap") if isinstance(setup.price_basis, dict) else None
    if isinstance(reference_vwap, (int, float)) and reference_vwap > 0:
        if side == "long" and bar.close < reference_vwap:
            votes += 1
        if side == "short" and bar.close > reference_vwap:
            votes += 1
    return votes >= min_votes


def taker_ratio_from_seconds(window: list[BacktestBar]) -> float | None:
    quote = sum(item.quote_volume for item in window)
    taker_buy = sum(item.taker_buy_quote_volume or 0.0 for item in window)
    taker_sell = quote - taker_buy
    if taker_sell <= 0:
        return None
    return taker_buy / taker_sell


def post_stop_path_reason_codes(
    *,
    seconds: list[BacktestBar],
    exit_index: int,
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    lookahead_seconds: int = 600,
) -> list[str]:
    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit <= 0:
        return ["post_stop_path:unavailable"]
    lookahead = seconds[exit_index + 1 : min(len(seconds), exit_index + 1 + max(1, lookahead_seconds))]
    if not lookahead:
        return ["post_stop_path:unavailable"]
    if side == "long":
        post_low = min(item.low for item in lookahead)
        post_high = max(item.high for item in lookahead)
        adverse_r = max((stop_price - post_low) / risk_per_unit, 0.0)
        recovery_r = (post_high - entry_price) / risk_per_unit
        reached_target = post_high >= target_price
        recovered_entry = post_high >= entry_price
    else:
        post_high = max(item.high for item in lookahead)
        post_low = min(item.low for item in lookahead)
        adverse_r = max((post_high - stop_price) / risk_per_unit, 0.0)
        recovery_r = (entry_price - post_low) / risk_per_unit
        reached_target = post_low <= target_price
        recovered_entry = post_low <= entry_price

    if reached_target or recovery_r >= 1.0:
        classification = "bad_entry_or_stop"
    elif adverse_r >= 0.6 and recovery_r < 0.25 and not recovered_entry:
        classification = "wrong_direction"
    else:
        classification = "noise_chop"
    return [
        f"post_stop_path:{classification}",
        f"post_stop_adverse_r:{round(adverse_r, 4)}",
        f"post_stop_recovery_r:{round(recovery_r, 4)}",
    ]


def compound_replay(trades: list[BacktestTrade], *, config: BacktestConfig) -> dict[str, Any]:
    initial = config.account_capital_usdt
    equity = initial
    peak = initial
    max_drawdown = 0.0
    daily_pnl: dict[str, float] = {}
    open_ids: set[int] = set()
    accepted: list[dict[str, Any]] = []
    skipped_daily = 0
    skipped_concurrency = 0
    trade_by_id = {index: trade for index, trade in enumerate(trades)}
    events: list[tuple[str, int, int]] = []
    for index, trade in trade_by_id.items():
        events.append((trade.entry_time, 1, index))
        events.append((trade.exit_time, 0, index))
    accepted_records: dict[int, dict[str, Any]] = {}
    for event_time, kind, index in sorted(events):
        trade = trade_by_id[index]
        if kind == 0:
            if index not in open_ids:
                continue
            open_ids.remove(index)
            record = accepted_records[index]
            equity += record["net_pnl_usdt"]
            daily_pnl[trade.exit_time[:10]] = daily_pnl.get(trade.exit_time[:10], 0.0) + record["net_pnl_usdt"]
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            record["equity_after_exit_usdt"] = round(equity, 8)
            record["drawdown_after_exit_usdt"] = round(peak - equity, 8)
            accepted.append(record)
            continue

        if equity <= 0:
            skipped_daily += 1
            continue
        day = trade.entry_time[:10]
        scaled_daily_loss_cap = config.max_daily_loss_usdt * max(equity / initial, 0.0)
        if abs(min(daily_pnl.get(day, 0.0), 0.0)) >= scaled_daily_loss_cap:
            skipped_daily += 1
            continue
        if len(open_ids) >= config.max_open_positions:
            skipped_concurrency += 1
            continue
        scale = max(equity / initial, 0.0)
        record = scaled_trade_record(trade, scale=scale, equity_before=equity)
        accepted_records[index] = record
        open_ids.add(index)

    net = sum(item["net_pnl_usdt"] for item in accepted)
    wins = sum(1 for item in accepted if item["net_pnl_usdt"] > 0)
    losses = sum(1 for item in accepted if item["net_pnl_usdt"] < 0)
    gross_profit = sum(item["net_pnl_usdt"] for item in accepted if item["net_pnl_usdt"] > 0)
    gross_loss = abs(sum(item["net_pnl_usdt"] for item in accepted if item["net_pnl_usdt"] < 0))
    summary = {
        "initial_capital_usdt": round(initial, 8),
        "final_capital_usdt": round(equity, 8),
        "net_pnl_usdt": round(net, 8),
        "return_percent": round((equity / initial - 1.0) * 100.0, 8) if initial else 0.0,
        "trade_count": len(accepted),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(accepted), 8) if accepted else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else ("inf" if gross_profit else None),
        "expectancy_usdt": round(net / len(accepted), 8) if accepted else 0.0,
        "fees_usdt": round(sum(item["fees_usdt"] for item in accepted), 8),
        "slippage_usdt": round(sum(item["slippage_usdt"] for item in accepted), 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "max_drawdown_percent_of_initial": round((max_drawdown / initial) * 100.0, 8) if initial else 0.0,
        "skipped_daily_loss_signals": skipped_daily,
        "skipped_concurrency_signals": skipped_concurrency,
        "exit_reason_counts": count_by(accepted, "exit_reason"),
        "side_counts": count_by(accepted, "side"),
    }
    return {"summary": summary, "trades": accepted}


def scaled_trade_record(trade: BacktestTrade, *, scale: float, equity_before: float) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_time": trade.entry_time,
        "exit_time": trade.exit_time,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "quantity": round(trade.quantity * scale, 8),
        "notional_usdt": round(trade.notional_usdt * scale, 8),
        "gross_pnl_usdt": round(trade.gross_pnl_usdt * scale, 8),
        "fees_usdt": round(trade.fees_usdt * scale, 8),
        "slippage_usdt": round(trade.slippage_usdt * scale, 8),
        "net_pnl_usdt": round(trade.net_pnl_usdt * scale, 8),
        "exit_reason": trade.exit_reason,
        "mfe_percent": trade.mfe_percent,
        "mae_percent": trade.mae_percent,
        "reason_codes": list(trade.reason_codes),
        "equity_before_entry_usdt": round(equity_before, 8),
        "equity_scale": round(scale, 8),
    }


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def day_start_ms(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)


def ms_to_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
