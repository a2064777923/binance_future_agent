"""Extract selected self-collected Binance trade ticks for exact replay."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bfa.backtest.raw_feed_replay import extract_raw_trade_archives  # noqa: E402


def parse_iso_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-feed-dir", required=True)
    parser.add_argument("--symbols", required=True, help="comma-separated symbols frozen before outcome replay")
    parser.add_argument("--start", required=True, help="inclusive UTC ISO timestamp")
    parser.add_argument("--end", required=True, help="inclusive UTC ISO timestamp")
    parser.add_argument("--output-cache-dir", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    report = extract_raw_trade_archives(
        args.raw_feed_dir,
        args.output_cache_dir,
        symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()],
        start_ms=parse_iso_ms(args.start),
        end_ms=parse_iso_ms(args.end),
        manifest_path=args.manifest,
        overwrite=bool(args.overwrite),
    )
    summary = {
        "manifest": str(args.manifest or Path(args.output_cache_dir) / "manifest.json"),
        "source_file_count": report["source_file_count"],
        "source_compressed_bytes": report["source_compressed_bytes"],
        "elapsed_seconds": report["elapsed_seconds"],
        "symbol_trade_counts": {
            symbol: values["trade_count"] for symbol, values in report["coverage"].items()
        },
    }
    print(json.dumps(summary if args.quiet else report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
