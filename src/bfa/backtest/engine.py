"""Backtest engine for the initial hot-momentum futures strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from bfa.backtest.models import BacktestBar, BacktestConfig, BacktestResult, BacktestTrade, built_in_variants


@dataclass(frozen=True)
class _Signal:
    symbol: str
    entry_index: int
    entry_time_ms: int
    reason_codes: list[str]


@dataclass(frozen=True)
class _CandidateTrade:
    signal: _Signal
    trade: BacktestTrade


@dataclass(frozen=True)
class _TradeEvent:
    kind: str
    time: str
    trade: BacktestTrade


def run_hot_momentum_backtest(
    bars_by_symbol: dict[str, list[BacktestBar]],
    config: BacktestConfig | None = None,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> BacktestResult:
    """Run a conservative long-only hot-momentum backtest.

    Signals are generated only from completed bars. Entries occur at the next
    bar open, and same-bar stop/target collisions are resolved against the
    strategy by taking the stop first.
    """

    cfg = config or BacktestConfig()
    filtered = _filter_bars(bars_by_symbol, start_ms=start_ms, end_ms=end_ms)
    candidate_trades: list[_CandidateTrade] = []
    rejected = 0
    for symbol, bars in filtered.items():
        signals, symbol_rejections = _generate_signals(symbol, bars, cfg)
        rejected += symbol_rejections
        for signal in signals:
            trade = _simulate_trade(bars, signal, cfg)
            if trade is not None:
                candidate_trades.append(_CandidateTrade(signal=signal, trade=trade))

    accepted: list[BacktestTrade] = []
    skipped_daily = 0
    skipped_concurrency = 0
    daily_pnl: dict[str, float] = {}

    events = _trade_events(candidate_trades)
    open_trades: list[BacktestTrade] = []
    for event in events:
        if event.kind == "exit":
            open_trades = [trade for trade in open_trades if trade is not event.trade]
            exit_day = event.trade.exit_time[:10]
            daily_pnl[exit_day] = daily_pnl.get(exit_day, 0.0) + event.trade.net_pnl_usdt
            continue

        trade_day = event.trade.entry_time[:10]
        if abs(min(daily_pnl.get(trade_day, 0.0), 0.0)) >= cfg.max_daily_loss_usdt:
            skipped_daily += 1
            continue
        if len(open_trades) >= cfg.max_open_positions:
            skipped_concurrency += 1
            continue
        accepted.append(event.trade)
        open_trades.append(event.trade)

    all_bars = [bar for bars in filtered.values() for bar in bars]
    return BacktestResult(
        config=cfg,
        start_time=min((bar.open_time_iso for bar in all_bars), default=None),
        end_time=max((bar.close_time_iso for bar in all_bars), default=None),
        symbols=sorted(filtered),
        initial_capital_usdt=cfg.account_capital_usdt,
        trades=accepted,
        rejected_signals=rejected,
        skipped_daily_loss_signals=skipped_daily,
        skipped_concurrency_signals=skipped_concurrency,
    )


def run_staged_sweep(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    window_bars: int = 72,
    step_bars: int | None = None,
    variants: Iterable[str] | None = None,
) -> dict[str, Any]:
    if window_bars <= 0:
        raise ValueError("window_bars must be positive")
    step = step_bars or window_bars
    if step <= 0:
        raise ValueError("step_bars must be positive")

    variant_configs = built_in_variants()
    selected = list(variants or ["strict", "balanced", "aggressive"])
    unknown = [name for name in selected if name not in variant_configs]
    if unknown:
        raise ValueError(f"unknown backtest variants: {', '.join(unknown)}")

    windows = _window_ranges(bars_by_symbol, window_bars=window_bars, step_bars=step)
    results: list[dict[str, Any]] = []
    for window in windows:
        for variant in selected:
            result = run_hot_momentum_backtest(
                bars_by_symbol,
                variant_configs[variant],
                start_ms=window[0],
                end_ms=window[1],
            )
            summary = result.summary()
            summary["window_start_ms"] = window[0]
            summary["window_end_ms"] = window[1]
            results.append(summary)

    aggregate: dict[str, dict[str, Any]] = {}
    for variant in selected:
        rows = [row for row in results if row["config_name"] == variant]
        aggregate[variant] = _aggregate_variant(rows, variant_configs[variant])

    return {
        "schema": "bfa_staged_backtest_sweep_v1",
        "window_bars": window_bars,
        "step_bars": step,
        "variants": selected,
        "window_count": len(windows),
        "aggregate": aggregate,
        "windows": results,
        "interpretation": _interpretation(aggregate),
    }


def _filter_bars(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> dict[str, list[BacktestBar]]:
    filtered: dict[str, list[BacktestBar]] = {}
    for symbol, bars in bars_by_symbol.items():
        selected = [
            bar
            for bar in sorted(bars, key=lambda item: item.open_time)
            if (start_ms is None or bar.open_time >= start_ms) and (end_ms is None or bar.open_time <= end_ms)
        ]
        if selected:
            filtered[symbol.upper()] = selected
    return filtered


def _generate_signals(
    symbol: str,
    bars: list[BacktestBar],
    config: BacktestConfig,
) -> tuple[list[_Signal], int]:
    signals: list[_Signal] = []
    rejected = 0
    next_allowed_index = config.lookback_bars
    last_entry_index = len(bars) - 1
    for entry_index in range(config.lookback_bars, last_entry_index + 1):
        if entry_index < next_allowed_index:
            continue
        signal_bar = bars[entry_index - 1]
        lookback_start = bars[entry_index - config.lookback_bars]
        momentum = ((signal_bar.close - lookback_start.open) / lookback_start.open) * 100.0
        taker_ratio = signal_bar.taker_buy_sell_ratio
        reasons: list[str] = []
        rejection = False

        if momentum >= config.min_momentum_percent:
            reasons.append("lookback_momentum")
        else:
            rejection = True
        if signal_bar.quote_volume >= config.min_quote_volume_usdt:
            reasons.append("liquidity_ok")
        else:
            rejection = True
        if taker_ratio is not None and taker_ratio >= config.min_taker_buy_sell_ratio:
            reasons.append("taker_buy_bias")
        else:
            rejection = True
        if signal_bar.range_percent <= config.max_signal_bar_range_percent:
            reasons.append("range_controlled")
        else:
            rejection = True

        if rejection:
            rejected += 1
            continue
        signals.append(
            _Signal(
                symbol=symbol.upper(),
                entry_index=entry_index,
                entry_time_ms=bars[entry_index].open_time,
                reason_codes=reasons,
            )
        )
        next_allowed_index = entry_index + config.cooldown_bars + 1
    return signals, rejected


def _simulate_trade(
    bars: list[BacktestBar],
    signal: _Signal,
    config: BacktestConfig,
) -> BacktestTrade | None:
    entry_bar = bars[signal.entry_index]
    raw_entry = entry_bar.open
    stop_price = raw_entry * (1.0 - config.stop_loss_percent / 100.0)
    target_price = raw_entry * (1.0 + config.take_profit_percent / 100.0)
    notional = min(
        config.max_position_notional_usdt,
        config.max_risk_per_trade_usdt / (config.stop_loss_percent / 100.0),
    )
    if notional <= 0:
        return None

    slippage_rate = config.slippage_bps / 10_000.0
    entry_fill = raw_entry * (1.0 + slippage_rate)
    quantity = notional / raw_entry
    exit_price = bars[min(signal.entry_index + config.max_hold_bars - 1, len(bars) - 1)].close
    exit_reason = "time_exit"
    exit_time = bars[min(signal.entry_index + config.max_hold_bars - 1, len(bars) - 1)].close_time_iso

    max_exit_index = min(len(bars) - 1, signal.entry_index + config.max_hold_bars - 1)
    for index in range(signal.entry_index, max_exit_index + 1):
        bar = bars[index]
        hit_stop = bar.low <= stop_price
        hit_target = bar.high >= target_price
        if hit_stop:
            exit_price = stop_price
            exit_reason = "stop_loss"
            exit_time = bar.close_time_iso
            break
        if hit_target:
            exit_price = target_price
            exit_reason = "take_profit"
            exit_time = bar.close_time_iso
            break

    exit_fill = exit_price * (1.0 - slippage_rate)
    gross_pnl = quantity * (exit_fill - entry_fill)
    entry_fee = quantity * entry_fill * config.taker_fee_rate
    exit_fee = quantity * exit_fill * config.taker_fee_rate
    fees = entry_fee + exit_fee
    slippage = quantity * ((entry_fill - raw_entry) + max(exit_price - exit_fill, 0.0))
    net_pnl = gross_pnl - fees

    return BacktestTrade(
        symbol=signal.symbol,
        side="long",
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
        reason_codes=list(signal.reason_codes),
    )


def _trade_events(candidate_trades: list[_CandidateTrade]) -> list[_TradeEvent]:
    events: list[_TradeEvent] = []
    for item in sorted(candidate_trades, key=lambda candidate: (candidate.signal.entry_time_ms, candidate.trade.symbol)):
        events.append(_TradeEvent(kind="entry", time=item.trade.entry_time, trade=item.trade))
        events.append(_TradeEvent(kind="exit", time=item.trade.exit_time, trade=item.trade))
    return sorted(events, key=lambda event: (event.time, 0 if event.kind == "exit" else 1, event.trade.symbol))


def _window_ranges(
    bars_by_symbol: dict[str, list[BacktestBar]],
    *,
    window_bars: int,
    step_bars: int,
) -> list[tuple[int, int]]:
    all_times = sorted({bar.open_time for bars in bars_by_symbol.values() for bar in bars})
    if len(all_times) < window_bars:
        return []
    ranges: list[tuple[int, int]] = []
    start_index = 0
    while start_index + window_bars <= len(all_times):
        end_index = start_index + window_bars - 1
        ranges.append((all_times[start_index], all_times[end_index]))
        start_index += step_bars
    return ranges


def _aggregate_variant(rows: list[dict[str, Any]], config: BacktestConfig) -> dict[str, Any]:
    net = sum(float(row["net_pnl_usdt"]) for row in rows)
    trade_count = sum(int(row["trade_count"]) for row in rows)
    positive_windows = sum(1 for row in rows if float(row["net_pnl_usdt"]) > 0)
    return {
        "window_count": len(rows),
        "positive_windows": positive_windows,
        "positive_window_rate": round(positive_windows / len(rows), 8) if rows else 0.0,
        "trade_count": trade_count,
        "net_pnl_usdt": round(net, 8),
        "average_window_pnl_usdt": round(net / len(rows), 8) if rows else 0.0,
        "worst_window_pnl_usdt": min((float(row["net_pnl_usdt"]) for row in rows), default=0.0),
        "worst_drawdown_usdt": max((float(row["max_drawdown_usdt"]) for row in rows), default=0.0),
        "max_daily_loss_usdt": config.max_daily_loss_usdt,
    }


def _interpretation(aggregate: dict[str, dict[str, Any]]) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for name, row in aggregate.items():
        if row["trade_count"] < 5:
            verdicts[name] = "insufficient_trades"
        elif row["net_pnl_usdt"] <= 0:
            verdicts[name] = "negative_or_flat"
        elif row["worst_drawdown_usdt"] >= row["max_daily_loss_usdt"]:
            verdicts[name] = "drawdown_exceeds_pilot_cap"
        elif row["positive_window_rate"] < 0.5:
            verdicts[name] = "unstable_across_windows"
        else:
            verdicts[name] = "candidate_for_forward_paper"
    return verdicts
