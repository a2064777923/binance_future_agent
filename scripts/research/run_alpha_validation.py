"""Run alpha walk-forward validation and emit a verdict artifact.

Supports all three legs:
- trend: 5m klines + fundingRate monthly archives (Binance Vision or local CSV).
- limit_range: 1m klines (Binance Vision monthly or local CSV).
- micro: aggTrades-derived 1-second bars + tick replay (D:/教青垃圾系統/binance/aggTrades-cache).

Runs expanding-window walk-forward, grid-searches on train segments only,
evaluates the best combo on each test segment, and writes the per-leg verdict
JSON to data/research/alpha_validation/<leg>_verdict.json.

No live env, no secrets, no order placement. Pure validation.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
# scripts/ must be importable so the tick-based research modules load via importlib
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bfa.backtest.adapters import (
    LimitRangeFoldRunner,
    MicroGridFoldRunner,
    TrendFoldRunner,
)
from bfa.backtest.cost import CostModel
from bfa.backtest.walk_forward import WalkForwardValidator, expanding_month_folds, write_verdict
from bfa.backtest.models import BacktestBar
from bfa.market.vision_archives import (
    fetch_funding_rate_zip,
    fetch_klines_zip,
    parse_funding_rate_zip,
    parse_klines_zip,
)

FEE_TIERS_PATH = ROOT / "src" / "bfa" / "backtest" / "fee_tiers.json"
CACHE_DIR = ROOT / "data" / "research" / "vision-cache"
OUT_DIR = ROOT / "data" / "research" / "alpha_validation"
AGG_CACHE_DIR = Path(r"D:/教青垃圾系統/binance/aggTrades-cache")

DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    "AVAXUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT", "HYPEUSDT", "ONDOUSDT",
    "PUMPUSDT", "AAVEUSDT", "NEARUSDT", "LTCUSDT", "ZECUSDT", "SANDUSDT",
    "WLDUSDT", "ENAUSDT", "UNIUSDT", "ARBUSDT", "OPUSDT", "WIFUSDT",
    "1000PEPEUSDT",
)
# micro/limit-range defaults: 7 high-density symbols, the months present in the
# aggTrades cache (2026-03 / 05 / 06). 2 folds: train=Mar -> test=May,
# train=Mar+May -> test=Jun (Jun is the final holdout).
DEFAULT_MICRO_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT", "HYPEUSDT", "ONDOUSDT", "PUMPUSDT",
)
DEFAULT_MICRO_MONTHS = ["2026-03", "2026-05", "2026-06"]

DEFAULT_MONTHS = ["2025-12", "2026-01", "2026-02", "2026-03"]


def _load_csv_klines(path: Path, symbol: str) -> list[BacktestBar]:
    bars: list[BacktestBar] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if not row or not row[0].isdigit():
                continue
            bars.append(BacktestBar.from_binance_kline(symbol, row))
    return bars


def _load_research(name: str, filename: str):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _month_to_date_range(month: str) -> tuple[date, date]:
    y, m = month.split("-")
    start = date(int(y), int(m), 1)
    if int(m) == 12:
        end = date(int(y), 12, 31)
    else:
        end = date(int(y), int(m) + 1, 1) - timedelta(days=1)
    return start, end


def load_klines(symbols, months, interval="5m", klines_dir: Path | None = None):
    """Load kline bars + funding rates for the trend / limit_range legs."""
    bars_by_symbol: dict[str, list[BacktestBar]] = {}
    funding_by_symbol: dict[str, list[tuple[int, float]]] = {}
    for i, sym in enumerate(symbols, 1):
        all_bars: list[BacktestBar] = []
        all_rates: list[tuple[int, float]] = []
        loaded_csv = False
        if klines_dir is not None:
            csv_path = klines_dir / f"{sym}_{interval}.csv"
            if csv_path.exists():
                try:
                    all_bars = _load_csv_klines(csv_path, sym)
                    loaded_csv = True
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {sym} csv klines: {exc}", file=sys.stderr)
        if not loaded_csv:
            for month in months:
                try:
                    kdata = fetch_klines_zip(sym, interval, month, CACHE_DIR)
                    all_bars.extend(parse_klines_zip(sym, kdata))
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {sym} {month} klines: {exc}", file=sys.stderr)
        for month in months:
            try:
                fdata = fetch_funding_rate_zip(sym, month, CACHE_DIR)
                all_rates.extend(parse_funding_rate_zip(fdata))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} funding: {exc}", file=sys.stderr)
        all_bars.sort(key=lambda b: b.open_time)
        all_rates.sort(key=lambda r: r[0])
        if all_bars:
            bars_by_symbol[sym] = all_bars
            funding_by_symbol[sym] = all_rates
            source = "csv" if loaded_csv else "vision"
            print(f"[{i}/{len(symbols)}] {sym} ({source}): {len(all_bars)} bars, {len(all_rates)} funding events")
    return bars_by_symbol, funding_by_symbol


def load_micro_seconds(symbols, months, agg_cache_dir: Path):
    """Load aggTrades-derived 1-second bars for the micro leg, per month range."""
    second_agg = _load_research("second_agg", "run_second_agg_compound_backtest.py")
    seconds_by_symbol: dict[str, list[BacktestBar]] = {}
    funding_by_symbol: dict[str, list[tuple[int, float]]] = {}
    for i, sym in enumerate(symbols, 1):
        all_seconds: list[BacktestBar] = []
        all_rates: list[tuple[int, float]] = []
        for month in months:
            start, end = _month_to_date_range(month)
            try:
                secs, _cov = second_agg.load_symbol_seconds(sym, start, end, agg_cache_dir)
                all_seconds.extend(secs)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} seconds: {exc}", file=sys.stderr)
            try:
                fdata = fetch_funding_rate_zip(sym, month, CACHE_DIR)
                all_rates.extend(parse_funding_rate_zip(fdata))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} funding: {exc}", file=sys.stderr)
        all_seconds.sort(key=lambda b: b.open_time)
        all_rates.sort(key=lambda r: r[0])
        if all_seconds:
            seconds_by_symbol[sym] = all_seconds
            funding_by_symbol[sym] = all_rates
            print(f"[{i}/{len(symbols)}] {sym} (aggTrades): {len(all_seconds)} 1s bars, {len(all_rates)} funding events")
    return seconds_by_symbol, funding_by_symbol


def _cost_snapshot(cost_model: CostModel) -> dict:
    return {
        "fee_source": "binance_public_schedule",
        "default_tier": {"maker_fee_bps": cost_model.default_tier.maker_fee_bps,
                         "taker_fee_bps": cost_model.default_tier.taker_fee_bps},
        "note": "Excludes operator VIP tier + BNB discount. Per-symbol exceptions in fee_tiers.json.",
        "fee_tiers_path": str(FEE_TIERS_PATH),
    }


def _run_validator(runner, folds, cost_model, out_path) -> dict:
    validator = WalkForwardValidator(
        runner=runner, folds=folds, cost_model_snapshot=_cost_snapshot(cost_model),
    )
    verdict = validator.run()
    write_verdict(verdict, out_path)
    print(f"# verdict: {verdict['verdict']}")
    print(f"# oos aggregate: {verdict['oos_aggregate']}")
    print(f"# written: {out_path}")
    return verdict


def run_trend(args, cost_model) -> int:
    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    months = [m.strip() for m in args.months.split(",") if m.strip()]
    klines_dir = Path(args.klines_dir) if args.klines_dir else None
    print(f"# loading data: {len(symbols)} symbols x {len(months)} months")
    bars, funding = load_klines(symbols, months, interval=args.interval, klines_dir=klines_dir)
    print(f"# loaded: {len(bars)} symbols with bars")
    if args.fast_grid:
        import bfa.backtest.walk_forward as wf
        wf.LEG_GRIDS["trend"] = {"min_post_cost_edge_ratio": [1.0, 1.8, 2.2, 2.5]}
        print("# fast grid: only min_post_cost_edge_ratio")
    runner = TrendFoldRunner(
        cost_model=cost_model, variant_name=args.variant,
        bars_by_symbol=bars, funding_rates_by_symbol=funding,
    )
    folds = expanding_month_folds(months, symbols=symbols, leg="trend")
    print(f"# folds: {len(folds)}")
    _run_validator(runner, folds, cost_model, Path(args.out))
    return 0


def run_limit_range(args, cost_model) -> int:
    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    months = [m.strip() for m in args.months.split(",") if m.strip()]
    klines_dir = Path(args.klines_dir) if args.klines_dir else None
    print(f"# loading 1m klines: {len(symbols)} symbols x {len(months)} months")
    bars, funding = load_klines(symbols, months, interval="1m", klines_dir=klines_dir)
    print(f"# loaded: {len(bars)} symbols with 1m bars")
    if args.fast_grid:
        import bfa.backtest.walk_forward as wf
        wf.LEG_GRIDS["limit_range"] = {"min_reward_cost_ratio": [1.0, 1.8, 2.2, 2.5]}
        print("# fast grid: only min_reward_cost_ratio")
    runner = LimitRangeFoldRunner(
        cost_model=cost_model, bars_by_symbol=bars, funding_rates_by_symbol=funding,
        scan_stride=args.scan_stride,
    )
    folds = expanding_month_folds(months, symbols=symbols, leg="limit_range")
    print(f"# folds: {len(folds)}")
    _run_validator(runner, folds, cost_model, Path(args.out))
    return 0


def run_micro(args, cost_model) -> int:
    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    months = [m.strip() for m in args.months.split(",") if m.strip()]
    agg_dir = Path(args.agg_cache_dir) if args.agg_cache_dir else AGG_CACHE_DIR
    print(f"# loading aggTrades seconds: {len(symbols)} symbols x {len(months)} months")
    seconds, funding = load_micro_seconds(symbols, months, agg_dir)
    print(f"# loaded: {len(seconds)} symbols with 1s bars")
    if args.fast_grid:
        import bfa.backtest.walk_forward as wf
        wf.LEG_GRIDS["micro"] = {"min_reward_cost_ratio": [1.0, 1.8, 2.2, 2.5]}
        print("# fast grid: only min_reward_cost_ratio")
    # Build a TickReplaySource per symbol over the full month span so fills use
    # real tick-precise wicks (second-bar simulation flattens spikes per the
    # script author's own note; without ticks the micro leg shows false 0 WR).
    tick_sources: dict[str, object] = {}
    if not args.no_ticks:
        mg = _load_research("micro_grid_research", "run_micro_grid_research.py")
        first_start, _ = _month_to_date_range(months[0])
        _, last_end = _month_to_date_range(months[-1])
        for sym in seconds:
            tick_sources[sym] = mg.TickReplaySource(
                symbol=sym, start=first_start, end=last_end, cache_dir=agg_dir,
            )
        print(f"# tick replay enabled for {len(tick_sources)} symbols")
    runner = MicroGridFoldRunner(
        cost_model=cost_model, seconds_by_symbol=seconds,
        funding_rates_by_symbol=funding, tick_sources_by_symbol=tick_sources,
    )
    folds = expanding_month_folds(months, symbols=symbols, leg="micro")
    print(f"# folds: {len(folds)}")
    _run_validator(runner, folds, cost_model, Path(args.out))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="trend", choices=["trend", "limit_range", "micro"])
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--months", default=None)
    ap.add_argument("--variant", default="quant_setup_live_action_flow")
    ap.add_argument("--out", default=None)
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--klines-dir", default=str(ROOT / "data" / "research" / "klines"),
                    help="directory with local CSV klines; falls back to Binance Vision if missing")
    ap.add_argument("--agg-cache-dir", default=str(AGG_CACHE_DIR),
                    help="aggTrades cache dir for the micro leg")
    ap.add_argument("--fast-grid", action="store_true",
                    help="reduce leg grid to the reward/cost knob only for faster iteration")
    ap.add_argument("--scan-stride", type=int, default=1,
                    help="limit_range: stride (bars) between evaluated signal windows; raise to speed up")
    ap.add_argument("--no-ticks", action="store_true",
                    help="micro: disable TickReplaySource (faster but flattens spikes; not verdict-grade)")
    args = ap.parse_args()

    # leg-specific defaults
    if args.symbols is None:
        args.symbols = ",".join(DEFAULT_MICRO_SYMBOLS if args.leg in ("micro", "limit_range") else DEFAULT_SYMBOLS)
    if args.months is None:
        args.months = ",".join(DEFAULT_MICRO_MONTHS if args.leg in ("micro", "limit_range") else DEFAULT_MONTHS)
    if args.out is None:
        args.out = str(OUT_DIR / f"{args.leg}_verdict.json")

    cost_model = CostModel.load_fee_tiers(FEE_TIERS_PATH)
    if args.leg == "trend":
        return run_trend(args, cost_model)
    if args.leg == "limit_range":
        return run_limit_range(args, cost_model)
    if args.leg == "micro":
        return run_micro(args, cost_model)
    return 2


if __name__ == "__main__":
    sys.exit(main())
