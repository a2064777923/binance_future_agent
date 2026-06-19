"""Market data models and parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class MarketDataResponse:
    endpoint: str
    params: dict[str, str]
    payload: Any
    status_code: int = 200
    headers: dict[str, str] | None = None

    @property
    def request_weight(self) -> str | None:
        if not self.headers:
            return None
        for key, value in self.headers.items():
            if key.upper().startswith("X-MBX-USED-WEIGHT"):
                return value
        return None


@dataclass(frozen=True)
class BinanceSymbolFilter:
    filter_type: str
    values: dict[str, str]


@dataclass(frozen=True)
class ExchangeSymbol:
    symbol: str
    status: str
    contract_type: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    filters: dict[str, BinanceSymbolFilter]

    @property
    def min_notional(self) -> str | None:
        for filter_name in ("MIN_NOTIONAL", "NOTIONAL"):
            symbol_filter = self.filters.get(filter_name)
            if symbol_filter:
                return symbol_filter.values.get("notional") or symbol_filter.values.get("minNotional")
        return None


@dataclass(frozen=True)
class NormalizedMarketSnapshot:
    source: str
    event_type: str
    symbol: str
    event_time: int | str | None
    received_at: int | str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "event_type": self.event_type,
            "symbol": self.symbol,
            "event_time": self.event_time,
            "received_at": self.received_at,
            "payload": self.payload,
        }


def parse_exchange_symbols(payload: Mapping[str, Any]) -> list[ExchangeSymbol]:
    raw_symbols = payload.get("symbols", [])
    if not isinstance(raw_symbols, list):
        raise ValueError("exchangeInfo payload must contain a symbols list")

    return [_parse_exchange_symbol(item) for item in raw_symbols if isinstance(item, Mapping)]


def _parse_exchange_symbol(item: Mapping[str, Any]) -> ExchangeSymbol:
    return ExchangeSymbol(
        symbol=str(item.get("symbol", "")),
        status=str(item.get("status", "")),
        contract_type=str(item.get("contractType", "")),
        base_asset=str(item.get("baseAsset", "")),
        quote_asset=str(item.get("quoteAsset", "")),
        margin_asset=str(item.get("marginAsset", "")),
        filters=_parse_filters(item.get("filters", [])),
    )


def _parse_filters(raw_filters: Any) -> dict[str, BinanceSymbolFilter]:
    filters: dict[str, BinanceSymbolFilter] = {}
    if not isinstance(raw_filters, list):
        return filters

    for raw_filter in raw_filters:
        if not isinstance(raw_filter, Mapping):
            continue
        filter_type = str(raw_filter.get("filterType", ""))
        if not filter_type:
            continue
        values = {str(key): str(value) for key, value in raw_filter.items() if key != "filterType"}
        filters[filter_type] = BinanceSymbolFilter(filter_type=filter_type, values=values)
    return filters
