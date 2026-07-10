"""Fetch long-history klines for the research universe (server-side downloader).

Designed to run on the server sandbox where Binance fapi is reachable. Fetches
6 months of 5m + 15m klines for each universe symbol, with resume, rate-limiting,
and retry. Output is one compact CSV per (symbol, interval) under data/research/.

No live env, DB, or service is touched. No secrets.

Usage (on server):
    cd /opt/binance-futures-agent/backtest-p71/app
    /opt/binance-futures-agent/.venv/bin/python scripts/research/fetch_history.py \
        --months 6 --intervals 5m,15m
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "research" / "klines"
UNIVERSE_PATH = ROOT / "data" / "research" / "universe.json"
FAPI = "https://fapi.binance.com"


def load_universe() -> list[str]:
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    symbols = payload["symbols"]
    # exclude manual symbols from research training data
    manual = {"BTWUSDT"}
    return [s for s in symbols if s not in manual]


def fetch_klines_page(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1500) -> list[list]:
    url = (
        f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "bfa-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_all(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    retries = 0
    while cursor < end_ms:
        try:
            page = fetch_klines_page(symbol, interval, cursor, end_ms, limit=1500)
            retries = 0
        except Exception as exc:
            retries += 1
            if retries > 5:
                print(f"  ! {symbol} {interval}: giving up after 5 retries: {exc}", file=sys.stderr)
                break
            time.sleep(2 * retries)
            continue
        if not page:
            break
        rows.extend(page)
        last_open = int(page[-1][0])
        cursor = last_open + 1  # 1ms after last open to advance
        if len(page) < 1500:
            break
        time.sleep(0.15)  # gentle rate limit
    return rows


def output_path(symbol: str, interval: str) -> Path:
    return DATA_DIR / f"{symbol}_{interval}.csv"


def already_fetched(symbol: str, interval: str, expected_min_rows: int) -> bool:
    p = output_path(symbol, interval)
    if not p.exists():
        return False
    try:
        with p.open(encoding="utf-8") as fh:
            count = sum(1 for _ in fh) - 1
    except OSError:
        return False
    return count >= expected_min_rows * 0.9


def write_csv(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trade_count",
                    "taker_buy_volume", "taker_buy_quote_volume", "ignore"])
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--intervals", default="5m,15m")
    ap.add_argument("--symbols", default=None, help="override universe; comma-separated")
    args = ap.parse_args()

    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]
    universe = [s.strip() for s in args.symbols.split(",")] if args.symbols else load_universe()
    print(f"# universe: {len(universe)} symbols, intervals={intervals}, months={args.months}")

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.months * 30 * 24 * 3600 * 1000
    # rough expected row counts for resume check
    expected = {"5m": args.months * 30 * 24 * 12, "15m": args.months * 30 * 24 * 4,
                "1m": args.months * 30 * 24 * 60, "1h": args.months * 30 * 24}

    total_done = 0
    total_skip = 0
    for si, symbol in enumerate(universe, 1):
        for interval in intervals:
            exp_min = expected.get(interval, 1000)
            if already_fetched(symbol, interval, exp_min):
                total_skip += 1
                print(f"[{si}/{len(universe)}] {symbol} {interval}: cached, skip")
                continue
            print(f"[{si}/{len(universe)}] {symbol} {interval}: fetching...", end=" ", flush=True)
            rows = fetch_all(symbol, interval, start_ms, now_ms)
            if not rows:
                print("EMPTY")
                continue
            write_csv(output_path(symbol, interval), rows)
            total_done += 1
            print(f"{len(rows)} rows written")

    print(f"\n# done: fetched={total_done} skipped={total_skip}")
    print(f"# output dir: {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
