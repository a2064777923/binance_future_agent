"""Run hftbacktest micro-grid research on real L2/raw feed inputs.

Binance public ``bookDepth`` archives are deliberately handled as a probe only:
they are percent-band liquidity summaries, not tick-by-tick order book depth.
Use ``raw-feed`` for self-collected Binance futures WebSocket gzip logs, or
``historical-csv`` for vendor/self-collected depth+trades CSV in hftbacktest's
Binance historical market data schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
for path in (SCRIPT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bfa.backtest.hft_adapter import (  # noqa: E402
    HftPassiveGridConfig,
    convert_binance_raw_feed_to_hft,
    convert_historical_l2_csv_to_hft,
    fetch_binance_public_archive,
    hftbacktest_available,
    run_passive_hft_grid,
    summarize_public_book_depth_archive,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("public-probe", help="Probe Binance public bookDepth/trades archives without pretending they are L2")
    probe.add_argument("--symbol", required=True)
    probe.add_argument("--date", required=True, help="UTC date, YYYY-MM-DD")
    probe.add_argument("--cache-dir", default="runtime/hft-public-cache")
    probe.add_argument("--output", required=True)

    raw = subparsers.add_parser("raw-feed", help="Convert a self-collected Binance futures raw websocket gzip and run hft smoke")
    raw.add_argument("--input", required=True, help="gzip file in hftbacktest binancefutures raw stream format")
    raw.add_argument("--converted-output", default=None, help="optional .npz converted event file")
    raw.add_argument("--output", required=True)
    add_hft_grid_args(raw)

    csv_parser = subparsers.add_parser("historical-csv", help="Convert depth CSV + trades CSV and run hft smoke")
    csv_parser.add_argument("--depth-csv", required=True)
    csv_parser.add_argument("--trades-csv", required=True)
    csv_parser.add_argument("--converted-output", default=None, help="optional .npz converted event file")
    csv_parser.add_argument("--output", required=True)
    add_hft_grid_args(csv_parser)

    args = parser.parse_args()
    if args.command == "public-probe":
        payload = run_public_probe(args)
    elif args.command == "raw-feed":
        payload = run_raw_feed(args)
    elif args.command == "historical-csv":
        payload = run_historical_csv(args)
    else:
        raise SystemExit(f"unsupported command: {args.command}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": payload.get("summary") or payload.get("data_quality")}, indent=2, sort_keys=True))
    return 0


def add_hft_grid_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tick-size", type=float, required=True)
    parser.add_argument("--lot-size", type=float, required=True)
    parser.add_argument("--notional-usdt", type=float, default=20.0)
    parser.add_argument("--quote-offset-ticks", type=int, default=1)
    parser.add_argument("--max-position-qty", type=float, default=None)
    parser.add_argument("--grid-refresh-ms", type=int, default=1_000)
    parser.add_argument("--step-ms", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=200_000)
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--order-latency-ms", type=float, default=0.0)
    parser.add_argument("--buffer-size", type=int, default=100_000_000)


def run_public_probe(args: argparse.Namespace) -> dict[str, Any]:
    symbol = args.symbol.upper()
    day = date.fromisoformat(args.date)
    cache_dir = Path(args.cache_dir)
    book_depth = fetch_binance_public_archive("bookDepth", symbol, day, cache_dir)
    trades = fetch_binance_public_archive("trades", symbol, day, cache_dir)
    book_depth_summary = summarize_public_book_depth_archive(symbol, day, book_depth.path)
    return {
        "schema": "bfa_hft_public_archive_probe_v1",
        "symbol": symbol,
        "date": day.isoformat(),
        "archives": {
            "bookDepth": archive_to_dict(book_depth),
            "trades": archive_to_dict(trades),
        },
        "bookDepth_summary": book_depth_summary.to_dict(),
        "data_quality": {
            "hftbacktest_l2_ready": False,
            "blocker": "public bookDepth is aggregated by percentage bands and timestamp, not an executable L2 order book feed",
            "usable_for": ["liquidity regime features", "symbol screening", "coarse depth imbalance context"],
            "not_usable_for": ["queue position", "post-only fill probability", "tick-level stop/target ordering"],
        },
        "next_data_path": {
            "preferred": "self-collected Binance futures raw websocket gzip with depthUpdate + trade + periodic snapshots",
            "alternative": "vendor/self-collected Binance historical depth CSV + trades CSV matching hftbacktest binancehistmktdata schema",
        },
    }


def run_raw_feed(args: argparse.Namespace) -> dict[str, Any]:
    ensure_hftbacktest()
    events, conversion = convert_binance_raw_feed_to_hft(
        Path(args.input),
        output_path=Path(args.converted_output) if args.converted_output else None,
        buffer_size=int(args.buffer_size),
    )
    grid_config = grid_config_from_args(args)
    summary = run_passive_hft_grid(events, config=grid_config)
    return {
        "schema": "bfa_hftbacktest_raw_feed_micro_grid_v1",
        "conversion": conversion.to_dict(),
        "grid_config": asdict(grid_config),
        "summary": summary,
    }


def run_historical_csv(args: argparse.Namespace) -> dict[str, Any]:
    ensure_hftbacktest()
    events, conversion = convert_historical_l2_csv_to_hft(
        Path(args.depth_csv),
        Path(args.trades_csv),
        output_path=Path(args.converted_output) if args.converted_output else None,
        buffer_size=int(args.buffer_size),
    )
    grid_config = grid_config_from_args(args)
    summary = run_passive_hft_grid(events, config=grid_config)
    return {
        "schema": "bfa_hftbacktest_historical_csv_micro_grid_v1",
        "conversion": conversion.to_dict(),
        "grid_config": asdict(grid_config),
        "summary": summary,
    }


def ensure_hftbacktest() -> None:
    if not hftbacktest_available():
        raise SystemExit("hftbacktest is not installed; use the isolated .venv-hft environment")


def grid_config_from_args(args: argparse.Namespace) -> HftPassiveGridConfig:
    return HftPassiveGridConfig(
        tick_size=float(args.tick_size),
        lot_size=float(args.lot_size),
        notional_usdt=float(args.notional_usdt),
        quote_offset_ticks=int(args.quote_offset_ticks),
        max_position_qty=float(args.max_position_qty) if args.max_position_qty is not None else None,
        grid_refresh_ns=int(args.grid_refresh_ms * 1_000_000),
        step_ns=int(args.step_ms * 1_000_000),
        max_steps=int(args.max_steps),
        maker_fee_bps=float(args.maker_fee_bps),
        taker_fee_bps=float(args.taker_fee_bps),
        order_latency_ns=int(args.order_latency_ms * 1_000_000),
    )


def archive_to_dict(archive) -> dict[str, Any]:
    return {
        "market": archive.market,
        "symbol": archive.symbol,
        "day": archive.day.isoformat(),
        "path": str(archive.path),
        "url": archive.url,
        "size_bytes": archive.size_bytes,
    }


if __name__ == "__main__":
    raise SystemExit(main())
