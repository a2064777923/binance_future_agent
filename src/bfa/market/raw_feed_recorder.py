"""Raw Binance futures public feed recording helpers for hftbacktest."""

from __future__ import annotations

import gzip
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from bfa.market.binance_ws import combined_stream_url, depth_stream, trade_stream


BINANCE_USDM_WS_BASE_URL = "wss://fstream.binance.com"
_SYMBOL_PRUNE_INTERVAL_MS = 10_000
_GLOBAL_PRUNE_INTERVAL_MS = 60_000


@dataclass(frozen=True)
class RawFeedRecorderConfig:
    symbols: tuple[str, ...]
    output_path: Path
    base_url: str = BINANCE_USDM_WS_BASE_URL
    depth_speed_ms: int = 100
    include_trades: bool = True

    @property
    def streams(self) -> tuple[str, ...]:
        streams: list[str] = []
        for symbol in self.symbols:
            streams.append(depth_stream(symbol, self.depth_speed_ms))
            if self.include_trades:
                streams.append(trade_stream(symbol))
        return tuple(streams)

    @property
    def websocket_url(self) -> str:
        return combined_stream_url(self.base_url, list(self.streams))


@dataclass
class RawSecondBar:
    symbol: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    taker_buy_quote_volume: float

    @property
    def close_time(self) -> int:
        return self.open_time + 999

    def update(self, *, price: float, quantity: float, taker_buy: bool) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += quantity
        quote = price * quantity
        self.quote_volume += quote
        if taker_buy:
            self.taker_buy_quote_volume += quote


class RawSecondBarCache:
    """Maintain a compact latest-second cache beside the raw gzip feed."""

    def __init__(self, *, window_seconds: int = 1200) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self._bars: dict[str, dict[int, RawSecondBar]] = {}
        self._latest_open_time: dict[str, int] = {}
        self._last_symbol_prune_open_time: dict[str, int] = {}
        self._global_latest_open_time: int | None = None
        self._last_global_prune_open_time: int | None = None
        self.latest_event_time_ms: int | None = None
        self.updated_at_ns: int | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, window_seconds: int | None = None) -> "RawSecondBarCache":
        cache = cls(window_seconds=window_seconds or _int_or_none(payload.get("window_seconds")) or 1200)
        updated_at_ns = _int_or_none(payload.get("updated_at_ns"))
        cache.updated_at_ns = updated_at_ns
        cache.latest_event_time_ms = _int_or_none(payload.get("latest_event_time_ms"))
        symbols = payload.get("symbols")
        if not isinstance(symbols, Mapping):
            return cache
        for raw_symbol, raw_bars in symbols.items():
            symbol = str(raw_symbol).upper()
            if not isinstance(raw_bars, list):
                continue
            by_time = cache._bars.setdefault(symbol, {})
            for item in raw_bars:
                if not isinstance(item, Mapping):
                    continue
                bar = _second_bar_from_payload(symbol, item)
                if bar is None:
                    continue
                by_time[bar.open_time] = bar
            if by_time:
                latest = max(by_time)
                cache._latest_open_time[symbol] = latest
                cache._global_latest_open_time = max(cache._global_latest_open_time or latest, latest)
                inferred_event_time = max(bar.close_time for bar in by_time.values())
                cache.latest_event_time_ms = max(cache.latest_event_time_ms or inferred_event_time, inferred_event_time)
        cache._prune_globally(force=True)
        return cache

    @classmethod
    def load_json(cls, path: str | Path, *, window_seconds: int = 1200) -> "RawSecondBarCache":
        input_path = Path(path)
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls(window_seconds=window_seconds)
        if not isinstance(payload, Mapping):
            return cls(window_seconds=window_seconds)
        return cls.from_dict(payload, window_seconds=window_seconds)

    def ingest_combined_message(self, message: Mapping[str, Any] | str | bytes) -> bool:
        if isinstance(message, bytes) and b"trade" not in message:
            return False
        if isinstance(message, str) and "trade" not in message:
            return False
        payload = _json_payload(message)
        if not isinstance(payload, Mapping):
            return False
        data = payload.get("data")
        item = data if isinstance(data, Mapping) else payload
        event_type = str(item.get("e") or item.get("eventType") or "").lower()
        if event_type != "trade":
            return False
        symbol = str(item.get("s") or item.get("symbol") or "").upper()
        if not symbol:
            return False
        price = _float_or_none(item.get("p") or item.get("price"))
        quantity = _float_or_none(item.get("q") or item.get("quantity"))
        event_time = _int_or_none(item.get("T") or item.get("E") or item.get("time"))
        if price is None or quantity is None or event_time is None or price <= 0 or quantity <= 0:
            return False
        # Binance trade payload m=true means buyer is maker, so the taker was sell.
        taker_buy = not bool(item.get("m"))
        self.ingest_trade(
            symbol=symbol,
            event_time_ms=event_time,
            price=price,
            quantity=quantity,
            taker_buy=taker_buy,
        )
        return True

    def ingest_trade(
        self,
        *,
        symbol: str,
        event_time_ms: int,
        price: float,
        quantity: float,
        taker_buy: bool,
    ) -> None:
        normalized_symbol = symbol.upper()
        open_time = int(event_time_ms // 1000 * 1000)
        by_time = self._bars.setdefault(normalized_symbol, {})
        bar = by_time.get(open_time)
        if bar is None:
            quote = price * quantity
            bar = RawSecondBar(
                symbol=normalized_symbol,
                open_time=open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=quantity,
                quote_volume=quote,
                taker_buy_quote_volume=quote if taker_buy else 0.0,
            )
            by_time[open_time] = bar
        else:
            bar.update(price=price, quantity=quantity, taker_buy=taker_buy)
        prior_latest = self._latest_open_time.get(normalized_symbol)
        latest = max(prior_latest or open_time, open_time)
        self._latest_open_time[normalized_symbol] = latest
        if prior_latest is None or latest > prior_latest:
            last_prune = self._last_symbol_prune_open_time.get(normalized_symbol)
            prune_interval = min(_SYMBOL_PRUNE_INTERVAL_MS, self.window_seconds * 1000)
            if last_prune is None or latest - last_prune >= prune_interval:
                self._prune_symbol(normalized_symbol, latest=latest)
        if self._global_latest_open_time is None or open_time > self._global_latest_open_time:
            self._global_latest_open_time = open_time
            self._prune_globally()
        self.latest_event_time_ms = max(self.latest_event_time_ms or event_time_ms, event_time_ms)
        self.updated_at_ns = time.time_ns()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_raw_feed_second_bars_v1",
            "updated_at_ns": self.updated_at_ns,
            "updated_at_ms": int(self.updated_at_ns // 1_000_000) if self.updated_at_ns else None,
            "latest_event_time_ms": self.latest_event_time_ms,
            "window_seconds": self.window_seconds,
            "symbols": {
                symbol: [
                    {
                        "open_time": bar.open_time,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "quote_volume": bar.quote_volume,
                        "taker_buy_quote_volume": bar.taker_buy_quote_volume,
                    }
                    for bar in by_time.values()
                ]
                for symbol, by_time in sorted(self._bars.items())
                if by_time
            },
        }

    def write_json(self, path: str | Path) -> None:
        write_raw_second_cache_payload(path, self.to_dict())

    def _prune_symbol(self, symbol: str, *, latest: int) -> None:
        by_time = self._bars.get(symbol)
        if not by_time:
            return
        cutoff = latest - self.window_seconds * 1000
        for key in [key for key in by_time if key < cutoff]:
            del by_time[key]
        self._last_symbol_prune_open_time[symbol] = latest

    def _prune_globally(self, *, force: bool = False) -> None:
        latest = self._global_latest_open_time
        if latest is None:
            return
        if not force and self._last_global_prune_open_time is not None:
            if latest - self._last_global_prune_open_time < _GLOBAL_PRUNE_INTERVAL_MS:
                return
        cutoff = latest - self.window_seconds * 1000
        for symbol, by_time in list(self._bars.items()):
            for key in [key for key in by_time if key < cutoff]:
                del by_time[key]
            if not by_time:
                del self._bars[symbol]
                self._latest_open_time.pop(symbol, None)
                self._last_symbol_prune_open_time.pop(symbol, None)
                continue
            symbol_latest = max(by_time)
            self._latest_open_time[symbol] = symbol_latest
            self._last_symbol_prune_open_time[symbol] = symbol_latest
        self._last_global_prune_open_time = latest


def write_raw_second_cache_payload(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, output)


def normalize_symbols(raw_symbols: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw_symbols, str):
        values = raw_symbols.split(",")
    else:
        values = list(raw_symbols)
    symbols = tuple(symbol.strip().upper() for symbol in values if symbol.strip())
    if not symbols:
        raise ValueError("at least one symbol is required")
    return symbols


def raw_feed_line(message: Mapping[str, Any] | str | bytes, *, local_timestamp_ns: int | None = None) -> str:
    timestamp = int(local_timestamp_ns if local_timestamp_ns is not None else time.time_ns())
    if isinstance(message, bytes):
        payload = message.decode("utf-8")
    elif isinstance(message, str):
        payload = message
    else:
        payload = json.dumps(message, separators=(",", ":"), sort_keys=True)
    return f"{timestamp} {payload}\n"


def append_raw_feed_line(path: str | Path, message: Mapping[str, Any] | str | bytes, *, local_timestamp_ns: int | None = None) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "at", encoding="utf-8") as handle:
        handle.write(raw_feed_line(message, local_timestamp_ns=local_timestamp_ns))


def _json_payload(message: Mapping[str, Any] | str | bytes) -> Any:
    if isinstance(message, Mapping):
        return message
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    try:
        return json.loads(message)
    except json.JSONDecodeError:
        return None


def _second_bar_from_payload(symbol: str, item: Mapping[str, Any]) -> RawSecondBar | None:
    open_time = _int_or_none(item.get("open_time"))
    open_price = _float_or_none(item.get("open"))
    high = _float_or_none(item.get("high"))
    low = _float_or_none(item.get("low"))
    close = _float_or_none(item.get("close"))
    if open_time is None or open_price is None or high is None or low is None or close is None:
        return None
    return RawSecondBar(
        symbol=symbol.upper(),
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=_float_or_none(item.get("volume")) or 0.0,
        quote_volume=_float_or_none(item.get("quote_volume")) or 0.0,
        taker_buy_quote_volume=_float_or_none(item.get("taker_buy_quote_volume")) or 0.0,
    )


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
