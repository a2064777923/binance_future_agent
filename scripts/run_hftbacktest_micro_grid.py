"""Smoke hftbacktest runner for Binance micro-grid research.

This runner intentionally starts with a degraded aggTrades + synthetic BBO
adapter. It validates the hftbacktest backend wiring before full Binance L2
depth archives are added.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
for path in (SCRIPT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bfa.backtest.hft_adapter import AggTradeLike, HftSyntheticBboConfig, convert_agg_trades_to_hft_events  # noqa: E402
from run_second_agg_compound_backtest import fetch_zip, read_aggtrade_zip  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--cache-dir", default="runtime/aggTrades-cache")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-trades", type=int, default=5_000)
    parser.add_argument("--tick-size", type=float, default=0.001)
    parser.add_argument("--lot-size", type=float, default=1.0)
    parser.add_argument("--synthetic-spread-ticks", type=int, default=1)
    parser.add_argument("--synthetic-depth-qty", type=float, default=10_000.0)
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--notional-usdt", type=float, default=20.0)
    parser.add_argument("--quote-offset-ticks", type=int, default=1)
    parser.add_argument("--step-ns", type=int, default=1_000_000)
    parser.add_argument("--max-steps", type=int, default=20_000)
    args = parser.parse_args()

    payload = run_smoke(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": payload["summary"]}, indent=2, sort_keys=True))
    return 0


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    import hftbacktest as hft

    symbol = args.symbol.upper()
    day = date.fromisoformat(args.date)
    zip_path = fetch_zip(symbol, day, Path(args.cache_dir))
    raw_rows = read_aggtrade_zip(zip_path)
    rows = raw_rows[: max(1, int(args.max_trades))]
    trades = [
        AggTradeLike(
            time_ms=int(row["time_ms"]),
            price=float(row["price"]),
            quantity=float(row["quantity"]),
            buyer_maker=bool(row["buyer_maker"]),
        )
        for row in rows
    ]
    config = HftSyntheticBboConfig(
        tick_size=float(args.tick_size),
        lot_size=float(args.lot_size),
        synthetic_spread_ticks=int(args.synthetic_spread_ticks),
        synthetic_depth_qty=float(args.synthetic_depth_qty),
    )
    events = convert_agg_trades_to_hft_events(trades, config=config)
    if len(events) == 0:
        raise SystemExit("no hft events generated")

    asset = (
        hft.BacktestAsset()
        .data(events)
        .linear_asset(1.0)
        .tick_size(float(args.tick_size))
        .lot_size(float(args.lot_size))
        .constant_order_latency(0, 0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(args.maker_fee_bps / 10_000.0, args.taker_fee_bps / 10_000.0)
        .risk_adverse_queue_model()
    )
    hbt = hft.HashMapMarketDepthBacktest([asset])
    try:
        summary = run_passive_smoke_loop(
            hbt,
            hft_module=hft,
            notional_usdt=float(args.notional_usdt),
            quote_offset_ticks=int(args.quote_offset_ticks),
            lot_size=float(args.lot_size),
            step_ns=int(args.step_ns),
            max_steps=int(args.max_steps),
        )
    finally:
        hbt.close()

    return {
        "schema": "bfa_hftbacktest_micro_grid_smoke_v1",
        "symbol": symbol,
        "date": day.isoformat(),
        "data_quality": {
            "mode": "degraded_aggtrade_synthetic_bbo",
            "warning": "aggTrades lack real L2/L3 depth and queue position; use Binance depth/bookTicker archives before treating results as production evidence",
            "raw_aggtrade_rows": len(raw_rows),
            "used_aggtrade_rows": len(rows),
            "hft_event_rows": int(len(events)),
            "config": asdict(config),
        },
        "fees": {
            "maker_fee_bps": float(args.maker_fee_bps),
            "taker_fee_bps": float(args.taker_fee_bps),
        },
        "summary": summary,
    }


def run_passive_smoke_loop(
    hbt,
    *,
    hft_module,
    notional_usdt: float,
    quote_offset_ticks: int,
    lot_size: float,
    step_ns: int,
    max_steps: int,
) -> dict[str, Any]:
    submitted_orders = 0
    last_order_id = 1
    quote_offset_ticks = max(0, int(quote_offset_ticks))
    last_timestamp = None
    for step in range(max(1, max_steps)):
        status = hbt.elapse(max(1, int(step_ns)))
        last_timestamp = int(hbt.current_timestamp)
        depth = hbt.depth(0)
        if not is_finite_price(depth.best_bid) or not is_finite_price(depth.best_ask) or depth.best_ask <= depth.best_bid:
            if status != 0:
                break
            continue
        mid = (depth.best_bid + depth.best_ask) / 2.0
        qty = round(max(float(lot_size), notional_usdt / mid) / lot_size) * lot_size
        bid_px = max(float(depth.tick_size), (depth.best_bid_tick - quote_offset_ticks) * depth.tick_size)
        ask_px = (depth.best_ask_tick + quote_offset_ticks) * depth.tick_size
        if submitted_orders == 0:
            hbt.submit_buy_order(0, last_order_id, bid_px, qty, hft_module.GTX, hft_module.LIMIT, False)
            last_order_id += 1
            hbt.submit_sell_order(0, last_order_id, ask_px, qty, hft_module.GTX, hft_module.LIMIT, False)
            last_order_id += 1
            submitted_orders += 2
        if status != 0 and step > 0:
            break
    state = hbt.state_values(0)
    depth = hbt.depth(0)
    return {
        "submitted_orders": submitted_orders,
        "last_timestamp_ns": last_timestamp,
        "last_timestamp_iso": ns_to_iso(last_timestamp) if last_timestamp and last_timestamp < 9_000_000_000_000_000_000 else None,
        "best_bid": none_if_nan(depth.best_bid),
        "best_ask": none_if_nan(depth.best_ask),
        "position": float(state.position),
        "balance": float(state.balance),
        "fee": float(state.fee),
        "num_trades": int(state.num_trades),
        "trading_volume": float(state.trading_volume),
        "trading_value": float(state.trading_value),
    }


def is_finite_price(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def none_if_nan(value: float) -> float | None:
    return float(value) if value == value else None


def ns_to_iso(value: int) -> str:
    return datetime.utcfromtimestamp(value / 1_000_000_000).replace(microsecond=0).isoformat() + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
