"""Public Binance USD-M futures WebSocket stream utilities."""

from __future__ import annotations

from urllib.parse import quote


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


def _stream_symbol(symbol: str) -> str:
    return _require_text("symbol", symbol).lower()


def _base(base_url: str) -> str:
    return _require_text("base_url", base_url).rstrip("/")


def _require_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned
