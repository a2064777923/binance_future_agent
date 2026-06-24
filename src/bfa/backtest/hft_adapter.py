"""Optional hftbacktest adapters for Binance futures research data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
import zipfile
import zlib
from pathlib import Path
from typing import Iterable, Protocol
from urllib.request import urlopen


NANOSECONDS_PER_MILLISECOND = 1_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
BINANCE_FUTURES_DAILY_PUBLIC_URL = "https://data.binance.vision/data/futures/um/daily"


@dataclass(frozen=True)
class AggTradeLike:
    """Minimal aggTrade shape needed for hftbacktest conversion."""

    time_ms: int
    price: float
    quantity: float
    buyer_maker: bool


class AggTradeRow(Protocol):
    time_ms: int
    price: float
    quantity: float
    buyer_maker: bool


@dataclass(frozen=True)
class HftSyntheticBboConfig:
    tick_size: float
    lot_size: float = 0.001
    synthetic_spread_ticks: int = 1
    synthetic_depth_qty: float = 100.0
    feed_latency_ns: int = 0


@dataclass(frozen=True)
class BinancePublicArchive:
    market: str
    symbol: str
    day: date
    path: Path
    url: str
    size_bytes: int


@dataclass(frozen=True)
class BinancePublicBookDepthSummary:
    symbol: str
    day: date
    path: Path
    rows: int
    timestamps: int
    percentages: tuple[float, ...]
    first_timestamp: str | None
    last_timestamp: str | None
    min_interval_seconds: float | None
    median_interval_seconds: float | None
    max_interval_seconds: float | None
    data_quality: str = "aggregated_depth_percent_bands"
    warning: str = (
        "Binance public bookDepth archives are percent-band liquidity summaries, "
        "not tick-by-tick L2 order book updates; do not use them as hftbacktest L2 feed data."
    )

    @property
    def is_l2_order_book(self) -> bool:
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "day": self.day.isoformat(),
            "path": str(self.path),
            "rows": self.rows,
            "timestamps": self.timestamps,
            "percentages": list(self.percentages),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "min_interval_seconds": self.min_interval_seconds,
            "median_interval_seconds": self.median_interval_seconds,
            "max_interval_seconds": self.max_interval_seconds,
            "data_quality": self.data_quality,
            "is_l2_order_book": self.is_l2_order_book,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class HftRawFeedConversion:
    input_path: Path
    output_path: Path | None
    event_count: int
    first_timestamp_ns: int | None
    last_timestamp_ns: int | None
    data_quality: str = "binance_raw_websocket_depth_trade"

    def to_dict(self) -> dict[str, object]:
        return {
            "input_path": str(self.input_path),
            "output_path": str(self.output_path) if self.output_path else None,
            "event_count": self.event_count,
            "first_timestamp_ns": self.first_timestamp_ns,
            "last_timestamp_ns": self.last_timestamp_ns,
            "data_quality": self.data_quality,
        }


@dataclass(frozen=True)
class HftHistoricalCsvConversion:
    depth_path: Path
    trades_path: Path
    output_path: Path | None
    event_count: int
    first_timestamp: int | None
    last_timestamp: int | None
    data_quality: str = "binance_historical_l2_depth_trade_csv"

    def to_dict(self) -> dict[str, object]:
        return {
            "depth_path": str(self.depth_path),
            "trades_path": str(self.trades_path),
            "output_path": str(self.output_path) if self.output_path else None,
            "event_count": self.event_count,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "data_quality": self.data_quality,
        }


@dataclass(frozen=True)
class HftPassiveGridConfig:
    tick_size: float
    lot_size: float
    notional_usdt: float = 20.0
    quote_offset_ticks: int = 1
    max_position_qty: float | None = None
    grid_refresh_ns: int = 1_000_000_000
    step_ns: int = 50_000_000
    max_steps: int = 200_000
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 4.0
    order_latency_ns: int = 0


def convert_agg_trades_to_hft_events(
    trades: Iterable[AggTradeRow],
    *,
    config: HftSyntheticBboConfig,
):
    """Convert aggTrades into hftbacktest event_dtype with synthetic BBO depth.

    This is deliberately marked as a degraded data adapter: aggTrades do not
    contain full order book depth or queue position. The synthetic BBO events
    make a smoke hftbacktest possible while real L2/L3 depth ingestion is added.
    """
    import numpy as np
    from hftbacktest import EXCH_EVENT, LOCAL_EVENT
    from hftbacktest.types import (
        BUY_EVENT,
        DEPTH_SNAPSHOT_EVENT,
        SELL_EVENT,
        TRADE_EVENT,
        event_dtype,
    )

    rows = sorted(
        [row for row in trades if row.price > 0 and row.quantity > 0 and row.time_ms > 0],
        key=lambda item: item.time_ms,
    )
    if not rows:
        return np.empty(0, event_dtype)

    flags = EXCH_EVENT | LOCAL_EVENT
    depth_qty = max(float(config.synthetic_depth_qty), float(config.lot_size))
    half_spread = max(1, int(config.synthetic_spread_ticks)) * float(config.tick_size)
    event_count = 2 + len(rows) * 3
    events = np.empty(event_count, event_dtype)
    cursor = 0

    first_price = rows[0].price
    bid, ask = synthetic_bbo(first_price, tick_size=config.tick_size, half_spread=half_spread)
    ts_ns = rows[0].time_ms * NANOSECONDS_PER_MILLISECOND
    local_ts = ts_ns + int(config.feed_latency_ns)
    events[cursor] = (DEPTH_SNAPSHOT_EVENT | BUY_EVENT | flags, ts_ns, local_ts, bid, depth_qty, 0, 0, 0)
    cursor += 1
    events[cursor] = (DEPTH_SNAPSHOT_EVENT | SELL_EVENT | flags, ts_ns, local_ts, ask, depth_qty, 0, 0, 0)
    cursor += 1

    for row in rows:
        ts_ns = row.time_ms * NANOSECONDS_PER_MILLISECOND
        local_ts = ts_ns + int(config.feed_latency_ns)
        bid, ask = synthetic_bbo(row.price, tick_size=config.tick_size, half_spread=half_spread)
        events[cursor] = (DEPTH_SNAPSHOT_EVENT | BUY_EVENT | flags, ts_ns, local_ts, bid, depth_qty, 0, 0, 0)
        cursor += 1
        events[cursor] = (DEPTH_SNAPSHOT_EVENT | SELL_EVENT | flags, ts_ns, local_ts, ask, depth_qty, 0, 0, 0)
        cursor += 1
        trade_side = SELL_EVENT if row.buyer_maker else BUY_EVENT
        events[cursor] = (TRADE_EVENT | trade_side | flags, ts_ns, local_ts, row.price, row.quantity, 0, 0, 0)
        cursor += 1

    return events[:cursor]


def fetch_binance_public_archive(market: str, symbol: str, day: date, cache_dir: Path) -> BinancePublicArchive:
    """Download a Binance USD-M daily public archive if it exists.

    This helper intentionally stays generic because public Data Vision exposes
    several archive families with different schemas. Callers still need to
    inspect the file before treating it as hftbacktest-quality data.
    """
    market = market.strip().strip("/")
    symbol = symbol.upper()
    symbol_dir = Path(cache_dir) / market / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    name = f"{symbol}-{market}-{day.isoformat()}.zip"
    path = symbol_dir / name
    if path.exists() and path.stat().st_size > 0 and zip_is_valid(path):
        return BinancePublicArchive(market=market, symbol=symbol, day=day, path=path, url=archive_url(market, symbol, day), size_bytes=path.stat().st_size)
    path.unlink(missing_ok=True)
    url = archive_url(market, symbol, day)
    with urlopen(url, timeout=60) as response:  # noqa: S310 - fixed public Binance archive URL.
        path.write_bytes(response.read())
    if not zip_is_valid(path):
        raise ValueError(f"downloaded archive is not a valid zip: {path}")
    return BinancePublicArchive(market=market, symbol=symbol, day=day, path=path, url=url, size_bytes=path.stat().st_size)


def archive_url(market: str, symbol: str, day: date) -> str:
    market = market.strip().strip("/")
    symbol = symbol.upper()
    name = f"{symbol}-{market}-{day.isoformat()}.zip"
    return f"{BINANCE_FUTURES_DAILY_PUBLIC_URL}/{market}/{symbol}/{name}"


def zip_is_valid(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None
    except (OSError, zipfile.BadZipFile, zlib.error):
        return False


def summarize_public_book_depth_archive(symbol: str, day: date, zip_path: Path) -> BinancePublicBookDepthSummary:
    rows = 0
    timestamps: list[str] = []
    seen_timestamps: set[str] = set()
    percentages: set[float] = set()
    with zipfile.ZipFile(zip_path) as zf:
        names = [name for name in zf.namelist() if name.endswith(".csv")]
        if not names:
            raise ValueError(f"bookDepth archive has no csv member: {zip_path}")
        with zf.open(names[0]) as raw:
            reader = csv.DictReader((line.decode("utf-8") for line in raw))
            expected = {"timestamp", "percentage", "depth", "notional"}
            if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
                raise ValueError(f"unexpected bookDepth schema in {zip_path}: {reader.fieldnames}")
            for row in reader:
                rows += 1
                ts = str(row.get("timestamp") or "")
                if ts and ts not in seen_timestamps:
                    seen_timestamps.add(ts)
                    timestamps.append(ts)
                try:
                    percentages.add(float(row.get("percentage", "nan")))
                except (TypeError, ValueError):
                    pass
    intervals = timestamp_intervals_seconds(timestamps)
    return BinancePublicBookDepthSummary(
        symbol=symbol.upper(),
        day=day,
        path=Path(zip_path),
        rows=rows,
        timestamps=len(timestamps),
        percentages=tuple(sorted(percentages)),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        min_interval_seconds=min(intervals) if intervals else None,
        median_interval_seconds=median(intervals) if intervals else None,
        max_interval_seconds=max(intervals) if intervals else None,
    )


def timestamp_intervals_seconds(timestamps: list[str]) -> list[float]:
    from datetime import datetime

    parsed = []
    for value in timestamps:
        try:
            parsed.append(datetime.fromisoformat(value).timestamp())
        except ValueError:
            continue
    return [current - previous for previous, current in zip(parsed, parsed[1:]) if current >= previous]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def convert_binance_raw_feed_to_hft(
    input_path: Path,
    *,
    output_path: Path | None = None,
    opt: str = "",
    base_latency_ns: float = 0,
    combined_stream: bool = True,
    buffer_size: int = 100_000_000,
) -> tuple[object, HftRawFeedConversion]:
    """Convert a self-collected Binance futures raw WebSocket gzip file."""
    from hftbacktest.data.utils import binancefutures

    output = str(output_path) if output_path else None
    events = binancefutures.convert(
        str(input_path),
        output_filename=output,
        opt=opt,
        base_latency=base_latency_ns,
        combined_stream=combined_stream,
        buffer_size=buffer_size,
    )
    first, last = event_time_bounds(events)
    return events, HftRawFeedConversion(
        input_path=Path(input_path),
        output_path=Path(output_path) if output_path else None,
        event_count=int(len(events)),
        first_timestamp_ns=first,
        last_timestamp_ns=last,
    )


def convert_historical_l2_csv_to_hft(
    depth_path: Path,
    trades_path: Path,
    *,
    output_path: Path | None = None,
    feed_latency: float = 0,
    base_latency: float = 0,
    buffer_size: int = 100_000_000,
) -> tuple[object, HftHistoricalCsvConversion]:
    """Convert vendor/self-collected depth CSV + trades CSV into hftbacktest events."""
    from hftbacktest.data.utils import binancehistmktdata

    output = str(output_path) if output_path else None
    events = binancehistmktdata.convert(
        str(depth_path),
        str(trades_path),
        output_filename=output,
        buffer_size=buffer_size,
        feed_latency=feed_latency,
        base_latency=base_latency,
    )
    first, last = event_time_bounds(events)
    return events, HftHistoricalCsvConversion(
        depth_path=Path(depth_path),
        trades_path=Path(trades_path),
        output_path=Path(output_path) if output_path else None,
        event_count=int(len(events)),
        first_timestamp=first,
        last_timestamp=last,
    )


def event_time_bounds(events) -> tuple[int | None, int | None]:
    if len(events) == 0:
        return None, None
    values = [int(value) for value in events["exch_ts"] if int(value) > 0]
    if not values:
        return None, None
    return min(values), max(values)


def build_hft_asset(events, *, config: HftPassiveGridConfig):
    import hftbacktest as hft

    return (
        hft.BacktestAsset()
        .data(events)
        .linear_asset(1.0)
        .tick_size(float(config.tick_size))
        .lot_size(float(config.lot_size))
        .constant_order_latency(int(config.order_latency_ns), int(config.order_latency_ns))
        .no_partial_fill_exchange()
        .trading_value_fee_model(config.maker_fee_bps / 10_000.0, config.taker_fee_bps / 10_000.0)
        .risk_adverse_queue_model()
    )


def run_passive_hft_grid(events, *, config: HftPassiveGridConfig) -> dict[str, object]:
    import hftbacktest as hft

    asset = build_hft_asset(events, config=config)
    hbt = hft.HashMapMarketDepthBacktest([asset])
    try:
        return passive_grid_loop(hbt, hft_module=hft, config=config)
    finally:
        hbt.close()


def passive_grid_loop(hbt, *, hft_module, config: HftPassiveGridConfig) -> dict[str, object]:
    submitted_orders = 0
    canceled_orders = 0
    last_order_id = 1
    last_refresh_ts = 0
    last_timestamp = None
    max_abs_position = 0.0
    max_position_qty = float(config.max_position_qty) if config.max_position_qty is not None else None
    active_order_ids: set[int] = set()

    for step in range(max(1, int(config.max_steps))):
        status = hbt.elapse(max(1, int(config.step_ns)))
        last_timestamp = int(hbt.current_timestamp)
        depth = hbt.depth(0)
        if not valid_depth(depth):
            if status != 0:
                break
            continue

        state = hbt.state_values(0)
        max_abs_position = max(max_abs_position, abs(float(state.position)))
        should_refresh = submitted_orders == 0 or last_timestamp - last_refresh_ts >= max(1, int(config.grid_refresh_ns))
        if should_refresh:
            orders = hbt.orders(0)
            for order_id in list(active_order_ids):
                order = orders.get(order_id)
                if order is not None and bool(order.cancellable):
                    hbt.cancel(0, order_id, False)
                    canceled_orders += 1
            active_order_ids.clear()

            mid = (float(depth.best_bid) + float(depth.best_ask)) / 2.0
            qty = round_to_lot(max(float(config.lot_size), float(config.notional_usdt) / mid), float(config.lot_size))
            if max_position_qty is None or float(state.position) < max_position_qty:
                bid_px = max(float(depth.tick_size), (int(depth.best_bid_tick) - max(0, int(config.quote_offset_ticks))) * float(depth.tick_size))
                hbt.submit_buy_order(0, last_order_id, bid_px, qty, hft_module.GTX, hft_module.LIMIT, False)
                active_order_ids.add(last_order_id)
                last_order_id += 1
                submitted_orders += 1
            if max_position_qty is None or float(state.position) > -max_position_qty:
                ask_px = (int(depth.best_ask_tick) + max(0, int(config.quote_offset_ticks))) * float(depth.tick_size)
                hbt.submit_sell_order(0, last_order_id, ask_px, qty, hft_module.GTX, hft_module.LIMIT, False)
                active_order_ids.add(last_order_id)
                last_order_id += 1
                submitted_orders += 1
            last_refresh_ts = last_timestamp

        if status != 0 and step > 0:
            break

    state = hbt.state_values(0)
    depth = hbt.depth(0)
    return {
        "submitted_orders": submitted_orders,
        "canceled_orders": canceled_orders,
        "last_timestamp": last_timestamp,
        "best_bid": none_if_nan(depth.best_bid),
        "best_ask": none_if_nan(depth.best_ask),
        "best_bid_qty": none_if_nan(depth.best_bid_qty),
        "best_ask_qty": none_if_nan(depth.best_ask_qty),
        "position": float(state.position),
        "max_abs_position": float(max_abs_position),
        "balance": float(state.balance),
        "fee": float(state.fee),
        "num_trades": int(state.num_trades),
        "trading_volume": float(state.trading_volume),
        "trading_value": float(state.trading_value),
    }


def valid_depth(depth) -> bool:
    return (
        is_finite_price(float(depth.best_bid))
        and is_finite_price(float(depth.best_ask))
        and float(depth.best_ask) > float(depth.best_bid)
    )


def round_to_lot(quantity: float, lot_size: float) -> float:
    lot = max(float(lot_size), 1e-12)
    return round(max(lot, quantity) / lot) * lot


def synthetic_bbo(price: float, *, tick_size: float, half_spread: float) -> tuple[float, float]:
    import math

    tick = max(float(tick_size), 1e-12)
    bid = math.floor((price - half_spread) / tick) * tick
    ask = math.ceil((price + half_spread) / tick) * tick
    if ask <= bid:
        ask = bid + tick
    return round(bid, 12), round(ask, 12)


def hftbacktest_available() -> bool:
    try:
        import hftbacktest  # noqa: F401
    except Exception:
        return False
    return True


def is_finite_price(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def none_if_nan(value: float) -> float | None:
    return float(value) if value == value and abs(value) != float("inf") else None
