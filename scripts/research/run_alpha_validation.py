"""Run alpha walk-forward validation and emit a verdict artifact.

Phase 1: trend leg. Pulls 5m klines + fundingRate monthly archives from
data.binance.vision (fapi is unreachable locally), runs expanding-window
walk-forward over Dec 2025 -> Mar 2026, grid-searches on train segments,
evaluates the best combo on each test segment, and writes the trend verdict
JSON to data/research/alpha_validation/trend_verdict.json.

No live env, no secrets, no order placement. Pure validation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bfa.backtest.adapters import TrendFoldRunner
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

DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    "AVAXUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT", "HYPEUSDT", "ONDOUSDT",
    "PUMPUSDT", "AAVEUSDT", "NEARUSDT", "LTCUSDT", "ZECUSDT", "SANDUSDT",
    "WLDUSDT", "ENAUSDT", "UNIUSDT", "ARBUSDT", "OPUSDT", "WIFUSDT",
    "1000PEPEUSDT",
)
DEFAULT_MONTHS = ["2025-12", "2026-01", "2026-02", "2026-03"]


def load_data(symbols, months, interval="5m"):
    bars_by_symbol: dict[str, list[BacktestBar]] = {}
    funding_by_symbol: dict[str, list[tuple[int, float]]] = {}
    for i, sym in enumerate(symbols, 1):
        all_bars: list[BacktestBar] = []
        all_rates: list[tuple[int, float]] = []
        for month in months:
            try:
                kdata = fetch_klines_zip(sym, interval, month, CACHE_DIR)
                all_bars.extend(parse_klines_zip(sym, kdata))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} klines: {exc}", file=sys.stderr)
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
            print(f"[{i}/{len(symbols)}] {sym}: {len(all_bars)} bars, {len(all_rates)} funding events")
    return bars_by_symbol, funding_by_symbol


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="trend", choices=["trend"])
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--months", default=",".join(DEFAULT_MONTHS))
    ap.add_argument("--variant", default="quant_setup_live_action_flow")
    ap.add_argument("--out", default=str(OUT_DIR / "trend_verdict.json"))
    ap.add_argument("--interval", default="5m")
    args = ap.parse_args()

    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    months = [m.strip() for m in args.months.split(",") if m.strip()]
    cost_model = CostModel.load_fee_tiers(FEE_TIERS_PATH)
    print(f"# loading data: {len(symbols)} symbols x {len(months)} months")
    bars, funding = load_data(symbols, months, interval=args.interval)
    print(f"# loaded: {len(bars)} symbols with bars")

    runner = TrendFoldRunner(
        cost_model=cost_model, variant_name=args.variant,
        bars_by_symbol=bars, funding_rates_by_symbol=funding,
    )
    folds = expanding_month_folds(months, symbols=symbols, leg=args.leg)
    print(f"# folds: {len(folds)}")
    validator = WalkForwardValidator(
        runner=runner, folds=folds,
        cost_model_snapshot={
            "fee_source": "binance_public_schedule",
            "default_tier": {"maker_fee_bps": cost_model.default_tier.maker_fee_bps,
                             "taker_fee_bps": cost_model.default_tier.taker_fee_bps},
            "note": "Excludes operator VIP tier + BNB discount. Per-symbol exceptions in fee_tiers.json.",
            "fee_tiers_path": str(FEE_TIERS_PATH),
        },
    )
    verdict = validator.run()
    write_verdict(verdict, args.out)
    print(f"# verdict: {verdict['verdict']}")
    print(f"# oos aggregate: {verdict['oos_aggregate']}")
    print(f"# written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
