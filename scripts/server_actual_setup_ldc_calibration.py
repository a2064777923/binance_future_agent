"""Calibrate LDC against actual routed trend setups and raw tick paths.

Read-only server research tool. It reads persisted ``trade_setups`` from the
live SQLite store, labels each setup from self-collected raw Binance trade ticks
using the setup's own limit entry / stop / target geometry, then measures
whether a Lorentzian kNN confidence modifier would help the real routed trend
leg. It never places orders, never calls signed endpoints, and never mutates the
database.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import gzip
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable, Mapping

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
for _path in (ROOT_DIR, SCRIPT_DIR, SRC_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts.server_live_trade_forensics import parse_raw_trade_line  # noqa: E402
from bfa.strategy.ldc_classifier import LdcArtifact, lorentzian_distance, save_ldc_artifact  # noqa: E402


FEATURE_NAMES = ("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6")
FEATURE_SOURCE_KEYS = {
    "ema_spread": "ema_spread_percent",
    "rsi": "rsi",
    "atr_percent": "atr_percent",
    "taker_ratio": "taker_buy_sell_ratio",
    "mom_6": "kline_momentum_percent",
}


@dataclass(frozen=True)
class Tick:
    event_ms: int
    price: float
    quantity: float


@dataclass(frozen=True)
class SetupSample:
    row_id: int
    event_id: int | None
    occurred_at: datetime
    symbol: str
    side: str
    strategy_leg: str
    regime_label: str
    route_decision: str
    decision: str
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    wait_seconds: int
    confidence: float | None
    edge_score: float | None
    risk_reward_ratio: float | None
    features: dict[str, Any]
    setup: dict[str, Any]
    candidate: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/opt/binance-futures-agent/data/agent.sqlite")
    parser.add_argument("--raw-feed-dir", default="/opt/binance-futures-agent/data/raw-feed")
    parser.add_argument("--since", default="2026-06-20T00:00:00Z")
    parser.add_argument("--until", default="")
    parser.add_argument("--leg", default="trend", help="strategy leg to label, or 'any'")
    parser.add_argument("--regime", default="TREND", help="regime label to require, or 'any'")
    parser.add_argument("--decision", default="trade", help="setup decision to require, or 'any'")
    parser.add_argument("--horizon-seconds", type=int, default=10_800)
    parser.add_argument("--default-wait-seconds", type=int, default=75)
    parser.add_argument("--dead-zone-percent", type=float, default=0.12)
    parser.add_argument("--min-coverage-fraction", type=float, default=0.50)
    parser.add_argument("--raw-file-padding-minutes", type=int, default=30)
    parser.add_argument("--raw-workers", type=int, default=1, help="parallel gzip readers for raw-feed parsing")
    parser.add_argument("--val-fraction", type=float, default=0.35)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--max-setups", type=int, default=0)
    parser.add_argument("--order", choices=("asc", "desc"), default="asc", help="setup sampling order before max-setups filtering")
    parser.add_argument("--raw-scan-symbol-limit", type=int, default=0, help="debug: only scan first N symbols after setup filtering")
    parser.add_argument("--out-dir", default="/opt/binance-futures-agent/results/research/ldc_actual")
    parser.add_argument("--artifact", default="", help="optional output .npz artifact path")
    args = parser.parse_args()

    since = parse_iso(clean_arg(args.since))
    until = parse_iso(clean_arg(args.until)) if clean_arg(args.until) else datetime.now(UTC)
    out_dir = Path(clean_arg(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_read_only(args.db)
    try:
        setups = load_setup_samples(
            conn,
            since=since,
            until=until,
            leg=args.leg,
            regime=args.regime,
            decision=args.decision,
            default_wait_seconds=max(1, int(args.default_wait_seconds)),
            max_setups=max(0, int(args.max_setups)),
            order=str(args.order),
        )
    finally:
        conn.close()

    symbols = sorted({sample.symbol for sample in setups})
    if int(args.raw_scan_symbol_limit) > 0:
        symbols = symbols[: int(args.raw_scan_symbol_limit)]
        setups = [sample for sample in setups if sample.symbol in set(symbols)]
    ticks_by_symbol: dict[str, list[Tick]] = {}
    if setups:
        start = min(sample.occurred_at for sample in setups) - timedelta(seconds=5)
        end = max(sample.occurred_at for sample in setups) + timedelta(seconds=max(1, args.horizon_seconds) + max(1, args.default_wait_seconds) + 5)
        ticks_by_symbol = load_raw_trade_ticks(
            Path(clean_arg(args.raw_feed_dir)),
            symbols=symbols,
            start=start,
            end=end,
            file_padding_minutes=max(0, int(args.raw_file_padding_minutes)),
            workers=max(1, int(args.raw_workers)),
        )

    labeled = [
        label_setup_path(
            sample,
            ticks_by_symbol.get(sample.symbol, []),
            horizon_seconds=max(1, int(args.horizon_seconds)),
            dead_zone_percent=max(0.0, float(args.dead_zone_percent)),
            min_coverage_fraction=max(0.0, min(1.0, float(args.min_coverage_fraction))),
        )
        for sample in setups
    ]
    report = build_report(
        labeled,
        feature_names=FEATURE_NAMES,
        k=max(1, int(args.k)),
        val_fraction=max(0.05, min(0.80, float(args.val_fraction))),
    )

    artifact_path = Path(clean_arg(args.artifact)) if clean_arg(args.artifact) else out_dir / "ldc_actual_reference.npz"
    if report["calibration"]["train_samples"] > 0:
        artifact = make_ldc_artifact(labeled, k=max(1, int(args.k)), report=report)
        save_ldc_artifact(artifact, artifact_path)
        report["artifact_path"] = str(artifact_path)
    else:
        report["artifact_path"] = None

    report_path = out_dir / "actual_setup_ldc_report.json"
    rows_path = out_dir / "actual_setup_tick_labels.csv"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_rows_csv(rows_path, labeled)

    print(json.dumps({
        "report": str(report_path),
        "rows": str(rows_path),
        "artifact": report.get("artifact_path"),
        "summary": report["summary"],
        "calibration": report["calibration"],
    }, ensure_ascii=False, indent=2))
    return 0


def connect_read_only(db_path: str) -> sqlite3.Connection:
    path = Path(clean_arg(db_path))
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_setup_samples(
    conn: sqlite3.Connection,
    *,
    since: datetime,
    until: datetime,
    leg: str,
    regime: str,
    decision: str,
    default_wait_seconds: int,
    max_setups: int = 0,
    order: str = "asc",
) -> list[SetupSample]:
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(trade_setups)").fetchall()}
    payload_col = "payload_json" if "payload_json" in columns else "payload"
    if payload_col not in columns:
        return []
    params: list[Any] = [iso(since), iso(until)]
    order_sql = "DESC" if order.lower() == "desc" else "ASC"
    rows = conn.execute(
        f"""
        SELECT id, event_id, occurred_at, symbol, ref_id, {payload_col} AS payload
        FROM trade_setups
        WHERE occurred_at >= ? AND occurred_at <= ?
        ORDER BY occurred_at {order_sql}, id {order_sql}
        """,
        params,
    ).fetchall()
    samples: list[SetupSample] = []
    for row in rows:
        sample = sample_from_trade_setup_row(row, default_wait_seconds=default_wait_seconds)
        if sample is None:
            continue
        if leg.lower() != "any" and sample.strategy_leg.lower() != leg.lower():
            continue
        if regime.lower() != "any" and sample.regime_label.upper() != regime.upper():
            continue
        if decision.lower() != "any" and sample.decision.lower() != decision.lower():
            continue
        samples.append(sample)
        if max_setups > 0 and len(samples) >= max_setups:
            break
    samples.sort(key=lambda item: item.occurred_at)
    return samples


def sample_from_trade_setup_row(row: Mapping[str, Any], *, default_wait_seconds: int = 75) -> SetupSample | None:
    payload = parse_json(row_get(row, "payload"))
    setup = as_dict(payload.get("setup"))
    candidate = as_dict(payload.get("candidate"))
    features = as_dict(candidate.get("features"))
    price_basis = as_dict(setup.get("price_basis"))
    entry_basis = as_dict(price_basis.get("entry_basis"))
    route = as_dict(price_basis.get("regime_router"))
    symbol = str(setup.get("symbol") or candidate.get("symbol") or row_get(row, "symbol") or "").upper()
    side = normalize_setup_side(setup.get("side"))
    occurred_at = parse_iso(str(row_get(row, "occurred_at") or ""))
    entry = first_float(setup.get("entry_price"), price_basis.get("entry_price"))
    stop = first_float(setup.get("stop_price"), price_basis.get("stop_price"))
    target = first_float(setup.get("target_price"), price_basis.get("target_price"))
    if not symbol or side not in {"long", "short"}:
        return None
    wait_seconds = int(first_float(entry_basis.get("limit_entry_max_wait_seconds")) or default_wait_seconds)
    strategy_leg = str(
        features.get("strategy_leg")
        or candidate.get("strategy_leg")
        or route.get("strategy_leg")
        or "trend"
    )
    return SetupSample(
        row_id=int(row_get(row, "id") or 0),
        event_id=int(row_get(row, "event_id")) if row_get(row, "event_id") is not None else None,
        occurred_at=occurred_at,
        symbol=symbol,
        side=side,
        strategy_leg=strategy_leg,
        regime_label=str(route.get("regime_label") or features.get("regime_label") or ""),
        route_decision=str(route.get("route_decision") or features.get("route_decision") or ""),
        decision=str(setup.get("decision") or ""),
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        wait_seconds=max(1, wait_seconds),
        confidence=first_float(setup.get("confidence")),
        edge_score=first_float(setup.get("edge_score")),
        risk_reward_ratio=first_float(setup.get("risk_reward_ratio"), price_basis.get("risk_reward_ratio")),
        features=dict(features),
        setup=dict(setup),
        candidate=dict(candidate),
    )


def load_raw_trade_ticks(
    raw_feed_dir: Path,
    *,
    symbols: Iterable[str],
    start: datetime,
    end: datetime,
    file_padding_minutes: int = 30,
    workers: int = 1,
) -> dict[str, list[Tick]]:
    symbol_set = {symbol.upper() for symbol in symbols}
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    out: dict[str, list[Tick]] = {symbol: [] for symbol in symbol_set}
    if not raw_feed_dir.exists() or not symbol_set:
        return out
    files = [
        path
        for path in sorted(raw_feed_dir.glob("binance-usdm-raw-*.gz"))
        if raw_file_may_overlap_tight(path, start=start, end=end, padding_minutes=file_padding_minutes)
    ]
    if workers <= 1 or len(files) <= 1:
        chunks = [
            parse_raw_trade_file((str(path), tuple(symbol_set), start_ms, end_ms))
            for path in files
        ]
    else:
        chunks = []
        with ProcessPoolExecutor(max_workers=min(workers, len(files))) as pool:
            futures = [
                pool.submit(parse_raw_trade_file, (str(path), tuple(symbol_set), start_ms, end_ms))
                for path in files
            ]
            for future in as_completed(futures):
                chunks.append(future.result())
    for chunk in chunks:
        for symbol, rows in chunk.items():
            out.setdefault(symbol, []).extend(Tick(event_ms=event_ms, price=price, quantity=qty) for event_ms, price, qty in rows)
    for rows in out.values():
        rows.sort(key=lambda tick: tick.event_ms)
    return out


def parse_raw_trade_file(args: tuple[str, tuple[str, ...], int, int]) -> dict[str, list[tuple[int, float, float]]]:
    path_text, symbols, start_ms, end_ms = args
    symbol_set = set(symbols)
    out: dict[str, list[tuple[int, float, float]]] = {symbol: [] for symbol in symbol_set}
    try:
        handle = gzip.open(path_text, "rt", encoding="utf-8", errors="replace")
    except OSError:
        return out
    try:
        with handle:
            for line in handle:
                local_ns = raw_line_local_timestamp_ns(line)
                if local_ns is not None:
                    local_ms = local_ns // 1_000_000
                    if local_ms < start_ms - 300_000:
                        continue
                    if local_ms > end_ms + 300_000:
                        break
                if "@trade" not in line:
                    continue
                parsed = parse_raw_trade_line(line)
                if parsed is None:
                    continue
                symbol, event_ms, price, qty = parsed
                if price <= 0 or qty <= 0:
                    continue
                if symbol in symbol_set and start_ms <= event_ms <= end_ms:
                    out.setdefault(symbol, []).append((event_ms, price, qty))
    except (EOFError, OSError):
        return out
    return out


def raw_file_may_overlap_tight(path: Path, *, start: datetime, end: datetime, padding_minutes: int) -> bool:
    file_time = raw_file_start_time(path)
    if file_time is None:
        return True
    padding = timedelta(minutes=max(0, padding_minutes))
    return start - padding <= file_time <= end + timedelta(minutes=10)


def raw_file_start_time(path: Path) -> datetime | None:
    marker = "binance-usdm-raw-"
    if marker not in path.name:
        return None
    stamp = path.name.split(marker, 1)[1].split(".", 1)[0]
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def raw_line_local_timestamp_ns(line: str) -> int | None:
    if not line or not line[0].isdigit():
        return None
    head = line.split(" ", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def label_setup_path(
    sample: SetupSample,
    ticks: list[Tick],
    *,
    horizon_seconds: int,
    dead_zone_percent: float,
    min_coverage_fraction: float,
) -> dict[str, Any]:
    start_ms = int(sample.occurred_at.timestamp() * 1000)
    wait_end_ms = start_ms + sample.wait_seconds * 1000
    horizon_end_ms = start_ms + horizon_seconds * 1000
    window_ticks = [tick for tick in ticks if start_ms <= tick.event_ms <= horizon_end_ms]
    coverage = tick_coverage_fraction(window_ticks, start_ms=start_ms, end_ms=horizon_end_ms)
    base = row_base(sample, coverage_fraction=coverage, raw_tick_count=len(window_ticks))
    if sample.entry_price is None or sample.stop_price is None or sample.target_price is None:
        return {**base, "status": "missing_geometry", "label": 0, "label_reason": "missing_entry_stop_or_target"}
    if not window_ticks:
        return {**base, "status": "no_raw_ticks", "label": 0, "label_reason": "no_raw_ticks"}
    if coverage < min_coverage_fraction:
        base["low_coverage"] = True

    fill_tick = first_fill_tick(
        window_ticks,
        side=sample.side,
        entry=sample.entry_price,
        wait_end_ms=wait_end_ms,
    )
    if fill_tick is None:
        last_price = window_ticks[-1].price
        return {
            **base,
            "status": "no_fill",
            "label": 0,
            "label_reason": "limit_not_touched_within_wait",
            "last_price": last_price,
            "horizon_return_percent": percent_delta(sample.entry_price, last_price),
        }

    exit_hit = first_exit_hit(
        window_ticks,
        side=sample.side,
        stop=sample.stop_price,
        target=sample.target_price,
        start_ms=fill_tick.event_ms,
    )
    path = path_extremes(window_ticks, side=sample.side, entry=sample.entry_price, start_ms=fill_tick.event_ms)
    result = {
        **base,
        **path,
        "fill_time": iso_ms(fill_tick.event_ms),
        "fill_latency_seconds": round((fill_tick.event_ms - start_ms) / 1000.0, 3),
        "fill_price": fill_tick.price,
        "entry_slippage_percent": percent_delta(sample.entry_price, fill_tick.price),
        "low_coverage": coverage < min_coverage_fraction,
    }
    if exit_hit is None:
        last_price = window_ticks[-1].price
        direction_label = horizon_direction_label(
            entry=sample.entry_price,
            last_price=last_price,
            dead_zone_percent=dead_zone_percent,
        )
        return {
            **result,
            "status": "no_exit",
            "label": direction_label,
            "label_reason": "horizon_return_after_fill",
            "last_price": last_price,
            "horizon_return_percent": percent_delta(sample.entry_price, last_price),
            "setup_won": None,
        }

    hit_type, hit_tick = exit_hit
    label = side_sign(sample.side) if hit_type == "target" else -side_sign(sample.side)
    later_target = False
    if hit_type == "stop":
        later_target = any(target_touched(sample.side, tick.price, sample.target_price) for tick in window_ticks if tick.event_ms > hit_tick.event_ms)
    return {
        **result,
        "status": "target_first" if hit_type == "target" else "stop_first",
        "label": label,
        "label_reason": "target_before_stop" if hit_type == "target" else "stop_before_target",
        "setup_won": hit_type == "target",
        "first_exit_time": iso_ms(hit_tick.event_ms),
        "seconds_fill_to_exit": round((hit_tick.event_ms - fill_tick.event_ms) / 1000.0, 3),
        "first_exit_price": hit_tick.price,
        "stop_first_but_later_target": bool(later_target),
        "direction_correct_after_stop": bool(later_target),
    }


def first_fill_tick(ticks: list[Tick], *, side: str, entry: float, wait_end_ms: int) -> Tick | None:
    for tick in ticks:
        if tick.event_ms > wait_end_ms:
            break
        if side == "long" and tick.price <= entry:
            return tick
        if side == "short" and tick.price >= entry:
            return tick
    return None


def first_exit_hit(
    ticks: list[Tick],
    *,
    side: str,
    stop: float,
    target: float,
    start_ms: int,
) -> tuple[str, Tick] | None:
    for tick in ticks:
        if tick.event_ms < start_ms:
            continue
        if target_touched(side, tick.price, target):
            return "target", tick
        if stop_touched(side, tick.price, stop):
            return "stop", tick
    return None


def target_touched(side: str, price: float, target: float) -> bool:
    return price >= target if side == "long" else price <= target


def stop_touched(side: str, price: float, stop: float) -> bool:
    return price <= stop if side == "long" else price >= stop


def path_extremes(ticks: list[Tick], *, side: str, entry: float, start_ms: int) -> dict[str, Any]:
    after = [tick for tick in ticks if tick.event_ms >= start_ms]
    if not after:
        return {}
    high_tick = max(after, key=lambda tick: tick.price)
    low_tick = min(after, key=lambda tick: tick.price)
    favorable_price = high_tick.price if side == "long" else low_tick.price
    adverse_price = low_tick.price if side == "long" else high_tick.price
    return {
        "max_high_price": high_tick.price,
        "max_high_time": iso_ms(high_tick.event_ms),
        "min_low_price": low_tick.price,
        "min_low_time": iso_ms(low_tick.event_ms),
        "max_favorable_percent": abs(percent_delta(entry, favorable_price)),
        "max_adverse_percent": abs(percent_delta(entry, adverse_price)),
    }


def tick_coverage_fraction(ticks: list[Tick], *, start_ms: int, end_ms: int) -> float:
    total_seconds = max(1, int((end_ms - start_ms) / 1000))
    seconds = {int((tick.event_ms - start_ms) / 1000) for tick in ticks if start_ms <= tick.event_ms <= end_ms}
    return round(min(1.0, len(seconds) / total_seconds), 6)


def row_base(sample: SetupSample, *, coverage_fraction: float, raw_tick_count: int) -> dict[str, Any]:
    feature_row, missing = ldc_feature_row(sample.features)
    return {
        "row_id": sample.row_id,
        "event_id": sample.event_id,
        "occurred_at": iso(sample.occurred_at),
        "symbol": sample.symbol,
        "side": sample.side,
        "strategy_leg": sample.strategy_leg,
        "regime_label": sample.regime_label,
        "route_decision": sample.route_decision,
        "decision": sample.decision,
        "entry_price": sample.entry_price,
        "stop_price": sample.stop_price,
        "target_price": sample.target_price,
        "wait_seconds": sample.wait_seconds,
        "confidence": sample.confidence,
        "edge_score": sample.edge_score,
        "risk_reward_ratio": sample.risk_reward_ratio,
        "raw_tick_count": raw_tick_count,
        "coverage_fraction": coverage_fraction,
        "low_coverage": False,
        "ldc_missing_features": ",".join(missing),
        **{name: value for name, value in zip(FEATURE_NAMES, feature_row)},
    }


def build_report(
    rows: list[dict[str, Any]],
    *,
    feature_names: tuple[str, ...],
    k: int,
    val_fraction: float,
) -> dict[str, Any]:
    summary = summarize_rows(rows)
    calibration = calibrate_ldc(rows, feature_names=feature_names, k=k, val_fraction=val_fraction)
    return {
        "schema": "bfa_actual_setup_tick_ldc_calibration_v1",
        "generated_at": iso(datetime.now(UTC)),
        "feature_names": list(feature_names),
        "summary": summary,
        "status_counts": count_by(rows, "status"),
        "symbol_counts": count_by(rows, "symbol"),
        "side_counts": count_by(rows, "side"),
        "calibration": calibration,
        "interpretation": {
            "no_fill": "setup limit entry was not touched inside its wait window; exclude from fill-outcome training",
            "stop_first_but_later_target": "direction may have been right, but stop/entry geometry was too tight for the tick path",
            "low_coverage": "raw trade ticks are sparse for the label horizon; use these rows as diagnostics, not strong training labels",
        },
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    filled = [row for row in rows if row.get("fill_time")]
    wins = [row for row in rows if row.get("setup_won") is True]
    losses = [row for row in rows if row.get("setup_won") is False]
    low_coverage = [row for row in rows if row.get("low_coverage")]
    stop_later_target = [row for row in rows if row.get("stop_first_but_later_target")]
    return {
        "rows": len(rows),
        "filled": len(filled),
        "no_fill": sum(1 for row in rows if row.get("status") == "no_fill"),
        "no_raw_ticks": sum(1 for row in rows if row.get("status") == "no_raw_ticks"),
        "target_first": len(wins),
        "stop_first": len(losses),
        "win_rate_filled_clear": round(len(wins) / (len(wins) + len(losses)), 4) if wins or losses else 0.0,
        "stop_first_but_later_target": len(stop_later_target),
        "stop_later_target_fraction_of_losses": round(len(stop_later_target) / len(losses), 4) if losses else 0.0,
        "low_coverage_rows": len(low_coverage),
        "mean_coverage_fraction": round(avg(row.get("coverage_fraction") for row in rows), 4),
        "mean_fill_latency_seconds": round(avg(row.get("fill_latency_seconds") for row in filled), 4),
    }


def calibrate_ldc(
    rows: list[dict[str, Any]],
    *,
    feature_names: tuple[str, ...],
    k: int,
    val_fraction: float,
) -> dict[str, Any]:
    candidates = [row for row in rows if usable_training_row(row, feature_names)]
    if len(candidates) < max(10, k + 2):
        return {
            "status": "insufficient_samples",
            "usable_samples": len(candidates),
            "train_samples": 0,
            "val_samples": 0,
            "recommendation": "keep_ldc_disabled",
        }
    candidates.sort(key=lambda row: str(row.get("occurred_at") or ""))
    split = max(1, int(len(candidates) * (1.0 - val_fraction)))
    split = min(split, len(candidates) - 1)
    train = candidates[:split]
    val = candidates[split:]
    train_x = np.array([[float(row[name]) for name in feature_names] for row in train], dtype=float)
    train_y = np.array([int(row["label"]) for row in train], dtype=int)
    val_x = np.array([[float(row[name]) for name in feature_names] for row in val], dtype=float)
    val_y = np.array([int(row["label"]) for row in val], dtype=int)
    val_sides = [str(row.get("side") or "") for row in val]
    mean = train_x.mean(axis=0)
    std = np.where(train_x.std(axis=0) == 0, 1.0, train_x.std(axis=0))
    train_x_std = (train_x - mean) / std
    agreements = []
    correct = []
    for i, row in enumerate(val_x):
        side = val_sides[i]
        agreement, voters, dead = knn_agreement_for_row((row - mean) / std, train_x_std, train_y, k=k, side=side)
        agreements.append({"agreement": agreement, "voters": voters, "dead": dead})
        correct.append(val_y[i] == side_sign(side))
    base_win_rate = float(np.mean(correct)) if correct else 0.0
    sweep = lift_sweep(agreements, correct)
    viable = [item for item in sweep if item["n_passed_adjusted"] >= max(3, int(len(val) * 0.10)) and item["lift"] > 1.0]
    best = max(viable, key=lambda item: (item["lift"], item["win_rate_adjusted"])) if viable else None
    return {
        "status": "ok",
        "usable_samples": len(candidates),
        "train_samples": len(train),
        "val_samples": len(val),
        "label_counts": count_by(candidates, "label"),
        "base_win_rate": round(base_win_rate, 4),
        "mean_agreement": round(avg(item["agreement"] for item in agreements), 4),
        "opposed_fraction": round(sum(1 for item in agreements if item["agreement"] < 0) / len(agreements), 4) if agreements else 0.0,
        "blend_sweep": sweep,
        "recommended_blend": (
            {
                "strength": best["blend_strength"],
                "mode": best["blend_mode"],
                "lift": best["lift"],
                "reason": "max_lift_subject_to_min_n_passed",
            }
            if best
            else {"strength": 0.0, "mode": "linear", "lift": 0.0, "reason": "no_valid_lift"}
        ),
        "recommendation": "shadow_or_testnet_only" if best else "keep_ldc_disabled",
    }


def make_ldc_artifact(rows: list[dict[str, Any]], *, k: int, report: Mapping[str, Any]) -> LdcArtifact:
    training_rows = [row for row in rows if usable_training_row(row, FEATURE_NAMES)]
    training_rows.sort(key=lambda row: str(row.get("occurred_at") or ""))
    X = np.array([[float(row[name]) for name in FEATURE_NAMES] for row in training_rows], dtype=float)
    y = np.array([int(row["label"]) for row in training_rows], dtype=int)
    mean = X.mean(axis=0) if len(X) else np.zeros(len(FEATURE_NAMES))
    std = np.where(X.std(axis=0) == 0, 1.0, X.std(axis=0)) if len(X) else np.ones(len(FEATURE_NAMES))
    X_std = (X - mean) / std if len(X) else X
    return LdcArtifact(
        reference_x=X_std,
        reference_y=y,
        feature_names=FEATURE_NAMES,
        scaler_mean=mean,
        scaler_std=std,
        meta={
            "trained_at": iso(datetime.now(UTC)),
            "source": "actual_routed_trade_setups_raw_ticks",
            "n_reference": int(len(X_std)),
            "k": int(k),
            "report_summary": dict(report.get("summary", {})),
            "recommended_blend": dict(report.get("calibration", {}).get("recommended_blend", {})),
        },
        blend_modes_supported=("linear", "asymmetric"),
        reference_symbols=tuple(str(row.get("symbol") or "") for row in training_rows),
    )


def knn_agreement_for_row(
    query_std: np.ndarray,
    train_x_std: np.ndarray,
    train_y: np.ndarray,
    *,
    k: int,
    side: str,
) -> tuple[float, int, int]:
    if len(train_x_std) == 0:
        return 0.0, 0, 0
    k = min(k, len(train_x_std))
    distances = lorentzian_distance(query_std, train_x_std)
    idx = np.argpartition(distances, k - 1)[:k]
    labels = train_y[idx]
    voters = int(np.count_nonzero(labels != 0))
    dead = int(np.count_nonzero(labels == 0))
    if voters <= 0:
        return 0.0, 0, dead
    same = side_sign(side)
    same_votes = int(np.count_nonzero(labels == same))
    opposite_votes = voters - same_votes
    return float((same_votes - opposite_votes) / voters), voters, dead


def lift_sweep(agreements: list[dict[str, Any]], correct: list[bool]) -> list[dict[str, Any]]:
    strengths = (0.03, 0.05, 0.08, 0.10)
    modes = ("linear", "asymmetric")
    base_confs = (0.50, 0.56, 0.62)
    min_gate = 0.55
    correct_arr = np.array(correct, dtype=bool)
    agreement_arr = np.array([float(item["agreement"]) for item in agreements], dtype=float)
    sweep: list[dict[str, Any]] = []
    for strength in strengths:
        for mode in modes:
            deltas = np.array([blend_delta(value, blend_strength=strength, blend_mode=mode) for value in agreement_arr])
            for base in base_confs:
                unadjusted = np.full(len(correct_arr), base) >= min_gate
                adjusted = np.clip(base + deltas, 0.0, 0.95) >= min_gate
                n_unadj = int(unadjusted.sum())
                n_adj = int(adjusted.sum())
                wr_unadj = float(correct_arr[unadjusted].mean()) if n_unadj else 0.0
                wr_adj = float(correct_arr[adjusted].mean()) if n_adj else 0.0
                lift = wr_adj / wr_unadj if wr_unadj > 0 else 0.0
                sweep.append({
                    "blend_strength": strength,
                    "blend_mode": mode,
                    "base_conf": base,
                    "n_passed_unadjusted": n_unadj,
                    "win_rate_unadjusted": round(wr_unadj, 4),
                    "n_passed_adjusted": n_adj,
                    "win_rate_adjusted": round(wr_adj, 4),
                    "lift": round(lift, 4),
                    "net_rejected": int((unadjusted & ~adjusted).sum()),
                    "net_promoted": int((~unadjusted & adjusted).sum()),
                })
    return sweep


def blend_delta(agreement: float, *, blend_strength: float, blend_mode: str) -> float:
    penalty_mult = 1.6 if blend_mode == "asymmetric" and agreement < 0 else 1.0
    floor = -blend_strength * penalty_mult
    return float(max(floor, min(blend_strength, agreement * blend_strength * penalty_mult)))


def usable_training_row(row: Mapping[str, Any], feature_names: tuple[str, ...]) -> bool:
    if row.get("low_coverage"):
        return False
    if row.get("status") not in {"target_first", "stop_first", "no_exit"}:
        return False
    if int(row.get("label") or 0) == 0:
        return False
    if row.get("ldc_missing_features"):
        return False
    return all(is_finite(row.get(name)) for name in feature_names)


def ldc_feature_row(features: Mapping[str, Any]) -> tuple[list[float | None], list[str]]:
    row: list[float | None] = []
    missing: list[str] = []
    for name in FEATURE_NAMES:
        value = first_float(features.get(FEATURE_SOURCE_KEYS[name]))
        if value is None:
            missing.append(name)
        row.append(value)
    return row, missing


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "row_id", "event_id", "occurred_at", "symbol", "side", "strategy_leg",
        "regime_label", "route_decision", "decision", "status", "label",
        "label_reason", "setup_won", "stop_first_but_later_target",
        "direction_correct_after_stop", "entry_price", "stop_price",
        "target_price", "fill_time", "first_exit_time", "fill_latency_seconds",
        "seconds_fill_to_exit", "wait_seconds", "confidence", "edge_score",
        "risk_reward_ratio", "coverage_fraction", "raw_tick_count",
        "max_favorable_percent", "max_adverse_percent", "horizon_return_percent",
        "ldc_missing_features", *FEATURE_NAMES,
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def count_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def horizon_direction_label(*, entry: float, last_price: float, dead_zone_percent: float) -> int:
    move = percent_delta(entry, last_price)
    if move > dead_zone_percent:
        return 1
    if move < -dead_zone_percent:
        return -1
    return 0


def side_sign(side: str) -> int:
    return 1 if str(side).lower() == "long" else -1


def percent_delta(start: float, end: float) -> float:
    return ((end - start) / start) * 100.0 if start else 0.0


def avg(values: Iterable[Any]) -> float:
    nums = [float(value) for value in values if is_finite(value)]
    return sum(nums) / len(nums) if nums else 0.0


def first_float(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "" or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed:
            return parsed
    return None


def clean_arg(value: Any) -> str:
    return str(value or "").strip()


def is_finite(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed)


def row_get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if hasattr(row, "keys") and key in row.keys():  # sqlite3.Row
        return row[key]
    if isinstance(row, Mapping):
        return row.get(key, default)
    return default


def parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_setup_side(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"long", "buy"}:
        return "long"
    if text in {"short", "sell"}:
        return "short"
    return text


def parse_iso(value: str) -> datetime:
    if not value:
        raise ValueError("missing ISO timestamp")
    text = value
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    if "." in text and text.endswith("Z"):
        head, tail = text.split(".", 1)
        frac = tail[:-1]
        if len(frac) > 6:
            frac = frac[:6]
        text = f"{head}.{frac}Z"
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_ms(value_ms: int) -> str:
    return iso(datetime.fromtimestamp(value_ms / 1000.0, tz=UTC))


if __name__ == "__main__":
    raise SystemExit(main())
