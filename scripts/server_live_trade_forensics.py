"""Server-side read-only forensics for live closed futures trades.

The script joins closed live outcomes with their order intent, setup, AI
decision, exchange responses, persisted fills, and local raw public trade feed.
It does not call Binance and it does not mutate SQLite or exchange state.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import gzip
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen


BINANCE_FAPI = "https://fapi.binance.com"


@dataclass
class MinuteBar:
    symbol: str
    open_time_ms: int
    open: float
    high: float
    high_time_ms: int
    low: float
    low_time_ms: int
    close: float
    close_time_ms: int
    volume: float
    quote_volume: float
    trade_count: int
    source: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/opt/binance-futures-agent/data/agent.sqlite")
    parser.add_argument("--raw-feed-dir", default="/opt/binance-futures-agent/data/raw-feed")
    parser.add_argument("--since", default="2026-06-24T16:00:00Z")
    parser.add_argument("--until", default="")
    parser.add_argument("--pre-minutes", type=int, default=15)
    parser.add_argument("--post-minutes", type=int, default=15)
    parser.add_argument(
        "--price-source",
        choices=("public_1m", "snapshot", "raw"),
        default="public_1m",
        help="price path source; raw scans local gzip and is slow",
    )
    parser.add_argument("--out-dir", default="/tmp/live_trade_forensics_jun25_0000_bjt")
    args = parser.parse_args()

    since = parse_iso(args.since)
    until = parse_iso(args.until) if args.until else datetime.now(UTC)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        packet = build_packet(
            conn,
            raw_feed_dir=Path(args.raw_feed_dir),
            since=since,
            until=until,
            pre_minutes=args.pre_minutes,
            post_minutes=args.post_minutes,
            price_source=args.price_source,
        )
    finally:
        conn.close()

    write_csv(out_dir / "trades_forensics.csv", packet["trades"])
    write_csv(out_dir / "minute_path.csv", packet["minute_path"])
    write_csv(out_dir / "decision_flow.csv", packet["decision_flow"])
    write_csv(out_dir / "group_summary.csv", packet["group_summary"])
    (out_dir / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(render_report(packet), encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "trade_count": len(packet["trades"]),
        "minute_rows": len(packet["minute_path"]),
        "summary": packet["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


def build_packet(
    conn: sqlite3.Connection,
    *,
    raw_feed_dir: Path,
    since: datetime,
    until: datetime,
    pre_minutes: int,
    post_minutes: int,
    price_source: str,
) -> dict[str, Any]:
    outcomes = load_outcomes(conn, since=since, until=until)
    symbols = sorted({row["symbol"] for row in outcomes if row.get("symbol")})
    start = min((parse_iso(row["first_trade_time"]) for row in outcomes if row.get("first_trade_time")), default=since)
    end = max((parse_iso(row["last_trade_time"]) for row in outcomes if row.get("last_trade_time")), default=until)
    start -= timedelta(minutes=pre_minutes + 2)
    end += timedelta(minutes=post_minutes + 2)

    public_bars: dict[str, list[MinuteBar]] = {}
    raw_bars: dict[str, list[MinuteBar]] = {}
    snapshot_bars: dict[str, list[MinuteBar]] = {}
    if price_source == "public_1m":
        public_bars = load_public_1m_bars(symbols=symbols, start=start, end=end)
        snapshot_bars = load_snapshot_kline_bars(conn, symbols=symbols, start=start, end=end)
    elif price_source == "snapshot":
        snapshot_bars = load_snapshot_kline_bars(conn, symbols=symbols, start=start, end=end)
    else:
        raw_bars = load_raw_trade_minute_bars(raw_feed_dir, symbols=symbols, start=start, end=end)
        snapshot_bars = load_snapshot_kline_bars(conn, symbols=symbols, start=start, end=end)

    trades: list[dict[str, Any]] = []
    minute_rows: list[dict[str, Any]] = []
    flow_rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        intent_row = load_order_intent(conn, outcome["intent_event_id"])
        intent = as_dict(intent_row.get("payload", {}).get("intent"))
        decided_at = normalize_iso_text(str(intent.get("decided_at") or intent_row.get("occurred_at") or outcome["first_trade_time"]))
        setup_row = load_by_ref(conn, "trade_setups", f"trade_setup:{outcome['symbol']}:{decided_at}")
        candidate_row = load_by_ref(conn, "candidates", f"candidate:{outcome['symbol']}:{decided_at}")
        ai_row = load_by_ref(conn, "ai_decisions", f"ai_decision:{outcome['symbol']}:{decided_at}")
        exchange_rows = load_exchange_responses(conn, outcome["symbol"], decided_at)
        fill_rows = load_fills(conn, outcome["intent_event_id"])

        setup_payload = as_dict(setup_row.get("payload", {}).get("setup"))
        candidate_payload = as_dict(candidate_row.get("payload"))
        candidate_features = as_dict(candidate_payload.get("features"))
        price_basis = as_dict(setup_payload.get("price_basis"))
        route = as_dict(price_basis.get("regime_router"))
        fill_summary = summarize_trades(outcome["trades"], intent_side=str(intent.get("side") or outcome["side"]))

        side = normalize_side(intent.get("side") or outcome["side"])
        direction = "long" if side == "BUY" else "short" if side == "SELL" else normalize_direction(setup_payload.get("side"))
        entry = first_float(fill_summary.get("entry_avg_price"), outcome.get("entry_price"), intent.get("entry_price"), setup_payload.get("entry_price"))
        exit_price = first_float(fill_summary.get("exit_avg_price"))
        stop = first_float(intent.get("stop_price"), setup_payload.get("stop_price"))
        target = first_float(intent.get("target_price"), setup_payload.get("target_price"))
        first_trade_time = parse_iso(first_float_time(fill_summary.get("first_trade_time"), outcome.get("first_trade_time"), intent.get("occurred_at"), decided_at))
        last_trade_time = parse_iso(first_float_time(fill_summary.get("last_trade_time"), outcome.get("last_trade_time"), outcome.get("closed_at"), first_trade_time.isoformat()))
        order_time = parse_iso_or_none(intent_row.get("occurred_at")) or parse_iso_or_none(decided_at) or first_trade_time

        window_start = first_trade_time - timedelta(minutes=pre_minutes)
        window_end = last_trade_time + timedelta(minutes=post_minutes)
        bars, bar_source = choose_bars(
            public_bars.get(outcome["symbol"], []) or raw_bars.get(outcome["symbol"], []),
            snapshot_bars.get(outcome["symbol"], []),
            start=window_start,
            end=window_end,
        )
        path_rows, metrics = analyze_bars(
            bars,
            symbol=outcome["symbol"],
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
            order_time=order_time,
            first_trade_time=first_trade_time,
            last_trade_time=last_trade_time,
        )
        for row in path_rows:
            row["intent_event_id"] = outcome["intent_event_id"]
            row["outcome_event_id"] = outcome["outcome_event_id"]
        minute_rows.extend(path_rows)

        latency = as_dict(as_dict(intent.get("metadata")).get("latency"))
        trade = {
            "symbol": outcome["symbol"],
            "side": side,
            "direction": direction,
            "intent_event_id": outcome["intent_event_id"],
            "outcome_event_id": outcome["outcome_event_id"],
            "decided_at": decided_at,
            "order_created_at": intent_row.get("occurred_at"),
            "first_trade_time": iso(first_trade_time),
            "last_trade_time": iso(last_trade_time),
            "hold_seconds": round((last_trade_time - first_trade_time).total_seconds(), 3),
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop,
            "target_price": target,
            "quantity": first_float(intent.get("quantity")),
            "leverage": first_float(intent.get("leverage")),
            "notional_usdt": first_float(intent.get("notional_usdt")),
            "estimated_initial_margin_usdt": first_float(intent.get("estimated_initial_margin_usdt")),
            "gross_pnl_usdt": outcome["gross_pnl_usdt"],
            "fees_usdt": outcome["fees_usdt"],
            "net_pnl_usdt": outcome["net_pnl_usdt"],
            "trade_count": outcome["trade_count"],
            "entry_fill_qty": fill_summary.get("entry_qty"),
            "exit_fill_qty": fill_summary.get("exit_qty"),
            "entry_maker_count": fill_summary.get("entry_maker_count"),
            "exit_maker_count": fill_summary.get("exit_maker_count"),
            "setup_profile": outcome.get("setup_profile") or price_basis.get("profile"),
            "strategy_leg": candidate_features.get("strategy_leg") or as_dict(intent.get("metadata")).get("strategy_leg"),
            "regime_label": route.get("regime_label") or candidate_features.get("regime_label") or as_dict(intent.get("metadata")).get("regime_label"),
            "route_decision": route.get("route_decision") or candidate_features.get("route_decision") or as_dict(intent.get("metadata")).get("route_decision"),
            "setup_decision": setup_payload.get("decision"),
            "long_score": setup_payload.get("long_score"),
            "short_score": setup_payload.get("short_score"),
            "edge_score": setup_payload.get("edge_score"),
            "risk_reward_ratio_setup": setup_payload.get("risk_reward_ratio"),
            "stop_distance_percent_setup": setup_payload.get("stop_distance_percent"),
            "target_distance_percent_setup": setup_payload.get("target_distance_percent"),
            "bar_source": bar_source,
            "bar_count": len(bars),
            **metrics,
            "classification": classify_trade(float(outcome["net_pnl_usdt"]), metrics),
            "factor_reasons": "|".join(str(x) for x in list_or_empty(outcome.get("factor_reasons"))),
            "setup_reasons": "|".join(str(x) for x in list_or_empty(setup_payload.get("reasons"))),
            "regime_reason_codes": "|".join(str(x) for x in list_or_empty(route.get("regime_reason_codes") or candidate_features.get("regime_reason_codes"))),
            "entry_basis": compact_json(price_basis.get("entry_basis")),
            "stop_basis": compact_json(price_basis.get("stop_basis")),
            "target_basis": compact_json(price_basis.get("target_basis")),
            "top_factors": top_factors_text(setup_payload.get("factor_scores")),
            "ai_accepted": deep_get(ai_row, "payload", "validation", "accepted"),
            "ai_decision": deep_get(ai_row, "payload", "validation", "decision", "decision"),
            "ai_side": deep_get(ai_row, "payload", "validation", "decision", "side"),
            "ai_confidence": deep_get(ai_row, "payload", "validation", "decision", "confidence"),
            "exchange_response_types": "|".join(str(as_dict(row.get("payload")).get("response_type")) for row in exchange_rows),
            "db_fill_rows": len(fill_rows),
            "latency_signal_to_setup_ms": latency.get("signal_to_setup_finished_ms"),
            "latency_signal_to_ai_ms": latency.get("signal_to_ai_finished_ms"),
            "latency_signal_to_execution_ms": latency.get("signal_to_execution_telemetry_ms"),
            "latency_cache_to_candidate_ms": latency.get("cache_to_candidate_ms"),
            "latency_source": latency.get("source"),
        }
        trades.append(trade)
        flow_rows.extend(decision_flow_rows(trade, intent_row, setup_row, candidate_row, ai_row, exchange_rows))

    return {
        "schema": "bfa_server_live_trade_forensics_v1",
        "generated_at": iso(datetime.now(UTC)),
        "filters": {
            "since": iso(since),
            "until": iso(until),
            "pre_minutes": pre_minutes,
            "post_minutes": post_minutes,
            "price_source": price_source,
        },
        "summary": summarize(trades),
        "group_summary": summarize_groups(trades),
        "trades": trades,
        "minute_path": minute_rows,
        "decision_flow": flow_rows,
    }


def load_outcomes(conn: sqlite3.Connection, *, since: datetime, until: datetime) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, event_id, occurred_at, symbol, ref_id, payload_json
        FROM outcomes
        WHERE occurred_at >= ? AND occurred_at <= ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (iso(since), iso(until)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = parse_json(row["payload_json"])
        intent = as_dict(payload.get("intent"))
        trades = [as_dict(item) for item in list_or_empty(payload.get("trades"))]
        out.append({
            "outcome_row_id": row["id"],
            "outcome_event_id": row["event_id"],
            "closed_at": payload.get("last_trade_time") or row["occurred_at"],
            "symbol": str(payload.get("symbol") or row["symbol"] or intent.get("symbol") or "").upper(),
            "side": str(intent.get("side") or payload.get("side") or "").upper(),
            "intent_event_id": int_or_none(intent.get("event_id")),
            "first_trade_time": payload.get("first_trade_time") or intent.get("occurred_at"),
            "last_trade_time": payload.get("last_trade_time") or row["occurred_at"],
            "entry_price": first_trade_price(trades),
            "gross_pnl_usdt": float_or_zero(payload.get("gross_realized_pnl_usdt")),
            "fees_usdt": float_or_zero(payload.get("commission_usdt")),
            "net_pnl_usdt": float_or_zero(payload.get("net_realized_pnl_usdt")),
            "trade_count": int_or_none(payload.get("trade_count")) or 0,
            "setup_profile": payload.get("setup_profile"),
            "factor_reasons": payload.get("factor_reasons"),
            "trades": trades,
        })
    return out


def load_order_intent(conn: sqlite3.Connection, event_id: int | None) -> dict[str, Any]:
    if event_id is None:
        return {}
    row = conn.execute(
        """
        SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
        FROM order_intents
        WHERE event_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    return artifact_from_row(row) if row else {}


def load_by_ref(conn: sqlite3.Connection, table: str, ref_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"""
        SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
        FROM {table}
        WHERE ref_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (ref_id,),
    ).fetchone()
    return artifact_from_row(row) if row else {}


def load_exchange_responses(conn: sqlite3.Connection, symbol: str, decided_at: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
        FROM exchange_responses
        WHERE symbol = ? AND ref_id LIKE ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (symbol, f"exchange_response:%:{symbol}:{decided_at}"),
    ).fetchall()
    return [artifact_from_row(row) for row in rows]


def load_fills(conn: sqlite3.Connection, event_id: int | None) -> list[dict[str, Any]]:
    if event_id is None:
        return []
    rows = conn.execute(
        """
        SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
        FROM fills
        WHERE event_id = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (event_id,),
    ).fetchall()
    return [artifact_from_row(row) for row in rows]


def artifact_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "occurred_at": row["occurred_at"],
        "source": row["source"],
        "symbol": row["symbol"],
        "ref_id": row["ref_id"],
        "payload": parse_json(row["payload_json"]),
    }


def load_raw_trade_minute_bars(
    raw_feed_dir: Path,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[MinuteBar]]:
    symbol_set = set(symbols)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    buckets: dict[tuple[str, int], MinuteBar] = {}
    if not raw_feed_dir.exists():
        return {}
    for path in sorted(raw_feed_dir.glob("*.gz")):
        if not raw_file_may_overlap(path, start=start, end=end):
            continue
        try:
            handle = gzip.open(path, "rt", encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            with handle:
                for line in handle:
                    parsed = parse_raw_trade_line(line)
                    if parsed is None:
                        continue
                    symbol, event_ms, price, qty = parsed
                    if symbol not in symbol_set or event_ms < start_ms or event_ms > end_ms:
                        continue
                    minute_ms = (event_ms // 60_000) * 60_000
                    key = (symbol, minute_ms)
                    existing = buckets.get(key)
                    if existing is None:
                        buckets[key] = MinuteBar(
                            symbol=symbol,
                            open_time_ms=minute_ms,
                            open=price,
                            high=price,
                            high_time_ms=event_ms,
                            low=price,
                            low_time_ms=event_ms,
                            close=price,
                            close_time_ms=event_ms,
                            volume=qty,
                            quote_volume=price * qty,
                            trade_count=1,
                            source="raw_trade_1m",
                        )
                        continue
                    if price >= existing.high:
                        existing.high = price
                        existing.high_time_ms = event_ms
                    if price <= existing.low:
                        existing.low = price
                        existing.low_time_ms = event_ms
                    existing.close = price
                    existing.close_time_ms = event_ms
                    existing.volume += qty
                    existing.quote_volume += price * qty
                    existing.trade_count += 1
        except (EOFError, OSError):
            continue
    out: dict[str, list[MinuteBar]] = {}
    for bar in buckets.values():
        out.setdefault(bar.symbol, []).append(bar)
    for rows in out.values():
        rows.sort(key=lambda item: item.open_time_ms)
    return out


def load_public_1m_bars(
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[MinuteBar]]:
    out: dict[str, list[MinuteBar]] = {}
    for symbol in symbols:
        out[symbol] = fetch_public_klines(symbol, start=start, end=end, interval="1m")
        time.sleep(0.08)
    return out


def fetch_public_klines(symbol: str, *, start: datetime, end: datetime, interval: str) -> list[MinuteBar]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[MinuteBar] = []
    cursor = start_ms
    while cursor <= end_ms:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1500,
            }
        )
        with urlopen(f"{BINANCE_FAPI}/fapi/v1/klines?{query}", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            if not isinstance(item, list) or len(item) < 11:
                continue
            open_time = int(item[0])
            high = float(item[2])
            low = float(item[3])
            rows.append(
                MinuteBar(
                    symbol=symbol,
                    open_time_ms=open_time,
                    open=float(item[1]),
                    high=high,
                    high_time_ms=open_time,
                    low=low,
                    low_time_ms=open_time,
                    close=float(item[4]),
                    close_time_ms=int(item[6]),
                    volume=float(item[5]),
                    quote_volume=float(item[7]),
                    trade_count=int(item[8]),
                    source="public_1m",
                )
            )
        last_open = int(payload[-1][0])
        next_cursor = last_open + 60_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < 1500:
            break
        time.sleep(0.08)
    return rows


def parse_raw_trade_line(line: str) -> tuple[str, int, float, float] | None:
    text = line.strip()
    if not text:
        return None
    if text and text[0].isdigit() and " " in text:
        text = text.split(" ", 1)[1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("e") or "").lower()
    if event_type != "trade":
        return None
    symbol = str(payload.get("s") or "").upper()
    event_ms = int_or_none(payload.get("T") or payload.get("E"))
    price = float_or_none(payload.get("p"))
    qty = float_or_none(payload.get("q")) or 0.0
    if not symbol or event_ms is None or price is None:
        return None
    return symbol, event_ms, price, qty


def raw_file_may_overlap(path: Path, *, start: datetime, end: datetime) -> bool:
    marker = "binance-usdm-raw-"
    if marker not in path.name:
        return True
    stamp = path.name.split(marker, 1)[1].split(".", 1)[0]
    try:
        file_time = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return True
    return start - timedelta(hours=3) <= file_time <= end + timedelta(hours=3)


def load_snapshot_kline_bars(
    conn: sqlite3.Connection,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[MinuteBar]]:
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    params: list[Any] = list(symbols)
    params.extend([int(start.timestamp() * 1000), int(end.timestamp() * 1000)])
    rows = conn.execute(
        f"""
        SELECT symbol, occurred_at, payload_json
        FROM market_snapshots
        WHERE symbol IN ({placeholders})
          AND CAST(occurred_at AS INTEGER) >= ?
          AND CAST(occurred_at AS INTEGER) <= ?
          AND json_extract(payload_json, '$.event_type') = 'kline'
        ORDER BY symbol ASC, CAST(occurred_at AS INTEGER) ASC
        """,
        params,
    ).fetchall()
    out: dict[str, list[MinuteBar]] = {}
    seen: set[tuple[str, int]] = set()
    for row in rows:
        symbol = str(row["symbol"] or "").upper()
        payload = as_dict(parse_json(row["payload_json"]).get("payload"))
        interval = str(payload.get("interval") or "")
        if interval not in {"1m", "5m"}:
            continue
        open_time = int_or_none(payload.get("open_time") or row["occurred_at"])
        if open_time is None or (symbol, open_time) in seen:
            continue
        seen.add((symbol, open_time))
        high = float_or_zero(payload.get("high"))
        low = float_or_zero(payload.get("low"))
        out.setdefault(symbol, []).append(
            MinuteBar(
                symbol=symbol,
                open_time_ms=open_time,
                open=float_or_zero(payload.get("open")),
                high=high,
                high_time_ms=open_time,
                low=low,
                low_time_ms=open_time,
                close=float_or_zero(payload.get("close")),
                close_time_ms=int_or_none(payload.get("close_time")) or open_time + (299_999 if interval == "5m" else 59_999),
                volume=float_or_zero(payload.get("volume")),
                quote_volume=float_or_zero(payload.get("quote_volume")),
                trade_count=int_or_none(payload.get("trade_count")) or 0,
                source=f"snapshot_{interval}",
            )
        )
    return out


def choose_bars(
    raw: list[MinuteBar],
    snapshots: list[MinuteBar],
    *,
    start: datetime,
    end: datetime,
) -> tuple[list[MinuteBar], str]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    raw_rows = [bar for bar in raw if start_ms <= bar.open_time_ms <= end_ms]
    if raw_rows:
        sources = sorted({bar.source for bar in raw_rows})
        return raw_rows, "|".join(sources) if sources else "minute_bars"
    fallback = [bar for bar in snapshots if start_ms <= bar.open_time_ms <= end_ms]
    return fallback, fallback[0].source if fallback else "none"


def analyze_bars(
    bars: list[MinuteBar],
    *,
    symbol: str,
    direction: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
    order_time: datetime,
    first_trade_time: datetime,
    last_trade_time: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if entry is None or direction not in {"long", "short"}:
        return [], empty_metrics("missing_entry_or_direction")
    stop_distance_pct = abs(entry - stop) / entry * 100.0 if stop else None
    target_distance_pct = abs(target - entry) / entry * 100.0 if target else None
    first_floor_ms = int(first_trade_time.replace(second=0, microsecond=0).timestamp() * 1000)
    last_floor_ms = int(last_trade_time.replace(second=0, microsecond=0).timestamp() * 1000)
    pre: list[MinuteBar] = []
    active: list[MinuteBar] = []
    post: list[MinuteBar] = []
    rows: list[dict[str, Any]] = []
    first_stop_ms: int | None = None
    first_target_ms: int | None = None
    for bar in bars:
        phase = "pre_entry" if bar.open_time_ms < first_floor_ms else "in_trade" if bar.open_time_ms <= last_floor_ms else "post_exit"
        if phase == "pre_entry":
            pre.append(bar)
        elif phase == "in_trade":
            active.append(bar)
        else:
            post.append(bar)
        fav = favorable_pct(bar, direction, entry)
        adv = adverse_pct(bar, direction, entry)
        close_ret = close_direction_pct(bar, direction, entry)
        stop_hit = touches_stop(bar, direction, stop)
        target_hit = touches_target(bar, direction, target)
        stop_ms = touch_time_ms(bar, direction, "stop") if stop_hit else None
        target_ms = touch_time_ms(bar, direction, "target") if target_hit else None
        if bar.open_time_ms >= first_floor_ms:
            if stop_ms is not None and (first_stop_ms is None or stop_ms < first_stop_ms):
                first_stop_ms = stop_ms
            if target_ms is not None and (first_target_ms is None or target_ms < first_target_ms):
                first_target_ms = target_ms
        rows.append({
            "symbol": symbol,
            "minute_open_time": epoch_ms_to_iso(bar.open_time_ms),
            "phase": phase,
            "direction": direction,
            "open": bar.open,
            "high": bar.high,
            "high_time": epoch_ms_to_iso(bar.high_time_ms),
            "low": bar.low,
            "low_time": epoch_ms_to_iso(bar.low_time_ms),
            "mid": round((bar.high + bar.low) / 2.0, 12),
            "close": bar.close,
            "close_time": epoch_ms_to_iso(bar.close_time_ms),
            "volume": bar.volume,
            "quote_volume": bar.quote_volume,
            "trade_count": bar.trade_count,
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "favorable_pct_from_entry": round(fav, 8),
            "adverse_pct_from_entry": round(adv, 8),
            "directional_close_pct": round(close_ret, 8),
            "stop_hit": stop_hit,
            "target_hit": target_hit,
            "source": bar.source,
        })
    active_and_post = active + post
    after_stop = [bar for bar in active_and_post if first_stop_ms is not None and bar.open_time_ms > first_stop_ms]
    mfe = max((favorable_pct(bar, direction, entry) for bar in active), default=0.0)
    mae = max((adverse_pct(bar, direction, entry) for bar in active), default=0.0)
    exit_dir = close_direction_pct(active[-1], direction, entry) if active else 0.0
    post_end_dir = close_direction_pct(post[-1], direction, entry) if post else None
    expected_minutes = expected_minute_count(bars)
    metrics = {
        "path_issue": "",
        "bar_coverage_ratio": round(len(bars) / expected_minutes, 6) if expected_minutes else 0.0,
        "entry_to_stop_pct": round(stop_distance_pct, 8) if stop_distance_pct is not None else None,
        "entry_to_target_pct": round(target_distance_pct, 8) if target_distance_pct is not None else None,
        "planned_rr": round(target_distance_pct / stop_distance_pct, 8) if stop_distance_pct and target_distance_pct else None,
        "pre_high": value_time(pre, "high", max),
        "pre_high_time": value_time(pre, "high", max, want_time=True),
        "pre_low": value_time(pre, "low", min),
        "pre_low_time": value_time(pre, "low", min, want_time=True),
        "entry_pos_in_pre_range": entry_position_in_range(entry, pre),
        "in_trade_high": value_time(active, "high", max),
        "in_trade_high_time": value_time(active, "high", max, want_time=True),
        "in_trade_low": value_time(active, "low", min),
        "in_trade_low_time": value_time(active, "low", min, want_time=True),
        "post_high": value_time(post, "high", max),
        "post_high_time": value_time(post, "high", max, want_time=True),
        "post_low": value_time(post, "low", min),
        "post_low_time": value_time(post, "low", min, want_time=True),
        "mfe_pct": round(mfe, 8),
        "mae_pct": round(mae, 8),
        "mfe_r": round(mfe / stop_distance_pct, 8) if stop_distance_pct else None,
        "mae_r": round(mae / stop_distance_pct, 8) if stop_distance_pct else None,
        "exit_directional_pct": round(exit_dir, 8),
        "giveback_from_mfe_pct": round(max(0.0, mfe - exit_dir), 8),
        "first_stop_touch_time": epoch_ms_to_iso(first_stop_ms) if first_stop_ms else "",
        "first_target_touch_time": epoch_ms_to_iso(first_target_ms) if first_target_ms else "",
        "first_touch": first_touch(first_stop_ms, first_target_ms),
        "target_after_stop": any(touches_target(bar, direction, target) for bar in after_stop),
        "entry_recovered_after_stop": any(recovered_entry(bar, direction, entry) for bar in after_stop),
        "post_exit_directional_pct": round(post_end_dir, 8) if post_end_dir is not None else None,
    }
    return rows, metrics


def empty_metrics(issue: str) -> dict[str, Any]:
    return {"path_issue": issue}


def summarize_trades(trades: list[dict[str, Any]], *, intent_side: str) -> dict[str, Any]:
    side = normalize_side(intent_side)
    entry_side = "BUY" if side == "BUY" else "SELL"
    exit_side = "SELL" if entry_side == "BUY" else "BUY"
    entry_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == entry_side]
    exit_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == exit_side]
    times = [int_or_none(trade.get("time")) for trade in trades]
    times = [t for t in times if t is not None]
    return {
        "entry_avg_price": weighted_avg_price(entry_trades),
        "exit_avg_price": weighted_avg_price(exit_trades),
        "entry_qty": round(sum(float_or_zero(t.get("qty")) for t in entry_trades), 12) if entry_trades else None,
        "exit_qty": round(sum(float_or_zero(t.get("qty")) for t in exit_trades), 12) if exit_trades else None,
        "entry_maker_count": sum(1 for t in entry_trades if bool(t.get("maker"))),
        "exit_maker_count": sum(1 for t in exit_trades if bool(t.get("maker"))),
        "first_trade_time": epoch_ms_to_iso(min(times)) if times else None,
        "last_trade_time": epoch_ms_to_iso(max(times)) if times else None,
    }


def decision_flow_rows(
    trade: dict[str, Any],
    intent_row: dict[str, Any],
    setup_row: dict[str, Any],
    candidate_row: dict[str, Any],
    ai_row: dict[str, Any],
    exchange_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = {
        "symbol": trade["symbol"],
        "intent_event_id": trade["intent_event_id"],
        "outcome_event_id": trade["outcome_event_id"],
        "decided_at": trade["decided_at"],
    }
    rows = [
        {
            **base,
            "stage": "candidate",
            "occurred_at": candidate_row.get("occurred_at"),
            "status": "present" if candidate_row else "missing",
            "detail": compact_json(candidate_row.get("payload")),
        },
        {
            **base,
            "stage": "setup",
            "occurred_at": setup_row.get("occurred_at"),
            "status": deep_get(setup_row, "payload", "setup", "decision"),
            "detail": compact_json(deep_get(setup_row, "payload", "setup")),
        },
        {
            **base,
            "stage": "ai",
            "occurred_at": ai_row.get("occurred_at"),
            "status": deep_get(ai_row, "payload", "validation", "accepted"),
            "detail": compact_json(deep_get(ai_row, "payload", "validation")),
        },
        {
            **base,
            "stage": "intent",
            "occurred_at": intent_row.get("occurred_at"),
            "status": deep_get(intent_row, "payload", "status"),
            "detail": compact_json(intent_row.get("payload")),
        },
    ]
    for item in exchange_rows:
        rows.append({
            **base,
            "stage": "exchange",
            "occurred_at": item.get("occurred_at"),
            "status": deep_get(item, "payload", "response_type"),
            "detail": compact_json(deep_get(item, "payload", "response")),
        })
    return rows


def classify_trade(net_pnl: float, metrics: dict[str, Any]) -> str:
    mfe_r = float_or_zero(metrics.get("mfe_r"))
    mae_r = float_or_zero(metrics.get("mae_r"))
    first = str(metrics.get("first_touch") or "")
    giveback = float_or_zero(metrics.get("giveback_from_mfe_pct"))
    if net_pnl < 0 and first == "stop" and bool(metrics.get("target_after_stop")):
        return "direction_ok_but_entry_or_stop_bad"
    if net_pnl < 0 and mfe_r < 0.35 and mae_r >= 0.8:
        return "wrong_direction_or_late_entry"
    if net_pnl < 0 and mfe_r >= 0.6 and giveback > 0:
        return "had_profit_but_exit_failed"
    if net_pnl > 0 and mfe_r >= 1.0 and giveback > 0:
        return "profit_but_gave_back"
    if net_pnl > 0:
        return "profit"
    return "loss"


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [t for t in trades if float_or_zero(t.get("net_pnl_usdt")) > 0]
    losses = [t for t in trades if float_or_zero(t.get("net_pnl_usdt")) < 0]
    gp = sum(float_or_zero(t.get("net_pnl_usdt")) for t in wins)
    gl = -sum(float_or_zero(t.get("net_pnl_usdt")) for t in losses)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades), 8) if trades else 0.0,
        "net_pnl_usdt": round(sum(float_or_zero(t.get("net_pnl_usdt")) for t in trades), 8),
        "gross_profit_usdt": round(gp, 8),
        "gross_loss_abs_usdt": round(gl, 8),
        "profit_factor": round(gp / gl, 8) if gl else None,
        "avg_win_usdt": round(gp / len(wins), 8) if wins else 0.0,
        "avg_loss_usdt": round(-gl / len(losses), 8) if losses else 0.0,
        "avg_mfe_r": round(avg(float_or_none(t.get("mfe_r")) for t in trades), 8),
        "avg_mae_r": round(avg(float_or_none(t.get("mae_r")) for t in trades), 8),
    }


def summarize_groups(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for group in ["side", "strategy_leg", "regime_label", "setup_profile", "classification", "symbol"]:
        for value in sorted({str(t.get(group) or "") for t in trades}):
            subset = [t for t in trades if str(t.get(group) or "") == value]
            wins = [t for t in subset if float_or_zero(t.get("net_pnl_usdt")) > 0]
            losses = [t for t in subset if float_or_zero(t.get("net_pnl_usdt")) < 0]
            gp = sum(float_or_zero(t.get("net_pnl_usdt")) for t in wins)
            gl = -sum(float_or_zero(t.get("net_pnl_usdt")) for t in losses)
            rows.append({
                "group": group,
                "name": value,
                "count": len(subset),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(subset), 8) if subset else 0.0,
                "net_pnl_usdt": round(sum(float_or_zero(t.get("net_pnl_usdt")) for t in subset), 8),
                "profit_factor": round(gp / gl, 8) if gl else None,
                "avg_win_usdt": round(gp / len(wins), 8) if wins else 0.0,
                "avg_loss_usdt": round(-gl / len(losses), 8) if losses else 0.0,
                "avg_mfe_r": round(avg(float_or_none(t.get("mfe_r")) for t in subset), 8),
                "avg_mae_r": round(avg(float_or_none(t.get("mae_r")) for t in subset), 8),
            })
    return rows


def render_report(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    worst = sorted(packet["trades"], key=lambda item: float_or_zero(item.get("net_pnl_usdt")))[:15]
    lines = [
        "# Live Trade Forensics",
        "",
        f"Window: {packet['filters']['since']} to {packet['filters']['until']} UTC",
        f"Trades: {summary['trade_count']}; win_rate={summary['win_rate']:.2%}; net={summary['net_pnl_usdt']}U; PF={summary['profit_factor']}",
        f"Avg win/loss: {summary['avg_win_usdt']}U / {summary['avg_loss_usdt']}U",
        "",
        "## Worst Trades",
        "",
        "|symbol|side|leg|pnl|hold_s|entry|stop|target|MFE_R|MAE_R|first_touch|class|",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for t in worst:
        lines.append(
            f"|{t.get('symbol')}|{t.get('side')}|{t.get('strategy_leg')}|{t.get('net_pnl_usdt')}|{t.get('hold_seconds')}|"
            f"{t.get('entry_price')}|{t.get('stop_price')}|{t.get('target_price')}|{t.get('mfe_r')}|{t.get('mae_r')}|"
            f"{t.get('first_touch')}|{t.get('classification')}|"
        )
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def favorable_pct(bar: MinuteBar, direction: str, entry: float) -> float:
    return ((bar.high - entry) / entry * 100.0) if direction == "long" else ((entry - bar.low) / entry * 100.0)


def adverse_pct(bar: MinuteBar, direction: str, entry: float) -> float:
    return ((entry - bar.low) / entry * 100.0) if direction == "long" else ((bar.high - entry) / entry * 100.0)


def close_direction_pct(bar: MinuteBar, direction: str, entry: float) -> float:
    return ((bar.close - entry) / entry * 100.0) if direction == "long" else ((entry - bar.close) / entry * 100.0)


def touches_stop(bar: MinuteBar, direction: str, stop: float | None) -> bool:
    if stop is None:
        return False
    return bar.low <= stop if direction == "long" else bar.high >= stop


def touches_target(bar: MinuteBar, direction: str, target: float | None) -> bool:
    if target is None:
        return False
    return bar.high >= target if direction == "long" else bar.low <= target


def touch_time_ms(bar: MinuteBar, direction: str, kind: str) -> int:
    if kind == "stop":
        return bar.low_time_ms if direction == "long" else bar.high_time_ms
    return bar.high_time_ms if direction == "long" else bar.low_time_ms


def recovered_entry(bar: MinuteBar, direction: str, entry: float) -> bool:
    return bar.high >= entry if direction == "long" else bar.low <= entry


def first_touch(stop_ms: int | None, target_ms: int | None) -> str:
    if stop_ms is None and target_ms is None:
        return "none"
    if stop_ms is None:
        return "target"
    if target_ms is None:
        return "stop"
    if stop_ms == target_ms:
        return "same_time_ambiguous"
    return "stop" if stop_ms < target_ms else "target"


def value_time(rows: list[MinuteBar], field: str, func, *, want_time: bool = False) -> Any:
    if not rows:
        return ""
    selected = func(rows, key=lambda row: getattr(row, field))
    if want_time:
        return epoch_ms_to_iso(selected.high_time_ms if field == "high" else selected.low_time_ms)
    return getattr(selected, field)


def entry_position_in_range(entry: float, rows: list[MinuteBar]) -> float | None:
    if not rows:
        return None
    high = max(row.high for row in rows)
    low = min(row.low for row in rows)
    if high <= low:
        return None
    return round((entry - low) / (high - low), 8)


def expected_minute_count(rows: list[MinuteBar]) -> int:
    if not rows:
        return 0
    return max(1, int((rows[-1].open_time_ms - rows[0].open_time_ms) / 60_000) + 1)


def weighted_avg_price(trades: list[dict[str, Any]]) -> float | None:
    qty = sum(float_or_zero(t.get("qty")) for t in trades)
    if qty <= 0:
        return None
    return sum(float_or_zero(t.get("price")) * float_or_zero(t.get("qty")) for t in trades) / qty


def first_trade_price(trades: list[dict[str, Any]]) -> float | None:
    if not trades:
        return None
    ordered = sorted(trades, key=lambda item: int_or_none(item.get("time")) or 0)
    return float_or_none(ordered[0].get("price"))


def top_factors_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts = []
    for item in items[:8]:
        if isinstance(item, dict):
            parts.append(f"{item.get('group','')}:{item.get('name','')}:{item.get('polarity','')}:{item.get('weighted_score','')}")
    return " | ".join(parts)


def normalize_side(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"BUY", "LONG"}:
        return "BUY"
    if text in {"SELL", "SHORT"}:
        return "SELL"
    return text


def normalize_direction(value: Any) -> str:
    side = normalize_side(value)
    if side == "BUY":
        return "long"
    if side == "SELL":
        return "short"
    return str(value or "").lower()


def parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def compact_json(value: Any) -> str:
    if value in (None, ""):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def deep_get(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_float(*values: Any) -> float | None:
    for value in values:
        parsed = float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def first_float_time(*values: Any) -> str:
    for value in values:
        if isinstance(value, datetime):
            return iso(value)
        if value:
            return str(value)
    raise ValueError("missing time")


def float_or_none(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def float_or_zero(value: Any) -> float:
    parsed = float_or_none(value)
    return 0.0 if parsed is None else parsed


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def avg(values: Iterable[float | None]) -> float:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else 0.0


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(normalize_iso_text(value).replace("Z", "+00:00")).astimezone(UTC)


def parse_iso_or_none(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return parse_iso(str(value))
    except (TypeError, ValueError):
        return None


def normalize_iso_text(value: str) -> str:
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    if "." in value and value.endswith("Z"):
        head, tail = value.split(".", 1)
        frac = tail[:-1]
        if len(frac) > 6:
            frac = frac[:6]
        return f"{head}.{frac}Z"
    return value


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms_to_iso(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
