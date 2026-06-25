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

LimitRangeFoldRunner wraps ``run_portfolio_backtest`` from
scripts/run_limit_range_research.py (the rhythm range-reversion core on 1m
klines). The script already applies a true signal-time ``min_reward_cost_ratio``
gate, so grid knobs map onto existing ``RhythmProfile`` fields without editing
the 4400-line script. Funding (rare for minute-scale holds) is applied per trade
on top of the script's net via :class:`CostModel`.

MicroGridFoldRunner wraps ``generate_symbol_candidate_trades`` from
scripts/run_micro_grid_research.py (the aggTrades tick-precise core). The
script's signal-time ``min_reward_cost_ratio`` gate maps directly to
``MicroGridProfile.min_reward_cost_ratio``; the spike target/stop knobs map onto
the dynamic spike-depth fields. Funding is applied per trade on top.
"""

from __future__ import annotations

import bisect
import importlib.util
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
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
        # cache once per (split, start_ms, end_ms) because grid search calls
        # the same fold many times with different params
        self._bars_cache: dict[tuple[str, int, int], dict[str, list[BacktestBar]]] = {}

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
        cache_key = (split, start_ms, end_ms)
        bars = self._bars_cache.get(cache_key)
        if bars is None:
            symbols = [s for s in range.symbols if s in self.bars_by_symbol]
            bars = {s: self.bars_by_symbol[s] for s in symbols}
            self._bars_cache[cache_key] = bars
        else:
            symbols = list(bars.keys())
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


# ---------------------------------------------------------------------------
# Research-script loading
#
# run_limit_range_research.py and run_micro_grid_research.py live in scripts/
# and are not importable packages. They are loaded via importlib, mirroring the
# pattern in tests/test_limit_range_research_script.py and
# tests/test_micro_grid_research_script.py. The scripts insert SCRIPT_DIR into
# sys.path themselves, so cross-script imports resolve. Loaded once and cached
# on the module dict keyed by name so re-imports are cheap.
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def _load_research_module(name: str, filename: str):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = _SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _filter_bars_by_ms(
    bars_by_symbol: dict[str, list[BacktestBar]],
    symbols: tuple[str, ...],
    start_ms: int,
    end_ms: int,
) -> dict[str, list[BacktestBar]]:
    out: dict[str, list[BacktestBar]] = {}
    for sym in symbols:
        src = bars_by_symbol.get(sym)
        if not src:
            continue
        filtered = [
            bar
            for bar in src
            if start_ms <= bar.open_time <= end_ms
        ]
        if filtered:
            out[sym] = filtered
    return out


# ---------------------------------------------------------------------------
# LimitRangeFoldRunner
# ---------------------------------------------------------------------------

# Geometry grid knob -> RhythmProfile field overrides.
# "a" keeps the script defaults; "b" widens the target and tightens the stop
# so the leg is rewarded for letting reversions run further.
_LIMIT_RANGE_GEOMETRY: dict[str, dict[str, float]] = {
    "a": {},
    "b": {"target_range_fraction": 0.62, "stop_outside_fraction": 0.12},
}


class LimitRangeFoldRunner:
    """Run one fold of the limit-range leg over pre-loaded 1m klines."""

    def __init__(
        self,
        *,
        cost_model: CostModel,
        bars_by_symbol: dict[str, list[BacktestBar]],
        funding_rates_by_symbol: dict[str, list[tuple[int, float]]],
        initial_capital: float = 30.0,
        max_open_positions: int = 2,
        max_new_entries_per_minute: int = 1,
        risk_per_trade_fraction: float = 0.01,
        max_notional_fraction: float = 0.5,
        scan_stride: int = 1,
        profile_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.cost_model = cost_model
        self.bars_by_symbol = bars_by_symbol
        self.funding_rates_by_symbol = funding_rates_by_symbol
        self.initial_capital = initial_capital
        self.max_open_positions = max_open_positions
        self.max_new_entries_per_minute = max_new_entries_per_minute
        self.risk_per_trade_fraction = risk_per_trade_fraction
        self.max_notional_fraction = max_notional_fraction
        self.scan_stride = scan_stride
        self.profile_overrides = dict(profile_overrides or {})
        self._bars_cache: dict[tuple[str, int, int], dict[str, list[BacktestBar]]] = {}
        self._research = _load_research_module(
            "limit_range_research", "run_limit_range_research.py"
        )

    def _build_profile(self, params: dict[str, Any]):
        base = self._research.RhythmProfile()
        overrides = dict(self.profile_overrides)
        if "min_reward_cost_ratio" in params:
            overrides["min_reward_cost_ratio"] = params["min_reward_cost_ratio"]
        geometry = params.get("target_stop_geometry", "a")
        overrides.update(_LIMIT_RANGE_GEOMETRY.get(geometry, {}))
        return replace(base, **overrides)

    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult:
        start_ms, end_ms = _month_bounds_ms(range, split)
        cache_key = (split, start_ms, end_ms)
        bars = self._bars_cache.get(cache_key)
        if bars is None:
            bars = _filter_bars_by_ms(self.bars_by_symbol, range.symbols, start_ms, end_ms)
            self._bars_cache[cache_key] = bars
        profile = self._build_profile(params)
        result = self._research.run_portfolio_backtest(
            bars,
            profile=profile,
            initial_capital=self.initial_capital,
            max_open_positions=self.max_open_positions,
            max_new_entries_per_minute=self.max_new_entries_per_minute,
            risk_per_trade_fraction=self.risk_per_trade_fraction,
            max_notional_fraction=self.max_notional_fraction,
        )
        # front-end candidate flow: evaluated_windows -> signals -> rejections
        front = self._research.scan_signal_diagnostics(
            bars, profile=profile, stride=self.scan_stride
        )

        trades_out: list[dict[str, Any]] = []
        funding_total = 0.0
        for trade in result["trades"]:
            entry_time_ms = _iso_to_ms(trade["entry_time"])
            exit_time_ms = _iso_to_ms(trade["exit_time"])
            funding = self.cost_model.funding_cost_usdt(
                trade["symbol"], entry_time_ms=entry_time_ms, exit_time_ms=exit_time_ms,
                side=trade["side"], notional=trade["notional_usdt"],
                funding_rates=self.funding_rates_by_symbol.get(trade["symbol"], []),
            )
            verdict_net = trade["net_pnl_usdt"] - funding
            funding_total += funding
            d = dict(trade)
            d["funding_cost_usdt"] = round(funding, 8)
            d["net_pnl_usdt"] = round(verdict_net, 8)
            trades_out.append(d)

        accounting = {
            "trade_count": len(result["trades"]),
            "order_stats": result["order_stats"],
            "signal_diagnostics": front,
            "symbols_evaluated": sorted(bars.keys()),
        }
        return FoldResult(
            leg="limit_range", fold_id=_fold_id(range, split), split=split,
            trades=trades_out, candidate_accounting=accounting,
            funding_paid=round(funding_total, 8), params=dict(params),
        )


# ---------------------------------------------------------------------------
# MicroGridFoldRunner
# ---------------------------------------------------------------------------

# wick_depth_gate knob -> spike_depth_min_percent value.
# "current" keeps the script default (0.15); "strict" raises the dead-market
# floor so only the deepest recent wicks qualify for a passive entry.
_MICRO_WICK_DEPTH = {
    "current": 0.15,
    "strict": 0.45,
}


class MicroGridFoldRunner:
    """Run one fold of the micro-grid leg over pre-loaded 1-second bars.

    Data feed: aggTrades aggregated to continuous 1-second ``BacktestBar``s
    (loaded upstream via ``load_symbol_seconds`` from the aggTrades cache) plus
    an optional ``TickReplaySource`` for tick-precise fill simulation. The
    script's signal-time ``min_reward_cost_ratio`` gate is the spec's reward/cost
    knob; ``target_fraction`` maps to ``spike_depth_target_fraction``;
    ``wick_depth_gate`` maps to ``spike_depth_min_percent``.
    """

    _WICK_DEPTH_CURRENT = _MICRO_WICK_DEPTH["current"]

    def __init__(
        self,
        *,
        cost_model: CostModel,
        seconds_by_symbol: dict[str, list[BacktestBar]],
        funding_rates_by_symbol: dict[str, list[tuple[int, float]]],
        tick_sources_by_symbol: dict[str, Any] | None = None,
        max_candidate_trades: int = 0,
        profile_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.cost_model = cost_model
        self.seconds_by_symbol = seconds_by_symbol
        self.funding_rates_by_symbol = funding_rates_by_symbol
        self.tick_sources_by_symbol = tick_sources_by_symbol or {}
        self.max_candidate_trades = max_candidate_trades
        self.profile_overrides = dict(profile_overrides or {})
        self._seconds_cache: dict[tuple[str, int, int], list[BacktestBar]] = {}
        self._research = _load_research_module(
            "micro_grid_research", "run_micro_grid_research.py"
        )

    def _build_profile(self, params: dict[str, Any]):
        base = self._research.MicroGridProfile()
        overrides = dict(self.profile_overrides)
        if "min_reward_cost_ratio" in params:
            overrides["min_reward_cost_ratio"] = params["min_reward_cost_ratio"]
        if "target_fraction" in params:
            overrides["spike_depth_target_fraction"] = params["target_fraction"]
        gate = params.get("wick_depth_gate", "current")
        if gate in _MICRO_WICK_DEPTH:
            overrides["spike_depth_min_percent"] = _MICRO_WICK_DEPTH[gate]
        return replace(base, **overrides)

    def _slice_seconds(self, symbol: str, start_ms: int, end_ms: int) -> list[BacktestBar]:
        src = self.seconds_by_symbol.get(symbol)
        if not src:
            return []
        # src is sorted by open_time; bisect to the window once and cache
        open_times = [b.open_time for b in src]
        lo = bisect.bisect_left(open_times, start_ms)
        hi = bisect.bisect_right(open_times, end_ms, lo=lo)
        return src[lo:hi]

    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult:
        start_ms, end_ms = _month_bounds_ms(range, split)
        profile = self._build_profile(params)
        all_trades: list[dict[str, Any]] = []
        agg_diagnostics: dict[str, Any] = {}
        agg_order_stats: dict[str, Any] = {}
        funding_total = 0.0
        symbols_evaluated: list[str] = []

        for sym in range.symbols:
            cache_key = (sym, start_ms, end_ms)
            seconds = self._seconds_cache.get(cache_key)
            if seconds is None:
                seconds = self._slice_seconds(sym, start_ms, end_ms)
                self._seconds_cache[cache_key] = seconds
            if not seconds:
                continue
            symbols_evaluated.append(sym)
            tick_source = self.tick_sources_by_symbol.get(sym)
            trades, diagnostics, order_stats = self._research.generate_symbol_candidate_trades(
                sym, seconds, tick_source=tick_source, profile=profile,
                max_candidate_trades=self.max_candidate_trades,
            )
            self._merge_accounting(agg_diagnostics, diagnostics)
            self._merge_accounting(agg_order_stats, order_stats)
            for trade in trades:
                d = trade.to_dict()
                entry_time_ms = _iso_to_ms(d["entry_time"])
                exit_time_ms = _iso_to_ms(d["exit_time"])
                funding = self.cost_model.funding_cost_usdt(
                    sym, entry_time_ms=entry_time_ms, exit_time_ms=exit_time_ms,
                    side=d["side"], notional=d["notional_usdt"],
                    funding_rates=self.funding_rates_by_symbol.get(sym, []),
                )
                verdict_net = d["net_pnl_usdt"] - funding
                funding_total += funding
                d["funding_cost_usdt"] = round(funding, 8)
                d["net_pnl_usdt"] = round(verdict_net, 8)
                all_trades.append(d)

        accounting = {
            "trade_count": len(all_trades),
            "diagnostics": agg_diagnostics,
            "order_stats": agg_order_stats,
            "symbols_evaluated": sorted(symbols_evaluated),
        }
        return FoldResult(
            leg="micro", fold_id=_fold_id(range, split), split=split,
            trades=all_trades, candidate_accounting=accounting,
            funding_paid=round(funding_total, 8), params=dict(params),
        )

    @staticmethod
    def _merge_accounting(agg: dict[str, Any], extra: dict[str, Any]) -> None:
        for key, value in extra.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                agg[key] = agg.get(key, 0) + value
            elif isinstance(value, dict):
                bucket = agg.setdefault(key, {})
                for k2, v2 in value.items():
                    if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                        bucket[k2] = bucket.get(k2, 0) + v2
                    else:
                        bucket.setdefault(k2, v2)
            else:
                agg.setdefault(key, value)
