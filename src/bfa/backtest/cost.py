"""Unified per-symbol cost model: fees + slippage + funding.

Single source of truth for trading costs across all backtest/validation legs.
Per-symbol fee tiers are loaded from a curated config seeded from Binance's
public USD-M fee schedule (default maker 2.0 / taker 4.0 bps). The structure
allows swapping the data source to an authenticated commissionRate snapshot
later without changing this interface.

Known limitation: the public schedule excludes the operator's VIP tier + BNB
discount, so OOS cost may diverge from live actuals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SymbolFeeTier:
    maker_fee_bps: float
    taker_fee_bps: float


def _default_tier() -> SymbolFeeTier:
    return SymbolFeeTier(maker_fee_bps=2.0, taker_fee_bps=4.0)


@dataclass(frozen=True)
class CostModel:
    fee_tiers: dict[str, SymbolFeeTier] = field(default_factory=dict)
    default_tier: SymbolFeeTier = field(default_factory=_default_tier)
    slippage_bps: float = 5.0
    maker_slippage_bps: float = 1.0
    funding_interval_hours: int = 8
    funding_on_long: bool = True

    def tier(self, symbol: str) -> SymbolFeeTier:
        return self.fee_tiers.get(symbol.upper(), self.default_tier)

    def _fee_bps(self, symbol: str, is_maker: bool) -> float:
        tier = self.tier(symbol)
        return tier.maker_fee_bps if is_maker else tier.taker_fee_bps

    def _slip_bps(self, is_maker: bool) -> float:
        return self.maker_slippage_bps if is_maker else self.slippage_bps

    def round_trip_cost_percent(self, symbol: str, *, entry_is_maker: bool, exit_is_maker: bool) -> float:
        """Round-trip cost as a percent of notional (fees + slippage, both legs)."""
        bps = (
            self._fee_bps(symbol, entry_is_maker)
            + self._fee_bps(symbol, exit_is_maker)
            + self._slip_bps(entry_is_maker)
            + self._slip_bps(exit_is_maker)
        )
        return bps / 100.0  # bps -> percent

    def trade_fees_usdt(self, symbol: str, *, entry_price: float, exit_price: float,
                        qty: float, entry_is_maker: bool, exit_is_maker: bool) -> float:
        entry_fee = entry_price * qty * (self._fee_bps(symbol, entry_is_maker) / 10_000.0)
        exit_fee = exit_price * qty * (self._fee_bps(symbol, exit_is_maker) / 10_000.0)
        return entry_fee + exit_fee

    def trade_slippage_usdt(self, symbol: str, *, ref_entry: float, ref_exit: float,
                            qty: float, entry_is_maker: bool, exit_is_maker: bool) -> float:
        entry_slip = ref_entry * qty * (self._slip_bps(entry_is_maker) / 10_000.0)
        exit_slip = ref_exit * qty * (self._slip_bps(exit_is_maker) / 10_000.0)
        return entry_slip + exit_slip

    def funding_cost_usdt(self, symbol: str, *, entry_time_ms: int, exit_time_ms: int,
                          side: str, notional: float,
                          funding_rates: list[tuple[int, float]]) -> float:
        """Accumulate funding payments for funding events in [entry_time, exit_time].

        Long pays positive rate / receives negative; short is the mirror.
        `funding_rates` is a sorted list of (time_ms, rate). Events outside the
        holding window are ignored.
        """
        side_sign = 1.0 if side == "long" else -1.0
        cost = 0.0
        for event_time, rate in funding_rates:
            if entry_time_ms <= event_time <= exit_time_ms:
                cost += side_sign * notional * rate
        return cost

    @classmethod
    def load_fee_tiers(cls, path: str | Path) -> "CostModel":
        p = Path(path)
        if not p.exists():
            return cls()
        payload = json.loads(p.read_text(encoding="utf-8"))
        tiers = {
            sym.upper(): SymbolFeeTier(maker_fee_bps=float(t["maker_fee_bps"]),
                                        taker_fee_bps=float(t["taker_fee_bps"]))
            for sym, t in payload.get("tiers", {}).items()
        }
        default = payload.get("default")
        default_tier = (
            SymbolFeeTier(maker_fee_bps=float(default["maker_fee_bps"]),
                          taker_fee_bps=float(default["taker_fee_bps"]))
            if default else _default_tier()
        )
        return cls(fee_tiers=tiers, default_tier=default_tier)
