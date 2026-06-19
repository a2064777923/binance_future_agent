"""Selected-symbol Binance USD-M market snapshot collector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bfa.market.models import MarketDataResponse, NormalizedMarketSnapshot
from bfa.market.normalize import (
    normalize_exchange_info,
    normalize_funding_rate,
    normalize_kline,
    normalize_open_interest,
    normalize_open_interest_hist,
    normalize_taker_buy_sell_volume,
    normalize_ticker_24h,
    normalize_top_long_short_position,
)


class MarketRestClient(Protocol):
    def exchange_info(self) -> MarketDataResponse: ...

    def ticker_24hr(self, symbol: str) -> MarketDataResponse: ...

    def klines(self, symbol: str, *, interval: str, limit: int) -> MarketDataResponse: ...

    def funding_rate(self, symbol: str, *, limit: int) -> MarketDataResponse: ...

    def open_interest(self, symbol: str) -> MarketDataResponse: ...

    def open_interest_hist(self, symbol: str, *, period: str, limit: int) -> MarketDataResponse: ...

    def top_long_short_position_ratio(
        self,
        symbol: str,
        *,
        period: str,
        limit: int,
    ) -> MarketDataResponse: ...

    def taker_buy_sell_volume(self, symbol: str, *, period: str, limit: int) -> MarketDataResponse: ...


@dataclass(frozen=True)
class MarketDataCollector:
    client: MarketRestClient
    symbols: list[str]
    interval: str = "5m"
    period: str = "5m"
    kline_limit: int = 30
    funding_limit: int = 20
    historical_limit: int = 30
    max_symbols: int = 10
    received_at: int | str = "now"

    def collect_rest_snapshots(self) -> list[NormalizedMarketSnapshot]:
        symbols = _normalize_symbols(self.symbols, max_symbols=self.max_symbols)
        snapshots = normalize_exchange_info(
            self.client.exchange_info().payload,
            received_at=self.received_at,
        )
        for symbol in symbols:
            snapshots.extend(self._collect_symbol(symbol))
        return snapshots

    def _collect_symbol(self, symbol: str) -> list[NormalizedMarketSnapshot]:
        snapshots: list[NormalizedMarketSnapshot] = []
        snapshots.append(
            normalize_ticker_24h(
                self.client.ticker_24hr(symbol).payload,
                received_at=self.received_at,
            )
        )
        for item in self.client.klines(symbol, interval=self.interval, limit=self.kline_limit).payload:
            snapshots.append(
                normalize_kline(
                    symbol,
                    item,
                    interval=self.interval,
                    received_at=self.received_at,
                )
            )
        for item in self.client.funding_rate(symbol, limit=self.funding_limit).payload:
            snapshots.append(normalize_funding_rate(item, received_at=self.received_at))
        snapshots.append(
            normalize_open_interest(
                self.client.open_interest(symbol).payload,
                received_at=self.received_at,
            )
        )
        for item in self.client.open_interest_hist(
            symbol,
            period=self.period,
            limit=self.historical_limit,
        ).payload:
            snapshots.append(normalize_open_interest_hist(item, received_at=self.received_at))
        for item in self.client.top_long_short_position_ratio(
            symbol,
            period=self.period,
            limit=self.historical_limit,
        ).payload:
            snapshots.append(normalize_top_long_short_position(item, received_at=self.received_at))
        for item in self.client.taker_buy_sell_volume(
            symbol,
            period=self.period,
            limit=self.historical_limit,
        ).payload:
            snapshots.append(normalize_taker_buy_sell_volume(item, symbol=symbol, received_at=self.received_at))
        return snapshots


def _normalize_symbols(symbols: list[str], *, max_symbols: int) -> list[str]:
    if max_symbols <= 0:
        raise ValueError("max_symbols must be positive")
    normalized = []
    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if symbol:
            normalized.append(symbol)
    if not normalized:
        raise ValueError("at least one market symbol is required")
    if len(normalized) > max_symbols:
        raise ValueError(f"market symbol count exceeds cap of {max_symbols}")
    return normalized
