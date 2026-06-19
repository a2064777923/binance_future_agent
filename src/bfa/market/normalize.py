"""Normalize Binance USD-M market payloads into common snapshot records."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from bfa.market.models import NormalizedMarketSnapshot, parse_exchange_symbols


SOURCE = "binance_usdm"


def normalize_exchange_info(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> list[NormalizedMarketSnapshot]:
    event_time = payload.get("serverTime")
    snapshots: list[NormalizedMarketSnapshot] = []
    for symbol in parse_exchange_symbols(payload):
        snapshots.append(
            _snapshot(
                event_type="exchange_symbol",
                symbol=symbol.symbol,
                event_time=event_time,
                received_at=received_at,
                payload={
                    "status": symbol.status,
                    "contract_type": symbol.contract_type,
                    "base_asset": symbol.base_asset,
                    "quote_asset": symbol.quote_asset,
                    "margin_asset": symbol.margin_asset,
                    "filters": {
                        name: symbol_filter.values for name, symbol_filter in symbol.filters.items()
                    },
                },
            )
        )
    return snapshots


def normalize_ticker_24h(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="ticker_24h",
        symbol=_symbol(payload),
        event_time=payload.get("closeTime"),
        received_at=received_at,
        payload={
            "price_change": payload.get("priceChange"),
            "price_change_percent": payload.get("priceChangePercent"),
            "last_price": payload.get("lastPrice"),
            "volume": payload.get("volume"),
            "quote_volume": payload.get("quoteVolume"),
            "open_time": payload.get("openTime"),
            "close_time": payload.get("closeTime"),
        },
    )


def normalize_kline(
    symbol: str,
    payload: Sequence[Any],
    *,
    interval: str,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    if len(payload) < 11:
        raise ValueError("kline payload must contain at least 11 fields")
    return _snapshot(
        event_type="kline",
        symbol=symbol,
        event_time=payload[0],
        received_at=received_at,
        payload={
            "interval": _require_text("interval", interval),
            "open_time": payload[0],
            "open": payload[1],
            "high": payload[2],
            "low": payload[3],
            "close": payload[4],
            "volume": payload[5],
            "close_time": payload[6],
            "quote_volume": payload[7],
            "trade_count": payload[8],
            "taker_buy_base_volume": payload[9],
            "taker_buy_quote_volume": payload[10],
        },
    )


def normalize_funding_rate(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="funding_rate",
        symbol=_symbol(payload),
        event_time=payload.get("fundingTime"),
        received_at=received_at,
        payload={
            "funding_rate": payload.get("fundingRate"),
            "funding_time": payload.get("fundingTime"),
            "mark_price": payload.get("markPrice"),
        },
    )


def normalize_open_interest(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="open_interest",
        symbol=_symbol(payload),
        event_time=payload.get("time"),
        received_at=received_at,
        payload={
            "open_interest": payload.get("openInterest"),
            "time": payload.get("time"),
        },
    )


def normalize_open_interest_hist(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="open_interest_hist",
        symbol=_symbol(payload),
        event_time=payload.get("timestamp"),
        received_at=received_at,
        payload={
            "sum_open_interest": payload.get("sumOpenInterest"),
            "sum_open_interest_value": payload.get("sumOpenInterestValue"),
            "timestamp": payload.get("timestamp"),
        },
    )


def normalize_top_long_short_position(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="top_long_short_position",
        symbol=_symbol(payload),
        event_time=payload.get("timestamp"),
        received_at=received_at,
        payload={
            "long_short_ratio": payload.get("longShortRatio"),
            "long_account": payload.get("longAccount"),
            "short_account": payload.get("shortAccount"),
            "timestamp": payload.get("timestamp"),
        },
    )


def normalize_taker_buy_sell_volume(
    payload: Mapping[str, Any],
    *,
    received_at: int | str,
) -> NormalizedMarketSnapshot:
    return _snapshot(
        event_type="taker_buy_sell_volume",
        symbol=_symbol(payload),
        event_time=payload.get("timestamp"),
        received_at=received_at,
        payload={
            "buy_sell_ratio": payload.get("buySellRatio"),
            "buy_volume": payload.get("buyVol"),
            "sell_volume": payload.get("sellVol"),
            "timestamp": payload.get("timestamp"),
        },
    )


def _snapshot(
    *,
    event_type: str,
    symbol: str,
    event_time: int | str | None,
    received_at: int | str,
    payload: dict[str, Any],
) -> NormalizedMarketSnapshot:
    return NormalizedMarketSnapshot(
        source=SOURCE,
        event_type=event_type,
        symbol=_require_text("symbol", symbol).upper(),
        event_time=event_time,
        received_at=received_at,
        payload=payload,
    )


def _symbol(payload: Mapping[str, Any]) -> str:
    return _require_text("symbol", str(payload.get("symbol", "")))


def _require_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned
