"""Read-only forward-paper signal recorder for calibrated quant setups."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Mapping

from bfa.ai.schema import RiskLimits
from bfa.backtest.data import INTERVAL_MS
from bfa.backtest.models import BacktestBar, BacktestConfig, built_in_variants
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.strategy.indicators import KlinePoint, compute_indicator_snapshot
from bfa.strategy.setup import TradeSetup, build_trade_setup


@dataclass(frozen=True)
class PaperSignal:
    symbol: str
    interval: str
    variant: str
    opened_at: str
    expiry_time: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    notional_usdt: float
    hold_bars: int
    setup: dict[str, Any]
    recorded_at: str | None = None
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_paper_signal_v1",
            "symbol": self.symbol,
            "interval": self.interval,
            "variant": self.variant,
            "opened_at": self.opened_at,
            "expiry_time": self.expiry_time,
            "side": self.side,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "notional_usdt": self.notional_usdt,
            "hold_bars": self.hold_bars,
            "recorded_at": self.recorded_at,
            "status": self.status,
            "setup": dict(self.setup),
        }


@dataclass(frozen=True)
class PaperOutcome:
    signal_event_id: int
    symbol: str
    interval: str
    variant: str
    opened_at: str
    closed_at: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    notional_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    slippage_usdt: float
    net_pnl_usdt: float
    exit_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_paper_outcome_v1",
            "signal_event_id": self.signal_event_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "variant": self.variant,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "notional_usdt": self.notional_usdt,
            "gross_pnl_usdt": self.gross_pnl_usdt,
            "fees_usdt": self.fees_usdt,
            "slippage_usdt": self.slippage_usdt,
            "net_pnl_usdt": self.net_pnl_usdt,
            "exit_reason": self.exit_reason,
        }


@dataclass(frozen=True)
class ForwardPaperRunReport:
    status: str
    variant: str
    interval: str
    symbols: list[str]
    generated_signals: int = 0
    skipped_signals: int = 0
    settled_outcomes: int = 0
    reasons: list[str] = field(default_factory=list)
    paper_signals: list[dict[str, Any]] = field(default_factory=list)
    paper_outcomes: list[dict[str, Any]] = field(default_factory=list)
    persisted: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"paper_run_complete", "no_symbols"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_forward_paper_run_v1",
            "status": self.status,
            "variant": self.variant,
            "interval": self.interval,
            "symbols": list(self.symbols),
            "generated_signals": self.generated_signals,
            "skipped_signals": self.skipped_signals,
            "settled_outcomes": self.settled_outcomes,
            "reasons": list(self.reasons),
            "paper_signals": list(self.paper_signals),
            "paper_outcomes": list(self.paper_outcomes),
            "persisted": dict(self.persisted),
        }


def run_forward_paper(
    *,
    client,
    db_path: str,
    symbols: list[str],
    interval: str = "5m",
    variant: str = "quant_setup_selective",
    limit: int = 36,
    now: str | None = None,
) -> ForwardPaperRunReport:
    selected_symbols = _symbols(symbols)
    if not selected_symbols:
        return ForwardPaperRunReport(
            status="no_symbols",
            variant=variant,
            interval=interval,
            symbols=[],
            reasons=["no_symbols_selected"],
        )
    config = _variant_config(variant)
    connection = connect(db_path)
    try:
        store = EventStore(connection)
        bars_by_symbol = _fetch_bars(client, selected_symbols, interval=interval, limit=limit)
        outcomes, outcome_event_ids = _settle_open_signals(
            connection,
            store,
            bars_by_symbol=bars_by_symbol,
            interval=interval,
            variant=variant,
            config=config,
            now=now,
        )
        signals, signal_event_ids, skipped = _generate_new_signals(
            connection,
            store,
            bars_by_symbol=bars_by_symbol,
            interval=interval,
            variant=variant,
            config=config,
            now=now,
        )
    finally:
        connection.close()

    return ForwardPaperRunReport(
        status="paper_run_complete",
        variant=variant,
        interval=interval,
        symbols=selected_symbols,
        generated_signals=len(signals),
        skipped_signals=skipped,
        settled_outcomes=len(outcomes),
        paper_signals=[signal.to_dict() for signal in signals],
        paper_outcomes=[outcome.to_dict() for outcome in outcomes],
        persisted={
            "paper_signals": len(signal_event_ids),
            "paper_outcomes": len(outcome_event_ids),
        },
    )


def _fetch_bars(client, symbols: list[str], *, interval: str, limit: int) -> dict[str, list[BacktestBar]]:
    rows: dict[str, list[BacktestBar]] = {}
    for symbol in symbols:
        response = client.klines(symbol, interval=interval, limit=limit)
        payload = response.payload if isinstance(response.payload, list) else []
        rows[symbol] = [BacktestBar.from_binance_kline(symbol, row) for row in payload]
    return rows


def _settle_open_signals(
    connection: sqlite3.Connection,
    store: EventStore,
    *,
    bars_by_symbol: dict[str, list[BacktestBar]],
    interval: str,
    variant: str,
    config: BacktestConfig,
    now: str | None,
) -> tuple[list[PaperOutcome], list[int]]:
    outcomes: list[PaperOutcome] = []
    event_ids: list[int] = []
    for row in _open_signal_rows(connection, interval=interval, variant=variant):
        payload = json.loads(row["payload_json"])
        if _has_outcome(connection, int(row["event_id"])):
            continue
        bars = bars_by_symbol.get(str(row["symbol"]).upper(), [])
        outcome = _settle_signal(
            int(row["event_id"]),
            payload,
            bars,
            config=config,
            now=now,
        )
        if outcome is None:
            continue
        event_id = store.insert_artifact(
            "paper_outcomes",
            occurred_at=outcome.closed_at,
            source="ops.forward_paper",
            symbol=outcome.symbol,
            ref_id=f"paper_outcome:{outcome.signal_event_id}",
            payload=outcome.to_dict(),
            event_type="paper_outcome",
        )
        outcomes.append(outcome)
        event_ids.append(event_id)
    return outcomes, event_ids


def _generate_new_signals(
    connection: sqlite3.Connection,
    store: EventStore,
    *,
    bars_by_symbol: dict[str, list[BacktestBar]],
    interval: str,
    variant: str,
    config: BacktestConfig,
    now: str | None,
) -> tuple[list[PaperSignal], list[int], int]:
    signals: list[PaperSignal] = []
    event_ids: list[int] = []
    skipped = 0
    for symbol, bars in sorted(bars_by_symbol.items()):
        if _has_open_signal(connection, symbol=symbol, interval=interval, variant=variant):
            skipped += 1
            continue
        signal = _build_paper_signal(symbol, bars, interval=interval, variant=variant, config=config, now=now)
        if signal is None:
            skipped += 1
            continue
        event_id = store.insert_artifact(
            "paper_signals",
            occurred_at=signal.opened_at,
            source="ops.forward_paper",
            symbol=signal.symbol,
            ref_id=f"paper_signal:{signal.symbol}:{signal.interval}:{signal.variant}:{signal.opened_at}",
            payload=signal.to_dict(),
            event_type="paper_signal",
        )
        signals.append(signal)
        event_ids.append(event_id)
    return signals, event_ids, skipped


def _build_paper_signal(
    symbol: str,
    bars: list[BacktestBar],
    *,
    interval: str,
    variant: str,
    config: BacktestConfig,
    now: str | None,
) -> PaperSignal | None:
    if len(bars) <= config.lookback_bars:
        return None
    sorted_bars = sorted(bars, key=lambda item: item.open_time)
    lookback = sorted_bars[-(config.lookback_bars + 1) : -1]
    entry_bar = sorted_bars[-1]
    setup = build_trade_setup(
        _candidate_from_bars(symbol, lookback, config),
        risk_limits=_risk_limits_from_backtest_config(config),
        profile=config.setup_profile,
    )
    if setup.decision != "trade":
        return None
    if setup.entry_price is None or setup.stop_price is None or setup.target_price is None or setup.notional_usdt is None:
        return None
    hold_bars = _hold_bars_from_setup(setup, config)
    return PaperSignal(
        symbol=symbol.upper(),
        interval=interval,
        variant=variant,
        opened_at=entry_bar.open_time_iso,
        expiry_time=_expiry_time(entry_bar, interval=interval, hold_bars=hold_bars),
        side=setup.side,
        entry_price=round(entry_bar.open, 8),
        stop_price=setup.stop_price,
        target_price=setup.target_price,
        notional_usdt=setup.notional_usdt,
        hold_bars=hold_bars,
        setup=setup.to_dict(),
        recorded_at=now,
    )


def _settle_signal(
    signal_event_id: int,
    payload: Mapping[str, Any],
    bars: list[BacktestBar],
    *,
    config: BacktestConfig,
    now: str | None,
) -> PaperOutcome | None:
    symbol = str(payload.get("symbol") or "").upper()
    opened_at = str(payload.get("opened_at") or "")
    future_bars = [bar for bar in sorted(bars, key=lambda item: item.open_time) if bar.open_time_iso > opened_at]
    if not future_bars:
        return None

    side = str(payload.get("side") or "")
    entry_price = _float_or_zero(payload.get("entry_price"))
    stop_price = _float_or_zero(payload.get("stop_price"))
    target_price = _float_or_zero(payload.get("target_price"))
    notional = _float_or_zero(payload.get("notional_usdt"))
    hold_bars = max(1, _int_or_zero(payload.get("hold_bars")))
    bars_to_check = future_bars[:hold_bars]
    for bar in bars_to_check:
        if side == "long":
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
        if hit_stop:
            exit_price = stop_price
            exit_reason = "stop_loss"
            closed_at = bar.close_time_iso
            break
        if hit_target:
            exit_price = target_price
            exit_reason = "take_profit"
            closed_at = bar.close_time_iso
            break
    else:
        if len(future_bars) < hold_bars:
            return None
        exit_bar = future_bars[hold_bars - 1]
        exit_price = exit_bar.close
        exit_reason = "time_exit"
        closed_at = exit_bar.close_time_iso

    return _paper_outcome(
        signal_event_id,
        payload,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        closed_at=closed_at,
        notional=notional,
        exit_reason=exit_reason,
        config=config,
    )


def _paper_outcome(
    signal_event_id: int,
    payload: Mapping[str, Any],
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    closed_at: str,
    notional: float,
    exit_reason: str,
    config: BacktestConfig,
) -> PaperOutcome:
    slippage_rate = config.slippage_bps / 10_000.0
    entry_fill = entry_price * (1.0 + slippage_rate) if side == "long" else entry_price * (1.0 - slippage_rate)
    exit_fill = exit_price * (1.0 - slippage_rate) if side == "long" else exit_price * (1.0 + slippage_rate)
    quantity = notional / entry_price if entry_price > 0 else 0.0
    if side == "long":
        gross_pnl = quantity * (exit_fill - entry_fill)
        slippage = quantity * ((entry_fill - entry_price) + max(exit_price - exit_fill, 0.0))
    else:
        gross_pnl = quantity * (entry_fill - exit_fill)
        slippage = quantity * (max(entry_price - entry_fill, 0.0) + (exit_fill - exit_price))
    fees = quantity * entry_fill * config.taker_fee_rate + quantity * exit_fill * config.taker_fee_rate
    return PaperOutcome(
        signal_event_id=signal_event_id,
        symbol=str(payload.get("symbol") or "").upper(),
        interval=str(payload.get("interval") or ""),
        variant=str(payload.get("variant") or ""),
        opened_at=str(payload.get("opened_at") or ""),
        closed_at=closed_at,
        side=side,
        entry_price=round(entry_fill, 8),
        exit_price=round(exit_fill, 8),
        quantity=round(quantity, 8),
        notional_usdt=round(notional, 8),
        gross_pnl_usdt=round(gross_pnl, 8),
        fees_usdt=round(fees, 8),
        slippage_usdt=round(slippage, 8),
        net_pnl_usdt=round(gross_pnl - fees, 8),
        exit_reason=exit_reason,
    )


def _candidate_from_bars(symbol: str, bars: list[BacktestBar], config: BacktestConfig) -> dict[str, Any]:
    first = bars[0]
    last = bars[-1]
    previous = bars[-2] if len(bars) >= 2 else first
    taker_ratio = last.taker_buy_sell_ratio
    previous_taker_ratio = previous.taker_buy_sell_ratio
    indicators = compute_indicator_snapshot(
        KlinePoint(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            quote_volume=bar.quote_volume,
            taker_buy_sell_ratio=bar.taker_buy_sell_ratio,
        )
        for bar in bars
    )
    features = {
        "mention_count": 1,
        "source_count": 1,
        "author_count": 1,
        "engagement_score": min(abs(_momentum_percent(first.open, last.close)) * 10.0, 100.0),
        "price_change_percent": _momentum_percent(first.open, last.close),
        "quote_volume": last.quote_volume,
        "open_interest_value": None,
        "taker_buy_sell_ratio": taker_ratio,
        "taker_buy_sell_ratio_change": (taker_ratio - previous_taker_ratio)
        if taker_ratio is not None and previous_taker_ratio is not None
        else None,
        "funding_rate": 0.0,
        "kline_range_percent": last.range_percent,
        "kline_range_mean_percent": sum(bar.range_percent for bar in bars) / len(bars),
        "kline_range_max_percent": max(bar.range_percent for bar in bars),
        "kline_momentum_percent": _momentum_percent(first.open, last.close),
        "kline_micro_momentum_percent": _momentum_percent(previous.close, last.close),
        "kline_close_position_percent": _close_position_percent(last),
        "kline_quote_volume_change_percent": _momentum_percent(previous.quote_volume, last.quote_volume),
        "reference_price": last.close,
        "min_executable_notional": 5.0,
    }
    features.update({key: value for key, value in indicators.to_features().items() if value is not None})
    return {
        "symbol": symbol.upper(),
        "score": 0.0,
        "narrative_score": 0.0,
        "market_score": 0.0,
        "reason_codes": ["forward_paper_quant_setup"],
        "features": features,
    }


def _open_signal_rows(connection: sqlite3.Connection, *, interval: str, variant: str):
    return connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM paper_signals
        WHERE json_extract(payload_json, '$.interval') = ?
          AND json_extract(payload_json, '$.variant') = ?
          AND json_extract(payload_json, '$.status') = 'open'
        ORDER BY occurred_at ASC, id ASC
        """,
        (interval, variant),
    ).fetchall()


def _has_open_signal(connection: sqlite3.Connection, *, symbol: str, interval: str, variant: str) -> bool:
    rows = connection.execute(
        """
        SELECT event_id
        FROM paper_signals
        WHERE symbol = ?
          AND json_extract(payload_json, '$.interval') = ?
          AND json_extract(payload_json, '$.variant') = ?
          AND json_extract(payload_json, '$.status') = 'open'
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """,
        (symbol.upper(), interval, variant),
    ).fetchall()
    return any(not _has_outcome(connection, int(row["event_id"])) for row in rows)


def _has_outcome(connection: sqlite3.Connection, signal_event_id: int) -> bool:
    row = connection.execute(
        """
        SELECT id
        FROM paper_outcomes
        WHERE json_extract(payload_json, '$.signal_event_id') = ?
        LIMIT 1
        """,
        (signal_event_id,),
    ).fetchone()
    return row is not None


def _variant_config(variant: str) -> BacktestConfig:
    variants = built_in_variants()
    if variant not in variants:
        raise ValueError(f"unknown backtest variant: {variant}")
    config = variants[variant]
    if config.strategy_type != "quant_setup":
        raise ValueError("forward-paper recorder requires a quant_setup variant")
    return config


def _risk_limits_from_backtest_config(config: BacktestConfig) -> RiskLimits:
    return RiskLimits(
        account_capital_usdt=config.account_capital_usdt,
        max_leverage=config.max_leverage,
        max_position_notional_usdt=config.max_position_notional_usdt,
        max_risk_per_trade_usdt=config.max_risk_per_trade_usdt,
        max_daily_loss_usdt=config.max_daily_loss_usdt,
        max_open_positions=config.max_open_positions,
    )


def _hold_bars_from_setup(setup: TradeSetup, config: BacktestConfig) -> int:
    if setup.hold_time_minutes is None:
        return config.max_hold_bars
    return max(1, min(config.max_hold_bars, round(setup.hold_time_minutes / 5)))


def _expiry_time(entry_bar: BacktestBar, *, interval: str, hold_bars: int) -> str:
    interval_ms = INTERVAL_MS.get(interval, 300_000)
    close_time = entry_bar.open_time + max(1, hold_bars) * interval_ms - 1
    return BacktestBar(
        symbol=entry_bar.symbol,
        open_time=entry_bar.open_time,
        open=entry_bar.open,
        high=entry_bar.high,
        low=entry_bar.low,
        close=entry_bar.close,
        volume=entry_bar.volume,
        close_time=close_time,
        quote_volume=entry_bar.quote_volume,
        taker_buy_quote_volume=entry_bar.taker_buy_quote_volume,
    ).close_time_iso


def _momentum_percent(start: float, end: float) -> float:
    if start <= 0:
        return 0.0
    return ((end - start) / start) * 100.0


def _close_position_percent(bar: BacktestBar) -> float | None:
    if bar.high <= bar.low:
        return None
    return ((bar.close - bar.low) / (bar.high - bar.low)) * 100.0


def _symbols(symbols: list[str]) -> list[str]:
    return _dedupe([symbol.strip().upper() for symbol in symbols if symbol.strip()])


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
