"""Public Binance USD-M futures WebSocket stream utilities."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import quote

from bfa.market.models import NormalizedMarketSnapshot


_BLOCKED_STREAM_MARKERS = (
    "listenkey",
    "userdata",
    "account",
    "order",
    "/private",
    "private/",
)


def ticker_stream(symbol: str) -> str:
    return f"{_stream_symbol(symbol)}@ticker"


def kline_stream(symbol: str, interval: str) -> str:
    return f"{_stream_symbol(symbol)}@kline_{_require_text('interval', interval)}"


def mark_price_stream(symbol: str) -> str:
    return f"{_stream_symbol(symbol)}@markPrice"


def book_ticker_stream(symbol: str) -> str:
    return f"{_stream_symbol(symbol)}@bookTicker"


def combined_stream_url(base_url: str, streams: list[str] | tuple[str, ...]) -> str:
    clean_streams = [validate_public_stream(stream) for stream in streams]
    if not clean_streams:
        raise ValueError("at least one stream is required")
    stream_path = "/".join(quote(stream, safe="@_") for stream in clean_streams)
    return f"{_base(base_url)}/stream?streams={stream_path}"


def raw_stream_url(base_url: str, stream: str) -> str:
    clean_stream = validate_public_stream(stream)
    return f"{_base(base_url)}/ws/{quote(clean_stream, safe='@_')}"


def validate_public_stream(stream: str) -> str:
    cleaned = _require_text("stream", stream)
    lowered = cleaned.lower()
    if any(marker in lowered for marker in _BLOCKED_STREAM_MARKERS):
        raise ValueError("private, account, and trading streams are not allowed")
    return cleaned


def parse_market_stream_message(
    message: Mapping[str, Any] | str | bytes,
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    payload = _coerce_message(message)
    _reject_private_payload(payload)

    stream = payload.get("stream")
    event_payload = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(event_payload, Mapping):
        raise ValueError("websocket message must contain a JSON object")

    event_name = str(event_payload.get("e", ""))
    event_time = event_payload.get("E")
    symbol = _extract_symbol(event_payload, stream=stream)
    normalized_payload = _payload_for_event(event_name, event_payload)
    if isinstance(stream, str):
        normalized_payload["stream"] = validate_public_stream(stream)

    return NormalizedMarketSnapshot(
        source="binance_usdm",
        event_type=_event_type(event_name),
        symbol=symbol,
        event_time=event_time,
        received_at=received_at,
        payload=normalized_payload,
    )


def next_reconnect_delay(
    attempt: int,
    *,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
) -> float:
    if attempt < 0:
        raise ValueError("attempt must be non-negative")
    if initial_delay <= 0:
        raise ValueError("initial_delay must be positive")
    if max_delay <= 0:
        raise ValueError("max_delay must be positive")
    return min(max_delay, initial_delay * (2**attempt))


def _stream_symbol(symbol: str) -> str:
    return _require_text("symbol", symbol).lower()


def _base(base_url: str) -> str:
    return _require_text("base_url", base_url).rstrip("/")


def _require_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def _coerce_message(message: Mapping[str, Any] | str | bytes) -> Mapping[str, Any]:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        loaded = json.loads(message)
        if not isinstance(loaded, Mapping):
            raise ValueError("websocket message must decode to a JSON object")
        return loaded
    return message


def _reject_private_payload(payload: Mapping[str, Any]) -> None:
    keys_and_values = " ".join(str(item).lower() for item in payload.keys())
    event_name = str(payload.get("e", "")).lower()
    if any(marker in keys_and_values for marker in _BLOCKED_STREAM_MARKERS):
        raise ValueError("private websocket payloads are not allowed")
    if "account" in event_name or "order" in event_name:
        raise ValueError("private websocket payloads are not allowed")


def _extract_symbol(event_payload: Mapping[str, Any], *, stream: Any) -> str:
    symbol = event_payload.get("s")
    if not symbol and isinstance(event_payload.get("k"), Mapping):
        symbol = event_payload["k"].get("s")
    if not symbol and isinstance(stream, str) and "@" in stream:
        symbol = stream.split("@", 1)[0].upper()
    return str(symbol or "UNKNOWN").upper()


def _event_type(event_name: str) -> str:
    if event_name == "24hrTicker":
        return "ws_ticker"
    if event_name == "kline":
        return "ws_kline"
    if event_name == "markPriceUpdate":
        return "ws_mark_price"
    if event_name == "bookTicker":
        return "ws_book_ticker"
    return "ws_unknown"


def _payload_for_event(event_name: str, event_payload: Mapping[str, Any]) -> dict[str, Any]:
    if event_name == "24hrTicker":
        return {
            "event_name": event_name,
            "price_change": event_payload.get("p"),
            "price_change_percent": event_payload.get("P"),
            "last_price": event_payload.get("c"),
            "volume": event_payload.get("v"),
            "quote_volume": event_payload.get("q"),
        }
    if event_name == "kline":
        kline = event_payload.get("k")
        if not isinstance(kline, Mapping):
            raise ValueError("kline event missing kline payload")
        return {
            "event_name": event_name,
            "open_time": kline.get("t"),
            "close_time": kline.get("T"),
            "interval": kline.get("i"),
            "open": kline.get("o"),
            "close": kline.get("c"),
            "high": kline.get("h"),
            "low": kline.get("l"),
            "volume": kline.get("v"),
            "closed": kline.get("x"),
        }
    if event_name == "markPriceUpdate":
        return {
            "event_name": event_name,
            "mark_price": event_payload.get("p"),
            "index_price": event_payload.get("i"),
            "funding_rate": event_payload.get("r"),
            "next_funding_time": event_payload.get("T"),
        }
    if event_name == "bookTicker":
        return {
            "event_name": event_name,
            "update_id": event_payload.get("u"),
            "transaction_time": event_payload.get("T"),
            "best_bid_price": event_payload.get("b"),
            "best_bid_qty": event_payload.get("B"),
            "best_ask_price": event_payload.get("a"),
            "best_ask_qty": event_payload.get("A"),
        }
    return {
        "event_name": event_name or "unknown",
        "raw": dict(event_payload),
    }
