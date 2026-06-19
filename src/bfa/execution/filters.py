"""Binance symbol filter parsing and quantization."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

from bfa.market.models import ExchangeSymbol, parse_exchange_symbols


@dataclass(frozen=True)
class FilteredOrderValues:
    quantity: float
    entry_price: float
    stop_price: float
    target_price: float
    notional_usdt: float
    rejection_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "notional_usdt": self.notional_usdt,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class SymbolExecutionFilters:
    symbol: str
    tick_size: Decimal | None = None
    step_size: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    min_notional: Decimal | None = None

    @classmethod
    def from_exchange_info(
        cls,
        payload: Mapping[str, Any],
        symbol: str,
    ) -> "SymbolExecutionFilters":
        target = symbol.upper()
        for item in parse_exchange_symbols(payload):
            if item.symbol.upper() == target:
                return cls.from_exchange_symbol(item)
        raise ValueError(f"symbol {target} not found in exchange info")

    @classmethod
    def from_exchange_symbol(cls, symbol: ExchangeSymbol) -> "SymbolExecutionFilters":
        price_filter = symbol.filters.get("PRICE_FILTER")
        lot_filter = symbol.filters.get("MARKET_LOT_SIZE") or symbol.filters.get("LOT_SIZE")
        min_notional = symbol.min_notional
        return cls(
            symbol=symbol.symbol.upper(),
            tick_size=_decimal_or_none(price_filter.values.get("tickSize") if price_filter else None),
            step_size=_decimal_or_none(lot_filter.values.get("stepSize") if lot_filter else None),
            min_qty=_decimal_or_none(lot_filter.values.get("minQty") if lot_filter else None),
            max_qty=_decimal_or_none(lot_filter.values.get("maxQty") if lot_filter else None),
            min_notional=_decimal_or_none(min_notional),
        )

    def apply(
        self,
        *,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> FilteredOrderValues:
        q = _round_down(Decimal(str(quantity)), self.step_size)
        entry = _round_down(Decimal(str(entry_price)), self.tick_size)
        stop = _round_down(Decimal(str(stop_price)), self.tick_size)
        target = _round_down(Decimal(str(target_price)), self.tick_size)
        notional = q * entry

        reasons: list[str] = []
        if self.min_qty is not None and q < self.min_qty:
            reasons.append("quantity_below_min")
        if self.max_qty is not None and q > self.max_qty:
            reasons.append("quantity_above_max")
        if self.min_notional is not None and notional < self.min_notional:
            reasons.append("notional_below_min")
        if q <= 0:
            reasons.append("quantity_not_positive")
        if min(entry, stop, target) <= 0:
            reasons.append("price_not_positive")

        return FilteredOrderValues(
            quantity=float(q),
            entry_price=float(entry),
            stop_price=float(stop),
            target_price=float(target),
            notional_usdt=float(notional),
            rejection_reasons=_dedupe(reasons),
        )


def _round_down(value: Decimal, increment: Decimal | None) -> Decimal:
    if increment is None or increment <= 0:
        return value
    units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
    return units * increment


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    if parsed <= 0:
        return None
    return parsed


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
