"""Historical kline loading and fetching helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bfa.backtest.models import BacktestBar
from bfa.market.binance_rest import BinanceFuturesRestClient


INTERVAL_MS = {
    "1s": 1_000,
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def load_klines_dataset(path: str | Path) -> dict[str, list[BacktestBar]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("symbols"), dict):
        return {
            str(symbol).upper(): [BacktestBar.from_binance_kline(str(symbol), row) for row in rows]
            for symbol, rows in payload["symbols"].items()
        }
    if isinstance(payload, dict) and isinstance(payload.get("klines"), list):
        symbol = str(payload.get("symbol", "")).upper()
        if not symbol:
            raise ValueError("single-symbol kline payload must include symbol")
        return {symbol: [BacktestBar.from_binance_kline(symbol, row) for row in payload["klines"]]}
    raise ValueError("unsupported kline dataset shape")


def write_klines_dataset(
    path: str | Path,
    *,
    interval: str,
    symbols: dict[str, list[Any]],
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "bfa_klines_v1",
        "interval": interval,
        "fetched_at": _now_iso(),
        "symbols": {symbol.upper(): rows for symbol, rows in sorted(symbols.items())},
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def fetch_historical_klines(
    client: BinanceFuturesRestClient,
    *,
    symbols: list[str],
    interval: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    page_limit: int = 1500,
) -> dict[str, list[Any]]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    start_ms = parse_time_ms(start) if start else None
    end_ms = parse_time_ms(end) if end else None
    results: dict[str, list[Any]] = {}
    for symbol in symbols:
        rows = _fetch_symbol_klines(
            client,
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
            page_limit=page_limit,
        )
        results[symbol.upper()] = rows
    return results


def parse_time_ms(value: str) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("time value is required")
    if text.isdigit():
        return int(text)
    normalized = text.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def _fetch_symbol_klines(
    client: BinanceFuturesRestClient,
    *,
    symbol: str,
    interval: str,
    start_ms: int | None,
    end_ms: int | None,
    limit: int,
    page_limit: int,
) -> list[Any]:
    rows: list[Any] = []
    next_start = start_ms
    remaining = limit
    while remaining > 0:
        request_limit = min(page_limit, remaining)
        response = client.klines(
            symbol,
            interval=interval,
            limit=request_limit,
            start_time=next_start,
            end_time=end_ms,
        )
        page = response.payload if isinstance(response.payload, list) else []
        if not page:
            break
        rows.extend(page)
        remaining -= len(page)
        if len(page) < request_limit:
            break
        last_open = int(page[-1][0])
        next_start = last_open + INTERVAL_MS[interval]
        if end_ms is not None and next_start > end_ms:
            break
    return rows


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
