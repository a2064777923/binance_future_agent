"""Prepare selected self-collected Binance trade ticks for exact replay."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import gzip
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, TextIO
import zipfile


RAW_FEED_PATTERN = "binance-usdm-raw-*.gz"


def extract_raw_trade_archives(
    raw_feed_dir: str | Path,
    output_cache_dir: str | Path,
    *,
    symbols: Iterable[str],
    start_ms: int,
    end_ms: int,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Scan raw gzip files once and emit per-symbol/day replay ZIP archives.

    The output uses Binance's seven-column aggTrades-compatible CSV layout,
    but each row remains an individual ``@trade`` event. The micro replay only
    consumes price, quantity, event time, and buyer-maker side, so aggregation
    identifiers are not synthesized beyond reusing the public trade id.
    """

    selected = tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
    if not selected:
        raise ValueError("at least one symbol is required")
    if end_ms < start_ms:
        raise ValueError("end_ms must be on or after start_ms")
    raw_dir = Path(raw_feed_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw feed directory missing: {raw_dir}")
    output_dir = Path(output_cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = Path(manifest_path) if manifest_path is not None else output_dir / "manifest.json"
    files = _overlapping_raw_files(raw_dir, start_ms=start_ms, end_ms=end_ms)
    source_compressed_bytes = sum(_file_size_or_zero(path) for path in files)
    selected_set = set(selected)
    started = time.perf_counter()
    stats = {
        symbol: {
            "trade_count": 0,
            "duplicate_count": 0,
            "first_event_ms": None,
            "last_event_ms": None,
            "first_local_ms": None,
            "last_local_ms": None,
            "trade_seconds": set(),
            "latencies_ms": [],
            "archive_bytes": 0,
            "archive_count": 0,
        }
        for symbol in selected
    }
    last_trade_ids: dict[str, int | None] = {symbol: None for symbol in selected}
    parse_error_count = 0
    truncated_file_count = 0
    created_archives: list[str] = []

    with tempfile.TemporaryDirectory(prefix="bfa-raw-replay-") as temp_text:
        temp_dir = Path(temp_text)
        handles: dict[tuple[str, str], TextIO] = {}
        writers: dict[tuple[str, str], Any] = {}
        try:
            for path in files:
                try:
                    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                        for line in handle:
                            try:
                                parsed = _selected_trade_line(line, selected_set)
                            except (KeyError, TypeError, ValueError):
                                parse_error_count += 1
                                continue
                            if parsed is None:
                                continue
                            try:
                                symbol, trade_id, event_ms, price, quantity, buyer_maker, local_ms = parsed
                                if event_ms < start_ms or event_ms > end_ms:
                                    continue
                                symbol_stats = stats[symbol]
                                last_trade_id = last_trade_ids[symbol]
                                if last_trade_id is not None and trade_id <= last_trade_id:
                                    symbol_stats["duplicate_count"] += 1
                                    continue
                                last_trade_ids[symbol] = trade_id
                                day = datetime.fromtimestamp(event_ms / 1000.0, tz=UTC).date().isoformat()
                                key = (symbol, day)
                                if key not in writers:
                                    csv_path = temp_dir / f"{symbol}-aggTrades-{day}.csv"
                                    handles[key] = csv_path.open("w", encoding="utf-8", newline="")
                                    writers[key] = csv.writer(handles[key], lineterminator="\n")
                                writers[key].writerow(
                                    (
                                        trade_id,
                                        price,
                                        quantity,
                                        trade_id,
                                        trade_id,
                                        event_ms,
                                        "true" if buyer_maker else "false",
                                    )
                                )
                                _update_stats(symbol_stats, event_ms=event_ms, local_ms=local_ms)
                            except (KeyError, TypeError, ValueError):
                                parse_error_count += 1
                except (EOFError, OSError):
                    truncated_file_count += 1
        finally:
            for handle in handles.values():
                handle.close()

        for (symbol, day), _ in sorted(writers.items()):
            csv_path = temp_dir / f"{symbol}-aggTrades-{day}.csv"
            symbol_dir = output_dir / symbol
            symbol_dir.mkdir(parents=True, exist_ok=True)
            archive = symbol_dir / f"{symbol}-aggTrades-{day}.zip"
            if archive.exists() and not overwrite:
                raise FileExistsError(f"replay archive already exists: {archive}")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(csv_path, arcname=csv_path.name)
            stats[symbol]["archive_bytes"] += archive.stat().st_size
            stats[symbol]["archive_count"] += 1
            created_archives.append(str(archive))

    coverage = {symbol: _finalize_stats(values) for symbol, values in stats.items()}
    report = {
        "schema": "bfa_self_collected_tick_extract_v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "self_collected_binance_usdm_trade_websocket",
        "window": {
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
            "start": _iso_ms(start_ms),
            "end": _iso_ms(end_ms),
        },
        "symbols": list(selected),
        "source_file_count": len(files),
        "source_compressed_bytes": source_compressed_bytes,
        "parse_error_count": parse_error_count,
        "truncated_file_count": truncated_file_count,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "created_archives": created_archives,
        "coverage": coverage,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _overlapping_raw_files(raw_feed_dir: Path, *, start_ms: int, end_ms: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(raw_feed_dir.glob(RAW_FEED_PATTERN)):
        nominal_start_ms = _raw_file_start_ms(path)
        if nominal_start_ms is not None and nominal_start_ms > end_ms:
            continue
        try:
            last_write_ms = int(path.stat().st_mtime * 1000)
        except OSError:
            continue
        if last_write_ms < start_ms:
            continue
        files.append(path)
    return files


def _raw_file_start_ms(path: Path) -> int | None:
    marker = "binance-usdm-raw-"
    if marker not in path.name:
        return None
    stamp = path.name.split(marker, 1)[1].split(".", 1)[0]
    try:
        parsed = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _file_size_or_zero(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _selected_trade_line(
    line: str,
    symbols: set[str],
) -> tuple[str, int, int, str, str, bool, int | None] | None:
    trade_marker = line.find("@trade")
    if trade_marker < 0:
        return None
    quote_start = line.rfind('"', 0, trade_marker)
    if quote_start < 0:
        return None
    stream_symbol = line[quote_start + 1 : trade_marker].upper()
    if stream_symbol not in symbols:
        return None
    text = line.strip()
    local_ms: int | None = None
    if text and text[0].isdigit() and " " in text:
        head, text = text.split(" ", 1)
        try:
            local_ms = int(head) // 1_000_000
        except ValueError:
            local_ms = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(data.get("e") or "").lower() != "trade":
        return None
    symbol = str(data.get("s") or stream_symbol).upper()
    if symbol not in symbols:
        return None
    trade_id = int(data["t"])
    event_ms = int(data.get("T") or data.get("E"))
    price = str(data["p"])
    quantity = str(data["q"])
    if float(price) <= 0 or float(quantity) <= 0:
        return None
    return symbol, trade_id, event_ms, price, quantity, bool(data.get("m")), local_ms


def _update_stats(values: dict[str, Any], *, event_ms: int, local_ms: int | None) -> None:
    values["trade_count"] += 1
    values["first_event_ms"] = event_ms if values["first_event_ms"] is None else min(values["first_event_ms"], event_ms)
    values["last_event_ms"] = event_ms if values["last_event_ms"] is None else max(values["last_event_ms"], event_ms)
    values["trade_seconds"].add(event_ms // 1000)
    if local_ms is None:
        return
    values["first_local_ms"] = local_ms if values["first_local_ms"] is None else min(values["first_local_ms"], local_ms)
    values["last_local_ms"] = local_ms if values["last_local_ms"] is None else max(values["last_local_ms"], local_ms)
    values["latencies_ms"].append(local_ms - event_ms)


def _finalize_stats(values: dict[str, Any]) -> dict[str, Any]:
    latencies = values.pop("latencies_ms")
    trade_seconds = values.pop("trade_seconds")
    first = values.get("first_event_ms")
    last = values.get("last_event_ms")
    expected_seconds = (last // 1000 - first // 1000 + 1) if first is not None and last is not None else 0
    return {
        **values,
        "trade_second_count": len(trade_seconds),
        "within_observed_span_second_coverage": round(len(trade_seconds) / expected_seconds, 6)
        if expected_seconds
        else 0.0,
        "latency_ms_p50": _rounded_percentile(latencies, 0.50),
        "latency_ms_p95": _rounded_percentile(latencies, 0.95),
        "latency_ms_p99": _rounded_percentile(latencies, 0.99),
        "latency_ms_max": max(latencies) if latencies else None,
        "negative_latency_fraction": round(sum(1 for value in latencies if value < 0) / len(latencies), 6)
        if latencies
        else None,
    }


def _rounded_percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    result = ordered[lower] if lower == upper else ordered[lower] * (upper - position) + ordered[upper] * (position - lower)
    return round(float(result), 3)


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
