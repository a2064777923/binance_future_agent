"""Multi-round hot-universe backtest matrix reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from bfa.backtest.data import fetch_historical_klines
from bfa.backtest.engine import run_staged_sweep
from bfa.backtest.models import BacktestBar, built_in_variants
from bfa.market.binance_rest import BinanceFuturesRestClient


DEFAULT_STABLE_BASES = {
    "BUSD",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDC",
    "USDP",
    "USDT",
}


@dataclass(frozen=True)
class HotUniverseConfig:
    top_n: int = 8
    min_quote_volume_usdt: float = 10_000_000.0
    min_abs_price_change_percent: float = 3.0
    exclude_stable_bases: frozenset[str] = frozenset(DEFAULT_STABLE_BASES)


@dataclass(frozen=True)
class BacktestMatrixConfig:
    intervals: tuple[str, ...] = ("5m", "15m")
    limit: int = 144
    window_bars: int = 72
    step_bars: int = 36
    variants: tuple[str, ...] = ("strict", "balanced", "aggressive")
    hot_universe: HotUniverseConfig = field(default_factory=HotUniverseConfig)


@dataclass(frozen=True)
class HotUniversePreset:
    name: str
    config: HotUniverseConfig


@dataclass(frozen=True)
class BacktestMatrixSuiteConfig:
    intervals: tuple[str, ...] = ("5m", "15m")
    limit: int = 144
    window_bars: int = 72
    step_bars: int = 36
    variants: tuple[str, ...] = (
        "quant_setup_selective",
        "quant_setup_selective_guarded",
        "quant_setup_loss_recalibrated",
    )
    universe_presets: tuple[str, ...] = ("broad", "momentum", "liquid")


def select_hot_usdt_symbols(
    ticker_rows: Iterable[dict[str, Any]],
    config: HotUniverseConfig | None = None,
) -> list[dict[str, Any]]:
    """Rank USDT perpetual candidates from Binance 24h ticker rows."""

    cfg = config or HotUniverseConfig()
    candidates: list[dict[str, Any]] = []
    for row in ticker_rows:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base in cfg.exclude_stable_bases:
            continue
        quote_volume = _float_value(row.get("quoteVolume"))
        price_change = _float_value(row.get("priceChangePercent"))
        trade_count = _int_value(row.get("count"))
        if quote_volume < cfg.min_quote_volume_usdt:
            continue
        if abs(price_change) < cfg.min_abs_price_change_percent:
            continue
        score = (abs(price_change) * 1_000_000.0) + quote_volume
        candidates.append(
            {
                "symbol": symbol,
                "price_change_percent": price_change,
                "quote_volume_usdt": quote_volume,
                "trade_count": trade_count,
                "score": round(score, 8),
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            float(item["score"]),
            float(item["quote_volume_usdt"]),
            str(item["symbol"]),
        ),
        reverse=True,
    )[: cfg.top_n]


def hot_universe_presets(names: Iterable[str]) -> list[HotUniversePreset]:
    presets = {
        "broad": HotUniversePreset(
            "broad",
            HotUniverseConfig(top_n=40, min_quote_volume_usdt=10_000_000.0, min_abs_price_change_percent=0.5),
        ),
        "momentum": HotUniversePreset(
            "momentum",
            HotUniverseConfig(top_n=24, min_quote_volume_usdt=10_000_000.0, min_abs_price_change_percent=3.0),
        ),
        "liquid": HotUniversePreset(
            "liquid",
            HotUniverseConfig(top_n=30, min_quote_volume_usdt=50_000_000.0, min_abs_price_change_percent=0.5),
        ),
    }
    selected: list[HotUniversePreset] = []
    unknown: list[str] = []
    for name in names:
        normalized = name.strip().lower()
        if not normalized:
            continue
        if normalized not in presets:
            unknown.append(normalized)
            continue
        selected.append(presets[normalized])
    if unknown:
        raise ValueError(f"unknown hot-universe presets: {', '.join(unknown)}")
    if not selected:
        raise ValueError("at least one hot-universe preset is required")
    return selected


def run_hot_backtest_matrix_suite(
    client: BinanceFuturesRestClient,
    config: BacktestMatrixSuiteConfig | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Run the hot-symbol matrix across multiple universe presets."""

    cfg = config or BacktestMatrixSuiteConfig()
    _validate_matrix_suite_config(cfg)
    matrices: list[dict[str, Any]] = []
    for preset in hot_universe_presets(cfg.universe_presets):
        matrix = run_hot_backtest_matrix(
            client,
            BacktestMatrixConfig(
                intervals=cfg.intervals,
                limit=cfg.limit,
                window_bars=cfg.window_bars,
                step_bars=cfg.step_bars,
                variants=cfg.variants,
                hot_universe=preset.config,
            ),
            start=start,
            end=end,
        )
        matrices.append(
            {
                "preset": preset.name,
                "symbols": matrix["symbols"],
                "hot_universe": matrix["hot_universe"],
                "matrix_config": matrix["matrix_config"],
                "reports": matrix["reports"],
                "promotion": matrix["promotion"],
            }
        )
    return {
        "schema": "bfa_hot_backtest_matrix_suite_v1",
        "suite_config": {
            "intervals": list(cfg.intervals),
            "limit": cfg.limit,
            "window_bars": cfg.window_bars,
            "step_bars": cfg.step_bars,
            "variants": list(cfg.variants),
            "universe_presets": list(cfg.universe_presets),
        },
        "matrices": matrices,
        "promotion": _suite_promotion_summary(matrices),
    }


def run_hot_backtest_matrix(
    client: BinanceFuturesRestClient,
    config: BacktestMatrixConfig | None = None,
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Fetch hot symbols and run staged sweeps across intervals."""

    cfg = config or BacktestMatrixConfig()
    _validate_matrix_config(cfg)
    hot_rows: list[dict[str, Any]] = []
    if symbols is None:
        ticker_response = client.ticker_24hr()
        ticker_payload = ticker_response.payload if isinstance(ticker_response.payload, list) else []
        hot_rows = select_hot_usdt_symbols(ticker_payload, cfg.hot_universe)
        selected_symbols = [str(item["symbol"]) for item in hot_rows]
    else:
        selected_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]

    if not selected_symbols:
        return _matrix_payload(
            selected_symbols=selected_symbols,
            hot_rows=hot_rows,
            config=cfg,
            source="binance_24h_ticker" if symbols is None else "manual_symbols",
            reports=[],
            promotion={"cells": [], "variants": {}, "overall": "no_symbols_selected"},
        )

    reports: list[dict[str, Any]] = []
    for interval in cfg.intervals:
        rows = fetch_historical_klines(
            client,
            symbols=selected_symbols,
            interval=interval,
            start=start,
            end=end,
            limit=cfg.limit,
        )
        sweep = run_staged_sweep(
            _bars_from_raw(rows),
            window_bars=cfg.window_bars,
            step_bars=cfg.step_bars,
            variants=cfg.variants,
        )
        reports.append(
            {
                "interval": interval,
                "bar_counts": {symbol: len(values) for symbol, values in sorted(rows.items())},
                "sweep": sweep,
            }
        )

    return _matrix_payload(
        selected_symbols=selected_symbols,
        hot_rows=hot_rows,
        config=cfg,
        source="binance_24h_ticker" if symbols is None else "manual_symbols",
        reports=reports,
        promotion=_promotion_summary(reports),
    )


def _matrix_payload(
    *,
    selected_symbols: list[str],
    hot_rows: list[dict[str, Any]],
    config: BacktestMatrixConfig,
    source: str,
    reports: list[dict[str, Any]],
    promotion: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "bfa_hot_backtest_matrix_v1",
        "symbols": selected_symbols,
        "hot_universe": {
            "source": source,
            "config": _hot_config_dict(config.hot_universe),
            "candidates": hot_rows,
        },
        "matrix_config": {
            "intervals": list(config.intervals),
            "limit": config.limit,
            "window_bars": config.window_bars,
            "step_bars": config.step_bars,
            "variants": list(config.variants),
        },
        "reports": reports,
        "promotion": promotion,
    }


def _bars_from_raw(rows_by_symbol: dict[str, list[Any]]) -> dict[str, list[BacktestBar]]:
    return {
        symbol.upper(): [BacktestBar.from_binance_kline(symbol, row) for row in rows]
        for symbol, rows in rows_by_symbol.items()
        if rows
    }


def _promotion_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        interval = report["interval"]
        sweep = report["sweep"]
        for variant, aggregate in sweep["aggregate"].items():
            verdict = sweep["interpretation"][variant]
            cell = {
                "interval": interval,
                "variant": variant,
                "verdict": verdict,
                "trade_count": aggregate["trade_count"],
                "net_pnl_usdt": aggregate["net_pnl_usdt"],
                "positive_window_rate": aggregate["positive_window_rate"],
                "worst_drawdown_usdt": aggregate["worst_drawdown_usdt"],
                "max_daily_loss_usdt": aggregate["max_daily_loss_usdt"],
            }
            cells.append(cell)
            by_variant.setdefault(variant, []).append(cell)

    variant_summary: dict[str, dict[str, Any]] = {}
    for variant, rows in sorted(by_variant.items()):
        candidate_cells = [row for row in rows if row["verdict"] == "candidate_for_forward_paper"]
        total_net = sum(float(row["net_pnl_usdt"]) for row in rows)
        worst_drawdown = max((float(row["worst_drawdown_usdt"]) for row in rows), default=0.0)
        variant_summary[variant] = {
            "interval_count": len(rows),
            "candidate_interval_count": len(candidate_cells),
            "total_net_pnl_usdt": round(total_net, 8),
            "worst_drawdown_usdt": round(worst_drawdown, 8),
            "verdict": _variant_verdict(rows, total_net, worst_drawdown),
        }

    return {
        "cells": cells,
        "variants": variant_summary,
        "overall": _overall_verdict(variant_summary),
    }


def _variant_verdict(rows: list[dict[str, Any]], total_net: float, worst_drawdown: float) -> str:
    if not rows:
        return "no_evidence"
    candidate_count = sum(1 for row in rows if row["verdict"] == "candidate_for_forward_paper")
    cap = min(float(row["max_daily_loss_usdt"]) for row in rows)
    if candidate_count == len(rows) and total_net > 0 and worst_drawdown < cap:
        return "candidate_for_forward_paper"
    if candidate_count > 0 and total_net > 0 and worst_drawdown < cap:
        return "mixed_candidate_collect_more_data"
    if worst_drawdown >= cap:
        return "drawdown_exceeds_pilot_cap"
    return "not_promoted"


def _overall_verdict(variant_summary: dict[str, dict[str, Any]]) -> str:
    if any(row["verdict"] == "candidate_for_forward_paper" for row in variant_summary.values()):
        return "candidate_for_forward_paper"
    if any(row["verdict"] == "mixed_candidate_collect_more_data" for row in variant_summary.values()):
        return "mixed_candidate_collect_more_data"
    if any(row["verdict"] == "drawdown_exceeds_pilot_cap" for row in variant_summary.values()):
        return "keep_caps_unchanged_drawdown_risk"
    return "keep_caps_unchanged"


def _suite_promotion_summary(matrices: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for matrix in matrices:
        preset = matrix["preset"]
        for variant, row in matrix["promotion"]["variants"].items():
            by_variant.setdefault(variant, []).append({"preset": preset, **row})

    variants: dict[str, dict[str, Any]] = {}
    for variant, rows in sorted(by_variant.items()):
        total_net = sum(float(row["total_net_pnl_usdt"]) for row in rows)
        worst_drawdown = max((float(row["worst_drawdown_usdt"]) for row in rows), default=0.0)
        candidate_count = sum(1 for row in rows if row["verdict"] == "candidate_for_forward_paper")
        mixed_count = sum(1 for row in rows if row["verdict"] == "mixed_candidate_collect_more_data")
        variants[variant] = {
            "matrix_count": len(rows),
            "candidate_matrix_count": candidate_count,
            "mixed_matrix_count": mixed_count,
            "total_net_pnl_usdt": round(total_net, 8),
            "worst_drawdown_usdt": round(worst_drawdown, 8),
            "verdict": _suite_variant_verdict(rows, total_net, candidate_count, mixed_count),
        }
    return {
        "variants": variants,
        "overall": _overall_verdict(variants),
    }


def _suite_variant_verdict(
    rows: list[dict[str, Any]],
    total_net: float,
    candidate_count: int,
    mixed_count: int,
) -> str:
    if not rows:
        return "no_evidence"
    if candidate_count == len(rows) and total_net > 0:
        return "candidate_for_forward_paper"
    if (candidate_count or mixed_count) and total_net > 0:
        return "mixed_candidate_collect_more_data"
    if any(row["verdict"] == "drawdown_exceeds_pilot_cap" for row in rows):
        return "drawdown_exceeds_pilot_cap"
    return "not_promoted"


def _validate_matrix_suite_config(config: BacktestMatrixSuiteConfig) -> None:
    _validate_matrix_config(
        BacktestMatrixConfig(
            intervals=config.intervals,
            limit=config.limit,
            window_bars=config.window_bars,
            step_bars=config.step_bars,
            variants=config.variants,
            hot_universe=HotUniverseConfig(),
        )
    )
    hot_universe_presets(config.universe_presets)


def _validate_matrix_config(config: BacktestMatrixConfig) -> None:
    if not config.intervals:
        raise ValueError("at least one interval is required")
    if config.limit <= 0:
        raise ValueError("limit must be positive")
    if config.window_bars <= 0:
        raise ValueError("window_bars must be positive")
    if config.step_bars <= 0:
        raise ValueError("step_bars must be positive")
    known = built_in_variants()
    unknown = [variant for variant in config.variants if variant not in known]
    if unknown:
        raise ValueError(f"unknown backtest variants: {', '.join(unknown)}")
    if config.hot_universe.top_n <= 0:
        raise ValueError("top_n must be positive")
    if config.hot_universe.min_quote_volume_usdt < 0:
        raise ValueError("min_quote_volume_usdt must be non-negative")
    if config.hot_universe.min_abs_price_change_percent < 0:
        raise ValueError("min_abs_price_change_percent must be non-negative")


def _hot_config_dict(config: HotUniverseConfig) -> dict[str, Any]:
    return {
        "top_n": config.top_n,
        "min_quote_volume_usdt": config.min_quote_volume_usdt,
        "min_abs_price_change_percent": config.min_abs_price_change_percent,
        "exclude_stable_bases": sorted(config.exclude_stable_bases),
    }


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
