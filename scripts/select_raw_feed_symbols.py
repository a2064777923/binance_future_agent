"""Select raw-feed symbols from the same hot-universe inputs used by live."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
for path in (SCRIPT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bfa.agent import _crypto_perpetual_symbol_filter  # noqa: E402
from bfa.backtest.matrix import HotUniverseConfig, select_hot_usdt_symbols  # noqa: E402
from bfa.market.binance_rest import BinanceFuturesRestClient  # noqa: E402
from bfa.market.raw_feed_recorder import normalize_symbols  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://fapi.binance.com")
    parser.add_argument("--top-n", type=int, default=80)
    parser.add_argument("--min-quote-volume-usdt", type=float, default=10_000_000.0)
    parser.add_argument("--min-abs-price-change-percent", type=float, default=0.5)
    parser.add_argument("--fallback-symbols", required=True)
    parser.add_argument("--crypto-only", action="store_true")
    args = parser.parse_args()

    symbols = select_symbols(
        base_url=args.base_url,
        top_n=args.top_n,
        min_quote_volume_usdt=args.min_quote_volume_usdt,
        min_abs_price_change_percent=args.min_abs_price_change_percent,
        fallback_symbols=args.fallback_symbols,
        crypto_only=args.crypto_only,
    )
    print(",".join(symbols))
    return 0


def select_symbols(
    *,
    base_url: str,
    top_n: int,
    min_quote_volume_usdt: float,
    min_abs_price_change_percent: float,
    fallback_symbols: str,
    crypto_only: bool,
) -> tuple[str, ...]:
    fallback = normalize_symbols(fallback_symbols)
    client = BinanceFuturesRestClient(base_url=base_url)
    ticker_payload = client.ticker_24hr().payload
    ticker_rows = ticker_payload if isinstance(ticker_payload, list) else []
    if crypto_only:
        exchange_info_payload = client.exchange_info().payload
        crypto_symbols, _diagnostics = _crypto_perpetual_symbol_filter(exchange_info_payload)
        ticker_rows = [
            row
            for row in ticker_rows
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() in crypto_symbols
        ]
    hot_rows = select_hot_usdt_symbols(
        [row for row in ticker_rows if isinstance(row, dict)],
        HotUniverseConfig(
            top_n=max(int(top_n), 1),
            min_quote_volume_usdt=float(min_quote_volume_usdt),
            min_abs_price_change_percent=float(min_abs_price_change_percent),
        ),
    )
    symbols = tuple(str(row.get("symbol") or "").upper() for row in hot_rows if row.get("symbol"))
    return symbols or fallback


if __name__ == "__main__":
    raise SystemExit(main())
