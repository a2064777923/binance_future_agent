"""Per-leg fold runners for walk-forward validation.

Each adapter wraps an existing backtest engine/runner for one leg and exposes a
unified ``run_fold(range, split, params) -> FoldResult`` interface. The
orchestrator never inspects leg internals.

TrendFoldRunner wraps :func:`run_hot_momentum_backtest` (strategy_type=
quant_setup) with the ``quant_setup_live_action_flow`` family. It consumes the
engine's ``gross_pnl_usdt`` (which already includes the engine's taker-slippage
model) and applies the unified :class:`CostModel` on top: per-symbol fee-tier
correction + funding cost. This avoids refactoring engine.py internals (zero
regression risk) while still producing per-symbol-accurate, funding-inclusive
verdict PnL. Slippage is NOT re-subtracted (already inside gross), preventing
double-counting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from bfa.backtest.cost import CostModel
from bfa.backtest.engine import run_hot_momentum_backtest
from bfa.backtest.models import BacktestBar, BacktestConfig, built_in_variants


@dataclass(frozen=True)
class FoldRange:
    leg: str
    symbols: tuple[str, ...]
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class FoldResult:
    leg: str
    fold_id: str
    split: str
    trades: list[dict[str, Any]]
    candidate_accounting: dict[str, Any]
    funding_paid: float
    params: dict[str, Any]


class FoldRunner(Protocol):
    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult: ...


def _month_bounds_ms(range: FoldRange, split: str) -> tuple[int, int]:
    if split == "train":
        start = int(range.train_start.timestamp() * 1000)
        end = int(range.train_end.timestamp() * 1000)
    else:
        start = int(range.test_start.timestamp() * 1000)
        end = int(range.test_end.timestamp() * 1000)
    return start, end


def _iso_to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _fold_id(range: FoldRange, split: str) -> str:
    return f"{range.leg}_{split}_{range.test_start.strftime('%Y-%m')}"


class TrendFoldRunner:
    """Run one fold of the trend leg over pre-loaded bars + funding rates."""

    def __init__(
        self,
        *,
        cost_model: CostModel,
        variant_name: str = "quant_setup_live_action_flow",
        bars_by_symbol: dict[str, list[BacktestBar]],
        funding_rates_by_symbol: dict[str, list[tuple[int, float]]],
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.cost_model = cost_model
        self.variant_name = variant_name
        self.bars_by_symbol = bars_by_symbol
        self.funding_rates_by_symbol = funding_rates_by_symbol
        self.config_overrides = dict(config_overrides or {})

    def _build_config(self, params: dict[str, Any]) -> BacktestConfig:
        base = built_in_variants()[self.variant_name]
        profile = dict(base.setup_profile)
        # grid knobs map onto the setup profile
        if "min_post_cost_edge_ratio" in params:
            profile["min_post_cost_edge_ratio"] = params["min_post_cost_edge_ratio"]
        if "target_distance_multiplier" in params:
            profile["target_distance_multiplier"] = params["target_distance_multiplier"]
        if "stop_distance_multiplier" in params:
            profile["stop_distance_multiplier"] = params["stop_distance_multiplier"]
        overrides = {**self.config_overrides, "setup_profile": profile}
        return base.with_overrides(**overrides)

    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult:
        start_ms, end_ms = _month_bounds_ms(range, split)
        config = self._build_config(params)
        symbols = [s for s in range.symbols if s in self.bars_by_symbol]
        bars = {s: self.bars_by_symbol[s] for s in symbols}
        result = run_hot_momentum_backtest(bars, config, start_ms=start_ms, end_ms=end_ms)

        trades_out: list[dict[str, Any]] = []
        funding_total = 0.0
        for trade in result.trades:
            entry_time_ms = _iso_to_ms(trade.entry_time)
            exit_time_ms = _iso_to_ms(trade.exit_time)
            # per-symbol fee correction (trend = taker both legs)
            fees = self.cost_model.trade_fees_usdt(
                trade.symbol, entry_price=trade.entry_price, exit_price=trade.exit_price,
                qty=trade.quantity, entry_is_maker=False, exit_is_maker=False,
            )
            funding = self.cost_model.funding_cost_usdt(
                trade.symbol, entry_time_ms=entry_time_ms, exit_time_ms=exit_time_ms,
                side=trade.side, notional=trade.notional_usdt,
                funding_rates=self.funding_rates_by_symbol.get(trade.symbol, []),
            )
            # verdict net = engine gross (slip already inside) - per-symbol fees - funding
            verdict_net = trade.gross_pnl_usdt - fees - funding
            funding_total += funding
            d = trade.to_dict()
            d["fees_usdt"] = round(fees, 8)
            d["funding_cost_usdt"] = round(funding, 8)
            d["net_pnl_usdt"] = round(verdict_net, 8)
            trades_out.append(d)

        accounting = {
            "trade_count": len(result.trades),
            "rejected_signals": result.rejected_signals,
            "skipped_daily_loss_signals": result.skipped_daily_loss_signals,
            "skipped_concurrency_signals": result.skipped_concurrency_signals,
            "symbols_evaluated": sorted(symbols),
        }
        return FoldResult(
            leg="trend", fold_id=_fold_id(range, split), split=split,
            trades=trades_out, candidate_accounting=accounting,
            funding_paid=round(funding_total, 8), params=dict(params),
        )
