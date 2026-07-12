"""Historical multi-symbol replay for the public near-BBO scalp lane.

The repository only has public ``aggTrades`` archives for the selected
historical dates.  They contain trade order, price, quantity, and aggressor
side, but not historical bookTicker/L2/queue state.  This module therefore
uses a deliberately explicit synthetic-BBO sensitivity layer.  It is useful
for testing throughput, cross-symbol capacity, feature timing, and directional
robustness; its queue fills must not be presented as authenticated exchange
fills.

The replay is intentionally one-pass:

* raw aggTrades are merged chronologically across symbols;
* raw trades go only to the queue-proxy ledger when an intent is active;
* strategy features are fed as ordered one-second summaries;
* all synthetic-BBO variants share that same tick pass;
* a single ledger per variant enforces the global pending/active capacity.

That shape keeps the expensive strategy work bounded while preserving raw
trade ordering where it matters for the fill/exit proxy.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import csv
import hashlib
import heapq
import io
from pathlib import Path
import re
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
import zipfile

from bfa.backtest.near_bbo_shadow import NearBboShadowConfig, NearBboShadowLedger
from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse
from bfa.strategy.near_bbo_regime import NearBboRegimeConfig


UTC = timezone.utc
_ARCHIVE_RE = re.compile(r"^(?P<symbol>.+)-aggTrades-(?P<day>\d{4}-\d{2}-\d{2})\.zip$")


@dataclass(frozen=True, slots=True)
class ReplayWindow:
    name: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("replay window name must not be empty")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("replay window end must be after start")

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class SyntheticBboVariant:
    """One predeclared synthetic BBO assumption set.

    ``combined_top_notional_usdt`` is the sum of bid and ask notional.  The
    signed imbalance splits that depth between the two sides, which makes the
    resulting queue-ahead geometry visible in the report.
    """

    name: str
    spread_bps: float = 2.5
    combined_top_notional_usdt: float = 15_000.0
    imbalance_scale: float = 0.75
    max_abs_imbalance: float = 0.85
    flow_window_ms: int = 1_000

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("synthetic variant name must not be empty")
        if self.spread_bps <= 0 or self.combined_top_notional_usdt <= 0:
            raise ValueError("synthetic spread and depth must be positive")
        if self.imbalance_scale < 0 or not 0 < self.max_abs_imbalance <= 1:
            raise ValueError("synthetic imbalance controls are invalid")
        if self.flow_window_ms <= 0:
            raise ValueError("synthetic flow window must be positive")


@dataclass(frozen=True, slots=True)
class NearBboReplayConfig:
    account_capital_usdt: float = 400.0
    notional_usdt: float = 120.0
    max_active_intents: int = 3
    warmup_ms: int = 15 * 60_000
    evaluation_interval_ms: int = 3_000
    quote_ttl_ms: int = 5_000
    max_hold_ms: int = 30_000
    post_window_ms: int = 35_000
    setup_mode: str = "article_v2"
    min_top_notional_usdt: float = 1_000.0
    max_signal_volatility_bps: float = 6.0
    max_scout_adverse_bps: float = 6.0
    regime_history_minutes: int = 16
    regime_min_bars: int = 15
    regime_fast_ema_span: int = 5
    regime_slow_ema_span: int = 15
    scout_confirmation_ms: int = 2_000
    scout_ttl_ms: int = 8_000

    def __post_init__(self) -> None:
        if self.account_capital_usdt <= 0 or self.notional_usdt <= 0:
            raise ValueError("replay capital and notional must be positive")
        if self.max_active_intents <= 0:
            raise ValueError("replay capacity must be positive")
        if self.max_active_intents * self.notional_usdt > self.account_capital_usdt + 1e-9:
            raise ValueError("capacity notional exceeds replay capital")
        if self.warmup_ms < 0 or self.evaluation_interval_ms <= 0:
            raise ValueError("replay timing controls are invalid")
        if self.post_window_ms < self.max_hold_ms:
            raise ValueError("post_window_ms must cover max_hold_ms")
        if self.setup_mode not in {"legacy", "article_v2"}:
            raise ValueError("replay setup_mode must be legacy or article_v2")


@dataclass(frozen=True, slots=True)
class NearBboReplayTick:
    symbol: str
    event_time_ms: int
    price: float
    quantity: float
    taker_buy: bool


@dataclass
class _TradeAccumulator:
    second_ms: int
    last_event_time_ms: int
    first_price: float
    last_price: float
    high_price: float
    low_price: float
    taker_buy_quantity: float = 0.0
    taker_sell_quantity: float = 0.0
    quote_volume: float = 0.0
    taker_buy_quote: float = 0.0
    trade_count: int = 0

    @classmethod
    def from_tick(cls, tick: NearBboReplayTick) -> "_TradeAccumulator":
        quote = tick.price * tick.quantity
        return cls(
            second_ms=tick.event_time_ms // 1_000 * 1_000,
            last_event_time_ms=tick.event_time_ms,
            first_price=tick.price,
            last_price=tick.price,
            high_price=tick.price,
            low_price=tick.price,
            taker_buy_quantity=tick.quantity if tick.taker_buy else 0.0,
            taker_sell_quantity=0.0 if tick.taker_buy else tick.quantity,
            quote_volume=quote,
            taker_buy_quote=quote if tick.taker_buy else 0.0,
            trade_count=1,
        )

    def add(self, tick: NearBboReplayTick) -> None:
        # The merged source is chronological, so first/last are stable without
        # an extra sort or per-row timestamp list.
        self.last_event_time_ms = tick.event_time_ms
        self.last_price = tick.price
        self.high_price = max(self.high_price, tick.price)
        self.low_price = min(self.low_price, tick.price)
        if tick.taker_buy:
            self.taker_buy_quantity += tick.quantity
        else:
            self.taker_sell_quantity += tick.quantity
        quote = tick.price * tick.quantity
        self.quote_volume += quote
        if tick.taker_buy:
            self.taker_buy_quote += quote
        self.trade_count += 1


@dataclass
class _RollingFlow:
    window_ms: int
    chunks: deque[tuple[int, float, float]] = field(default_factory=deque)
    signed_quantity: float = 0.0
    total_quantity: float = 0.0

    def add_summary(self, second_ms: int, buy_quantity: float, sell_quantity: float) -> None:
        signed = buy_quantity - sell_quantity
        total = buy_quantity + sell_quantity
        if total <= 0:
            return
        if self.chunks and self.chunks[-1][0] == second_ms:
            old_second, old_signed, old_total = self.chunks.pop()
            self.signed_quantity -= old_signed
            self.total_quantity -= old_total
            signed += old_signed
            total += old_total
        self.chunks.append((second_ms, signed, total))
        self.signed_quantity += signed
        self.total_quantity += total

    def value(self, now_ms: int, window_ms: int | None = None) -> float:
        requested_window_ms = self.window_ms if window_ms is None else max(1, int(window_ms))
        cutoff = now_ms - self.window_ms
        while self.chunks and self.chunks[0][0] + 999 < cutoff:
            _second, signed, total = self.chunks.popleft()
            self.signed_quantity -= signed
            self.total_quantity -= total
        if requested_window_ms == self.window_ms:
            signed_quantity = self.signed_quantity
            total_quantity = self.total_quantity
        else:
            requested_cutoff = now_ms - requested_window_ms
            signed_quantity = 0.0
            total_quantity = 0.0
            for second_ms, signed, total in self.chunks:
                if second_ms + 999 >= requested_cutoff:
                    signed_quantity += signed
                    total_quantity += total
        if total_quantity <= 0:
            return 0.0
        return max(-1.0, min(1.0, signed_quantity / total_quantity))


@dataclass
class _SyntheticBookState:
    last_price: float
    last_trade_time_ms: int
    flow: _RollingFlow


@dataclass
class _VariantRuntime:
    spec: SyntheticBboVariant
    universe: NearBboUniverse
    ledger: NearBboShadowLedger
    rejection_counts: dict[str, int] = field(default_factory=dict)
    admitted_by_lane: dict[str, int] = field(default_factory=dict)
    admitted_by_regime: dict[str, int] = field(default_factory=dict)
    evaluation_ms: list[float] = field(default_factory=list)
    max_active_intents: int = 0
    intent_symbols: set[str] = field(default_factory=set)
    eligible_proposal_count: int = 0
    selected_proposal_count: int = 0
    capacity_selection_dropped_count: int = 0


def utc_ms(value: str | datetime) -> int:
    """Parse an ISO-8601 UTC value into milliseconds."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


def ms_to_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000, tz=UTC).isoformat().replace("+00:00", "Z")


def default_windows() -> tuple[ReplayWindow, ...]:
    """Predeclare varied UTC windows before looking at their outcomes."""

    raw = (
        ("2026-06-30T00:00:00Z", "2026-06-30T03:00:00Z"),
        ("2026-07-03T06:00:00Z", "2026-07-03T09:00:00Z"),
        ("2026-07-05T12:00:00Z", "2026-07-05T15:00:00Z"),
        ("2026-07-08T18:00:00Z", "2026-07-08T21:00:00Z"),
        ("2026-07-10T15:00:00Z", "2026-07-10T18:00:00Z"),
    )
    return tuple(ReplayWindow(day_start[:10], utc_ms(day_start), utc_ms(day_end)) for day_start, day_end in raw)


def archive_path(cache_dir: Path, symbol: str, day: date) -> Path:
    return cache_dir / symbol.upper() / f"{symbol.upper()}-aggTrades-{day.isoformat()}.zip"


def days_for_range(start_ms: int, end_ms: int) -> tuple[date, ...]:
    if end_ms <= start_ms:
        return ()
    start = datetime.fromtimestamp(start_ms / 1_000, tz=UTC).date()
    end = datetime.fromtimestamp((end_ms - 1) / 1_000, tz=UTC).date()
    current = start
    result: list[date] = []
    while current <= end:
        result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def available_symbols(cache_dir: Path, days: Sequence[date]) -> tuple[str, ...]:
    """Return the intersection of symbols with every required archive."""

    if not days:
        return ()
    common: set[str] | None = None
    for day in days:
        names: set[str] = set()
        pattern = f"*-aggTrades-{day.isoformat()}.zip"
        if cache_dir.exists():
            for symbol_dir in cache_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue
                for path in symbol_dir.glob(pattern):
                    match = _ARCHIVE_RE.match(path.name)
                    if match:
                        names.add(match.group("symbol").upper())
        common = names if common is None else common.intersection(names)
        if not common:
            return ()
    return tuple(sorted(common or ()))


def select_symbols_for_window(
    cache_dir: Path,
    window: ReplayWindow,
    *,
    limit: int = 24,
    warmup_ms: int = 15 * 60_000,
    post_window_ms: int = 35_000,
) -> tuple[str, ...]:
    """Select a deterministic, outcome-blind multi-coin watch set."""

    if limit <= 0:
        raise ValueError("symbol limit must be positive")
    days = days_for_range(window.start_ms - warmup_ms, window.end_ms + post_window_ms)
    candidates = available_symbols(cache_dir, days)
    keyed = []
    for symbol in candidates:
        digest = hashlib.sha256(f"{window.name}|{symbol}".encode("utf-8")).hexdigest()
        keyed.append((digest, symbol))
    keyed.sort()
    return tuple(symbol for _digest, symbol in keyed[:limit])


def _parse_archive_row(row: Sequence[str]) -> NearBboReplayTick | None:
    if len(row) < 7 or not row[0].strip().lstrip("-").isdigit():
        return None
    try:
        price = float(row[1])
        quantity = float(row[2])
        event_time_ms = int(row[5])
    except (TypeError, ValueError):
        return None
    if event_time_ms < 0 or price <= 0 or quantity <= 0:
        return None
    return NearBboReplayTick(
        symbol="",
        event_time_ms=event_time_ms,
        price=price,
        quantity=quantity,
        # Binance's ``is_buyer_maker`` means the buyer was the maker, so the
        # sell aggressor is false for taker-buy flow.
        taker_buy=row[6].strip().lower() != "true",
    )


def iter_symbol_ticks(
    cache_dir: Path,
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
) -> Iterator[NearBboReplayTick]:
    """Stream one symbol's selected time range without loading a whole day."""

    normalized = symbol.upper()
    for day in days_for_range(start_ms, end_ms):
        path = archive_path(cache_dir, normalized, day)
        if not path.exists() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"cached aggTrades archive missing: {path}")
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".csv")]
            if not names:
                continue
            with archive.open(names[0]) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    tick = _parse_archive_row(row)
                    if tick is None:
                        continue
                    if tick.event_time_ms < start_ms:
                        continue
                    if tick.event_time_ms >= end_ms:
                        # Binance daily files are ordered by transaction time.
                        return
                    yield NearBboReplayTick(
                        symbol=normalized,
                        event_time_ms=tick.event_time_ms,
                        price=tick.price,
                        quantity=tick.quantity,
                        taker_buy=tick.taker_buy,
                    )


def iter_merged_ticks(
    cache_dir: Path,
    symbols: Sequence[str],
    *,
    start_ms: int,
    end_ms: int,
) -> Iterator[NearBboReplayTick]:
    """K-way merge selected symbol streams in deterministic event order."""

    iterators: list[Iterator[NearBboReplayTick]] = []
    heap: list[tuple[int, str, int, NearBboReplayTick, Iterator[NearBboReplayTick]]] = []
    sequence = 0
    try:
        for symbol in sorted({item.upper() for item in symbols}):
            iterator = iter_symbol_ticks(cache_dir, symbol, start_ms=start_ms, end_ms=end_ms)
            iterators.append(iterator)
            try:
                tick = next(iterator)
            except StopIteration:
                continue
            heapq.heappush(heap, (tick.event_time_ms, tick.symbol, sequence, tick, iterator))
            sequence += 1
        while heap:
            _event_time, _symbol, _sequence, tick, iterator = heapq.heappop(heap)
            yield tick
            try:
                next_tick = next(iterator)
            except StopIteration:
                continue
            heapq.heappush(heap, (next_tick.event_time_ms, next_tick.symbol, sequence, next_tick, iterator))
            sequence += 1
    finally:
        for iterator in iterators:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()


def synthetic_bbo(
    price: float,
    *,
    flow_signed: float,
    spec: SyntheticBboVariant,
) -> tuple[float, float, float, float]:
    """Build a reproducible BBO from trade price and rolling flow only."""

    bounded_flow = max(-1.0, min(1.0, flow_signed))
    imbalance = max(
        -spec.max_abs_imbalance,
        min(spec.max_abs_imbalance, bounded_flow * spec.imbalance_scale),
    )
    half_spread = price * spec.spread_bps / 20_000.0
    bid = price - half_spread
    ask = price + half_spread
    total_quantity = spec.combined_top_notional_usdt / price
    bid_quantity = total_quantity * (1.0 + imbalance) / 2.0
    ask_quantity = total_quantity * (1.0 - imbalance) / 2.0
    return bid, bid_quantity, ask, ask_quantity


def default_variants() -> tuple[SyntheticBboVariant, ...]:
    return (
        SyntheticBboVariant(name="baseline", spread_bps=2.5, combined_top_notional_usdt=15_000.0, imbalance_scale=0.75),
        SyntheticBboVariant(name="low_imbalance", spread_bps=2.5, combined_top_notional_usdt=15_000.0, imbalance_scale=0.35),
        SyntheticBboVariant(name="deep_queue", spread_bps=2.5, combined_top_notional_usdt=30_000.0, imbalance_scale=0.75),
        SyntheticBboVariant(name="wide_spread", spread_bps=4.0, combined_top_notional_usdt=15_000.0, imbalance_scale=0.75),
    )


def _build_strategy_config(config: NearBboReplayConfig) -> NearBboConfig:
    return NearBboConfig(
        quote_ttl_ms=config.quote_ttl_ms,
        max_pending_orders=config.max_active_intents,
        min_top_notional_usdt=config.min_top_notional_usdt,
        # Article-v2 exploration intentionally bypasses uncalibrated heuristic
        # probability gates; structural/liquidity/regime gates remain active.
        min_fill_probability=0.0,
        min_win_probability=0.0,
        min_conditional_net_ev_bps=-1_000.0,
        setup_mode=config.setup_mode,
        regime_config=NearBboRegimeConfig(
            history_minutes=config.regime_history_minutes,
            min_bars=config.regime_min_bars,
            fast_ema_span=config.regime_fast_ema_span,
            slow_ema_span=config.regime_slow_ema_span,
        ),
        scout_confirmation_ms=config.scout_confirmation_ms,
        scout_ttl_ms=config.scout_ttl_ms,
        max_signal_volatility_bps=config.max_signal_volatility_bps,
        max_scout_adverse_bps=config.max_scout_adverse_bps,
    )


def _build_runtime(spec: SyntheticBboVariant, config: NearBboReplayConfig) -> _VariantRuntime:
    strategy_config = _build_strategy_config(config)
    shadow_config = NearBboShadowConfig(
        account_capital_usdt=config.account_capital_usdt,
        notional_usdt=config.notional_usdt,
        max_active_intents=config.max_active_intents,
        max_hold_ms=config.max_hold_ms,
    )
    return _VariantRuntime(
        spec=spec,
        universe=NearBboUniverse(strategy_config),
        ledger=NearBboShadowLedger(shadow_config, strategy_config=strategy_config),
    )


def _merge_counts(target: dict[str, int], additions: Mapping[str, Any]) -> None:
    for key, value in additions.items():
        count = int(value)
        if count:
            target[str(key)] = target.get(str(key), 0) + count


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _metric_counts(items: Iterable[Any], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, key))
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _outcome_metrics(outcomes: Sequence[Any]) -> dict[str, Any]:
    ordered = sorted(outcomes, key=lambda item: (item.exit_time_ms, item.proposal_id))
    net = sum(float(item.net_pnl_usdt) for item in ordered)
    gross_profit = sum(max(0.0, float(item.net_pnl_usdt)) for item in ordered)
    gross_loss = sum(max(0.0, -float(item.net_pnl_usdt)) for item in ordered)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for item in ordered:
        equity += float(item.net_pnl_usdt)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    by_symbol: dict[str, dict[str, float | int]] = {}
    for item in ordered:
        row = by_symbol.setdefault(item.symbol, {"trades": 0, "wins": 0, "net_pnl_usdt": 0.0})
        row["trades"] = int(row["trades"]) + 1
        row["wins"] = int(row["wins"]) + int(item.net_pnl_usdt > 0)
        row["net_pnl_usdt"] = round(float(row["net_pnl_usdt"]) + float(item.net_pnl_usdt), 8)
    positive_symbol_gross = {
        symbol: max(0.0, float(row["net_pnl_usdt"])) for symbol, row in by_symbol.items()
    }
    top_positive = max(positive_symbol_gross.values(), default=0.0)
    return {
        "gross_profit_usdt": round(gross_profit, 8),
        "gross_loss_usdt": round(gross_loss, 8),
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss > 0 else None,
        "net_pnl_usdt": round(net, 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "by_lane": _metric_counts(ordered, "lane"),
        "by_regime": _metric_counts(ordered, "regime"),
        "by_exit_reason": _metric_counts(ordered, "exit_reason"),
        "by_symbol": dict(sorted(by_symbol.items())),
        "positive_symbol_count": sum(1 for value in positive_symbol_gross.values() if value > 0),
        "top_positive_symbol_share_of_gross_profit": round(top_positive / gross_profit, 8)
        if gross_profit > 0
        else 0.0,
        "mean_mfe_bps": round(sum(float(item.mfe_bps) for item in ordered) / len(ordered), 8)
        if ordered
        else None,
        "mean_mae_bps": round(sum(float(item.mae_bps) for item in ordered) / len(ordered), 8)
        if ordered
        else None,
    }


def _runtime_report(
    runtime: _VariantRuntime,
    *,
    window: ReplayWindow,
    symbols: Sequence[str],
    raw_tick_count: int,
    warmup_tick_count: int,
    signal_tick_count: int,
    post_window_tick_count: int,
    evaluation_count: int,
) -> dict[str, Any]:
    outcomes = list(runtime.ledger.outcomes)
    summary = runtime.ledger.summary(now_ms=window.end_ms)
    outcome_metrics = _outcome_metrics(outcomes)
    signal_hours = window.duration_ms / 3_600_000.0
    return {
        "window": {
            "name": window.name,
            "start": ms_to_iso(window.start_ms),
            "end": ms_to_iso(window.end_ms),
            "duration_hours": signal_hours,
        },
        "symbols": list(symbols),
        "synthetic_bbo": asdict(runtime.spec),
        "shadow_summary": summary,
        "metrics": {
            **outcome_metrics,
            "admitted_count": int(summary["admitted_count"]),
            "capacity_rejected_count": int(summary["capacity_rejected_count"]),
            "expired_count": int(summary["expired_count"]),
            "filled_count": int(summary["filled_count"]),
            "closed_count": int(summary["closed_count"]),
            "label_count": int(summary["label_count"]),
            "wins": int(summary["wins"]),
            "losses": int(summary["losses"]),
            "fill_rate": float(summary["fill_rate"]),
            "win_rate": float(summary["win_rate"]),
            "fills_per_signal_hour": int(summary["filled_count"]) / signal_hours
            if signal_hours > 0
            else 0.0,
            "profitable_fills_per_signal_hour": int(summary["wins"]) / signal_hours
            if signal_hours > 0
            else 0.0,
            "max_active_intents": runtime.max_active_intents,
            "unique_intent_symbols": len(runtime.intent_symbols),
            "eligible_proposal_count": runtime.eligible_proposal_count,
            "selected_proposal_count": runtime.selected_proposal_count,
            "capacity_selection_dropped_count": runtime.capacity_selection_dropped_count,
            "evaluation_count": evaluation_count,
            "raw_tick_count": raw_tick_count,
            "warmup_tick_count": warmup_tick_count,
            "signal_tick_count": signal_tick_count,
            "post_window_tick_count": post_window_tick_count,
        },
        "diagnostics": {
            "rejection_counts": dict(sorted(runtime.rejection_counts.items())),
            "admitted_by_lane": dict(sorted(runtime.admitted_by_lane.items())),
            "admitted_by_regime": dict(sorted(runtime.admitted_by_regime.items())),
            "evaluation_ms_p50": _percentile(runtime.evaluation_ms, 0.50),
            "evaluation_ms_p95": _percentile(runtime.evaluation_ms, 0.95),
            "evaluation_ms_max": max(runtime.evaluation_ms) if runtime.evaluation_ms else None,
        },
        "outcomes": [item.to_dict() for item in outcomes],
        "limitations": [
            "BBO, displayed depth, cancellations, and queue priority are synthetic; aggTrades do not contain historical bookTicker/L2.",
            "Synthetic imbalance is derived from rolling aggressor flow and is tested only as a sensitivity assumption.",
            "Queue-proxy fills require opposing aggressor quantity and are not authenticated exchange fills.",
            "This public-data replay is research-only and cannot authorize testnet or live execution.",
        ],
    }


def replay_window(
    cache_dir: Path,
    window: ReplayWindow,
    *,
    symbols: Sequence[str],
    variants: Sequence[SyntheticBboVariant] | None = None,
    config: NearBboReplayConfig | None = None,
) -> dict[str, Any]:
    """Replay one fixed window with all variants in one chronological pass."""

    replay_config = config or NearBboReplayConfig()
    selected_variants = tuple(variants or default_variants())
    if not selected_variants:
        raise ValueError("at least one synthetic variant is required")
    normalized_symbols = tuple(dict.fromkeys(symbol.upper() for symbol in symbols if symbol.strip()))
    if not normalized_symbols:
        raise ValueError("at least one replay symbol is required")
    runtimes = [_build_runtime(spec, replay_config) for spec in selected_variants]
    flows = {
        symbol: _RollingFlow(window_ms=max(spec.flow_window_ms for spec in selected_variants))
        for symbol in normalized_symbols
    }
    books: dict[str, _SyntheticBookState] = {}
    accumulators: dict[str, _TradeAccumulator] = {}
    dirty_symbols: set[str] = set()
    start_replay_ms = window.start_ms - replay_config.warmup_ms
    end_replay_ms = window.end_ms + replay_config.post_window_ms
    next_evaluation_ms = window.start_ms
    evaluation_count = 0
    raw_tick_count = 0
    warmup_tick_count = 0
    signal_tick_count = 0
    post_window_tick_count = 0

    def flush_symbol(symbol: str) -> None:
        accumulator = accumulators.pop(symbol, None)
        if accumulator is None:
            return
        flow = flows[symbol]
        flow.add_summary(
            accumulator.second_ms,
            accumulator.taker_buy_quantity,
            accumulator.taker_sell_quantity,
        )
        books[symbol] = _SyntheticBookState(
            last_price=accumulator.last_price,
            last_trade_time_ms=accumulator.last_event_time_ms,
            flow=flow,
        )
        for runtime in runtimes:
            runtime.universe.ingest_trade_summary(
                symbol=symbol,
                event_time_ms=accumulator.last_event_time_ms,
                first_price=accumulator.first_price,
                last_price=accumulator.last_price,
                high_price=accumulator.high_price,
                low_price=accumulator.low_price,
                taker_buy_quantity=accumulator.taker_buy_quantity,
                taker_sell_quantity=accumulator.taker_sell_quantity,
                quote_volume=accumulator.quote_volume,
                taker_buy_quote=accumulator.taker_buy_quote,
                trade_count=accumulator.trade_count,
            )
        dirty_symbols.add(symbol)

    def flush_all() -> None:
        for symbol in tuple(accumulators):
            flush_symbol(symbol)

    def update_books() -> None:
        for symbol in tuple(dirty_symbols):
            state = books[symbol]
            for runtime in runtimes:
                flow_value = state.flow.value(
                    state.last_trade_time_ms,
                    runtime.spec.flow_window_ms,
                )
                bid, bid_quantity, ask, ask_quantity = synthetic_bbo(
                    state.last_price,
                    flow_signed=flow_value,
                    spec=runtime.spec,
                )
                runtime.universe.ingest_book_ticker(
                    symbol=symbol,
                    event_time_ms=state.last_trade_time_ms,
                    bid_price=bid,
                    bid_quantity=bid_quantity,
                    ask_price=ask,
                    ask_quantity=ask_quantity,
                )
        dirty_symbols.clear()

    def evaluate(now_ms: int) -> None:
        nonlocal evaluation_count
        flush_all()
        update_books()
        for runtime in runtimes:
            started = time.perf_counter()
            runtime.ledger.advance(now_ms)
            proposals, diagnostics = runtime.universe.rank_opportunities(
                now_ms=now_ms,
                excluded_symbols=runtime.ledger.active_symbols,
                capacity=runtime.ledger.available_capacity,
            )
            admitted = runtime.ledger.admit(proposals)
            elapsed = (time.perf_counter() - started) * 1_000.0
            runtime.evaluation_ms.append(elapsed)
            _merge_counts(runtime.rejection_counts, diagnostics.get("rejection_counts", {}))
            eligible_count = int(diagnostics.get("eligible_count") or 0)
            selected_count = int(diagnostics.get("selected_count") or 0)
            runtime.eligible_proposal_count += eligible_count
            runtime.selected_proposal_count += selected_count
            runtime.capacity_selection_dropped_count += max(0, eligible_count - selected_count)
            for proposal in admitted:
                runtime.admitted_by_lane[proposal.lane] = runtime.admitted_by_lane.get(proposal.lane, 0) + 1
                runtime.admitted_by_regime[proposal.regime] = runtime.admitted_by_regime.get(proposal.regime, 0) + 1
                runtime.intent_symbols.add(proposal.symbol)
            runtime.max_active_intents = max(runtime.max_active_intents, runtime.ledger.active_intent_count)
        evaluation_count += 1

    tick_iter = iter_merged_ticks(
        cache_dir,
        normalized_symbols,
        start_ms=start_replay_ms,
        end_ms=end_replay_ms,
    )
    for tick in tick_iter:
        raw_tick_count += 1
        while next_evaluation_ms < tick.event_time_ms and next_evaluation_ms < window.end_ms:
            evaluate(next_evaluation_ms)
            next_evaluation_ms += replay_config.evaluation_interval_ms
        if tick.event_time_ms < window.start_ms:
            warmup_tick_count += 1
            accumulator = accumulators.get(tick.symbol)
            second_ms = tick.event_time_ms // 1_000 * 1_000
            if accumulator is None or accumulator.second_ms != second_ms:
                if accumulator is not None:
                    flush_symbol(tick.symbol)
                accumulators[tick.symbol] = _TradeAccumulator.from_tick(tick)
            else:
                accumulator.add(tick)
            continue
        if tick.event_time_ms >= window.end_ms:
            post_window_tick_count += 1
            for runtime in runtimes:
                if runtime.ledger.has_active_symbol(tick.symbol):
                    runtime.ledger.on_trade(
                        symbol=tick.symbol,
                        event_time_ms=tick.event_time_ms,
                        price=tick.price,
                        quantity=tick.quantity,
                        taker_buy=tick.taker_buy,
                    )
                    runtime.max_active_intents = max(runtime.max_active_intents, runtime.ledger.active_intent_count)
            continue
        signal_tick_count += 1
        for runtime in runtimes:
            if runtime.ledger.has_active_symbol(tick.symbol):
                runtime.ledger.on_trade(
                    symbol=tick.symbol,
                    event_time_ms=tick.event_time_ms,
                    price=tick.price,
                    quantity=tick.quantity,
                    taker_buy=tick.taker_buy,
                )
                runtime.max_active_intents = max(runtime.max_active_intents, runtime.ledger.active_intent_count)
        accumulator = accumulators.get(tick.symbol)
        second_ms = tick.event_time_ms // 1_000 * 1_000
        if accumulator is None or accumulator.second_ms != second_ms:
            if accumulator is not None:
                flush_symbol(tick.symbol)
            accumulators[tick.symbol] = _TradeAccumulator.from_tick(tick)
        else:
            accumulator.add(tick)

    flush_all()
    while next_evaluation_ms < window.end_ms:
        evaluate(next_evaluation_ms)
        next_evaluation_ms += replay_config.evaluation_interval_ms
    final_ms = window.end_ms + replay_config.post_window_ms
    for runtime in runtimes:
        runtime.ledger.advance(final_ms)
        runtime.max_active_intents = max(runtime.max_active_intents, runtime.ledger.active_intent_count)

    reports = [
        _runtime_report(
            runtime,
            window=window,
            symbols=normalized_symbols,
            raw_tick_count=raw_tick_count,
            warmup_tick_count=warmup_tick_count,
            signal_tick_count=signal_tick_count,
            post_window_tick_count=post_window_tick_count,
            evaluation_count=evaluation_count,
        )
        for runtime in runtimes
    ]
    return {
        "schema": "bfa_near_bbo_historical_replay_v1",
        "window": {
            "name": window.name,
            "start": ms_to_iso(window.start_ms),
            "end": ms_to_iso(window.end_ms),
            "warmup_start": ms_to_iso(start_replay_ms),
            "post_window_end": ms_to_iso(end_replay_ms),
        },
        "replay_config": asdict(replay_config),
        "symbols": list(normalized_symbols),
        "data_quality": {
            "source": "Binance USD-M public daily aggTrades ZIP archives",
            "historical_book_state": "unavailable",
            "bbo_mode": "synthetic_trade_flow_sensitivity",
            "fill_mode": "queue_proxy_opposing_aggressor_quantity",
            "warning": "Results are degraded research evidence, not authentic historical order-book or queue fills.",
        },
        "raw_tick_count": raw_tick_count,
        "warmup_tick_count": warmup_tick_count,
        "signal_tick_count": signal_tick_count,
        "post_window_tick_count": post_window_tick_count,
        "evaluation_count": evaluation_count,
        "variants": {report["synthetic_bbo"]["name"]: report for report in reports},
    }


def aggregate_variant_reports(window_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate fixed windows without hiding per-window dispersion."""

    if not window_reports:
        return {}
    by_variant: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for report in window_reports:
        for name, variant in (report.get("variants") or {}).items():
            by_variant[str(name)].append(variant)
    aggregate: dict[str, Any] = {}
    for name, reports in sorted(by_variant.items()):
        outcomes = []
        positive_windows = 0
        symbols: set[str] = set()
        for report in reports:
            outcomes.extend(report.get("outcomes") or [])
            symbols.update(report.get("symbols") or [])
            if float((report.get("metrics") or {}).get("net_pnl_usdt") or 0.0) > 0:
                positive_windows += 1
        # Reconstruct lightweight outcome objects from dictionaries so the same
        # metric function remains the single source of truth.
        class _Outcome:
            def __init__(self, payload: Mapping[str, Any]) -> None:
                for key, value in payload.items():
                    setattr(self, key, value)

        converted = [_Outcome(item) for item in outcomes]
        metrics = _outcome_metrics(converted)
        metrics.update(
            {
                "window_count": len(reports),
                "positive_window_count": positive_windows,
                "positive_window_rate": positive_windows / len(reports) if reports else 0.0,
                "symbol_count": len(symbols),
                "admitted_count": sum(int((r.get("metrics") or {}).get("admitted_count") or 0) for r in reports),
                "capacity_rejected_count": sum(int((r.get("metrics") or {}).get("capacity_rejected_count") or 0) for r in reports),
                "expired_count": sum(int((r.get("metrics") or {}).get("expired_count") or 0) for r in reports),
                "filled_count": sum(int((r.get("metrics") or {}).get("filled_count") or 0) for r in reports),
                "closed_count": sum(int((r.get("metrics") or {}).get("closed_count") or 0) for r in reports),
                "wins": sum(int((r.get("metrics") or {}).get("wins") or 0) for r in reports),
                "losses": sum(int((r.get("metrics") or {}).get("losses") or 0) for r in reports),
                "raw_tick_count": sum(int(r.get("metrics", {}).get("raw_tick_count") or 0) for r in reports),
                "evaluation_count": sum(int(r.get("metrics", {}).get("evaluation_count") or 0) for r in reports),
                "max_active_intents_observed": max(
                    (int(r.get("metrics", {}).get("max_active_intents") or 0) for r in reports),
                    default=0,
                ),
                "eligible_proposal_count": sum(
                    int(r.get("metrics", {}).get("eligible_proposal_count") or 0) for r in reports
                ),
                "selected_proposal_count": sum(
                    int(r.get("metrics", {}).get("selected_proposal_count") or 0) for r in reports
                ),
                "capacity_selection_dropped_count": sum(
                    int(r.get("metrics", {}).get("capacity_selection_dropped_count") or 0)
                    for r in reports
                ),
            }
        )
        gross_fills = metrics["filled_count"]
        metrics["win_rate"] = metrics["wins"] / metrics["closed_count"] if metrics["closed_count"] else 0.0
        signal_hours = sum(float((r.get("window") or {}).get("duration_hours") or 0.0) for r in reports)
        metrics["fills_per_signal_hour"] = gross_fills / signal_hours if signal_hours > 0 else 0.0
        metrics["profitable_fills_per_signal_hour"] = metrics["wins"] / signal_hours if signal_hours > 0 else 0.0
        aggregate[name] = {
            "metrics": metrics,
            "synthetic_bbo": reports[0].get("synthetic_bbo"),
            "windows": [
                {
                    "name": (r.get("window") or {}).get("name"),
                    "metrics": r.get("metrics"),
                }
                for r in reports
            ],
        }
    return aggregate


__all__ = [
    "NearBboReplayConfig",
    "NearBboReplayTick",
    "ReplayWindow",
    "SyntheticBboVariant",
    "aggregate_variant_reports",
    "archive_path",
    "available_symbols",
    "default_variants",
    "default_windows",
    "days_for_range",
    "iter_merged_ticks",
    "iter_symbol_ticks",
    "ms_to_iso",
    "replay_window",
    "select_symbols_for_window",
    "synthetic_bbo",
    "utc_ms",
]
