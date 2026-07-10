"""Binance Vision public archive loader for futures (USD-M).

`fapi.binance.com` is unreachable from some dev machines, but
`data.binance.vision` (the public data bucket) is reachable and publishes
monthly klines and fundingRate archives. This module fetches and parses them
with a local cache so re-runs are cheap.

No secrets, no auth, no live env. Pure public market data.
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from pathlib import Path

from bfa.backtest.models import BacktestBar

VISION = "https://data.binance.vision"


def funding_rate_url(symbol: str, month: str) -> str:
    return f"{VISION}/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def klines_monthly_url(symbol: str, interval: str, month: str) -> str:
    return f"{VISION}/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def _fetch_zip(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "bfa-vision-archive"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _cache_path(cache_dir: Path, symbol: str, kind: str, month: str, interval: str | None) -> Path:
    name = (
        f"{symbol}-{kind}-{month}.zip"
        if interval is None
        else f"{symbol}-{interval}-{kind}-{month}.zip"
    )
    return cache_dir / symbol / name


def _zip_is_corrupt(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is not None
    except (zipfile.BadZipFile, OSError):
        return True


def fetch_funding_rate_zip(symbol: str, month: str, cache_dir: Path) -> bytes:
    p = _cache_path(cache_dir, symbol, "fundingRate", month, None)
    if p.exists() and not _zip_is_corrupt(p):
        return p.read_bytes()
    data = _fetch_zip(funding_rate_url(symbol, month))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def fetch_klines_zip(symbol: str, interval: str, month: str, cache_dir: Path) -> bytes:
    p = _cache_path(cache_dir, symbol, "klines", month, interval)
    if p.exists() and not _zip_is_corrupt(p):
        return p.read_bytes()
    data = _fetch_zip(klines_monthly_url(symbol, interval, month))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def parse_funding_rate_zip(data: bytes) -> list[tuple[int, float]]:
    """Return sorted [(time_ms, rate)] from a fundingRate monthly archive."""
    rates: list[tuple[int, float]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        calc_time = int(row["calc_time"])
        rate = float(row["last_funding_rate"])
        rates.append((calc_time, rate))
    rates.sort(key=lambda item: item[0])
    return rates


def parse_klines_zip(symbol: str, data: bytes) -> list[BacktestBar]:
    """Parse a klines monthly archive into BacktestBar objects."""
    bars: list[BacktestBar] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    for row in reader:
        if not row or not row[0].isdigit():
            continue
        bars.append(BacktestBar.from_binance_kline(symbol, row))
    return bars
