"""Post-entry path attribution for live trade outcomes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import sqlite3
from typing import Any, Mapping

from bfa.backtest.data import INTERVAL_MS
from bfa.backtest.models import BacktestBar
from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate


@dataclass(frozen=True)
class PostTradePathReport:
    status: str
    reasons: list[str]
    filters: dict[str, Any]
    summary: dict[str, Any]
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    mutation_proof: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_post_trade_path_v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "filters": dict(self.filters),
            "summary": dict(self.summary),
            "outcomes": [dict(item) for item in self.outcomes],
            "mutation_proof": dict(self.mutation_proof),
        }


def build_post_trade_path_report(
    config: AppConfig,
    *,
    client,
    db_path: str | None = None,
    symbol: str | None = None,
    interval: str = "1m",
    lookahead_minutes: int = 120,
    latest_limit: int = 20,
) -> PostTradePathReport:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    normalized_symbol = symbol.upper() if symbol else None
    filters = {
        "symbol": normalized_symbol,
        "interval": interval,
        "lookahead_minutes": lookahead_minutes,
        "latest_limit": latest_limit,
    }
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        rows = _load_outcome_rows(connection, symbol=normalized_symbol, latest_limit=latest_limit)
    finally:
        connection.close()

    analyses: list[dict[str, Any]] = []
    for row in rows:
        analyses.append(
            _analyze_outcome_path(
                row,
                client=client,
                interval=interval,
                lookahead_minutes=lookahead_minutes,
            )
        )

    return PostTradePathReport(
        status="path_ready" if analyses else "no_outcomes",
        reasons=_report_reasons(analyses),
        filters=filters,
        summary=_summary(analyses),
        outcomes=analyses,
        mutation_proof={
            "places_orders": False,
            "cancels_orders": False,
            "changes_systemd_state": False,
            "writes_env_files": False,
            "persists_closed_fills_and_outcomes": False,
            "raises_risk": False,
        },
    )


def _load_outcome_rows(
    connection: sqlite3.Connection,
    *,
    symbol: str | None,
    latest_limit: int,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol)
    params.append(max(1, latest_limit))
    rows = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM outcomes
        {where}
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_outcome_row(connection, row) for row in rows]


def _outcome_row(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["payload_json"]))
    outcome_intent = _mapping(payload.get("intent"))
    intent_event_id = _int_or_none(outcome_intent.get("event_id"))
    order_intent = _order_intent(connection, intent_event_id)
    intent_payload = _mapping(order_intent.get("intent"))
    symbol = str(payload.get("symbol") or row["symbol"] or outcome_intent.get("symbol") or intent_payload.get("symbol") or "").upper()
    decided_at = str(intent_payload.get("decided_at") or order_intent.get("occurred_at") or outcome_intent.get("occurred_at") or "")
    trade_setup = _artifact_by_ref(connection, "trade_setups", f"trade_setup:{symbol}:{decided_at}") if decided_at else {}
    setup = _mapping(_mapping(trade_setup.get("payload")).get("setup"))
    opened_at = str(outcome_intent.get("occurred_at") or order_intent.get("occurred_at") or payload.get("first_trade_time") or row["occurred_at"])
    closed_at = str(payload.get("last_trade_time") or row["occurred_at"])
    side = _side(intent_payload.get("side") or outcome_intent.get("side") or setup.get("side"))
    return {
        "outcome_event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "intent_event_id": intent_event_id,
        "trade_setup_event_id": trade_setup.get("event_id"),
        "symbol": symbol,
        "side": side,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "net_pnl_usdt": _float_or_zero(payload.get("net_realized_pnl_usdt")),
        "entry_price": _first_float(intent_payload, setup, "entry_price"),
        "stop_price": _first_float(intent_payload, setup, "stop_price"),
        "target_price": _first_float(intent_payload, setup, "target_price"),
        "notional_usdt": _first_float(intent_payload, setup, "notional_usdt"),
        "setup_reasons": [str(item) for item in _list(setup.get("reasons")) if str(item)],
        "setup_warnings": [str(item) for item in _list(setup.get("warnings")) if str(item)],
        "trace_ids": {
            "outcome_event_id": int(row["event_id"]) if row["event_id"] is not None else None,
            "order_intent_event_id": intent_event_id,
            "trade_setup_event_id": trade_setup.get("event_id"),
        },
    }


def _analyze_outcome_path(
    row: Mapping[str, Any],
    *,
    client,
    interval: str,
    lookahead_minutes: int,
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    opened_at = str(row.get("opened_at") or "")
    opened = _parse_time(opened_at)
    entry = _positive_float(row.get("entry_price"))
    stop = _positive_float(row.get("stop_price"))
    target = _positive_float(row.get("target_price"))
    side = str(row.get("side") or "").lower()
    base = {
        "outcome_event_id": row.get("outcome_event_id"),
        "intent_event_id": row.get("intent_event_id"),
        "trade_setup_event_id": row.get("trade_setup_event_id"),
        "symbol": symbol,
        "side": side,
        "opened_at": opened_at,
        "closed_at": row.get("closed_at"),
        "net_pnl_usdt": row.get("net_pnl_usdt"),
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "setup_reasons": list(_list(row.get("setup_reasons"))),
        "setup_warnings": list(_list(row.get("setup_warnings"))),
        "trace_ids": dict(_mapping(row.get("trace_ids"))),
    }
    if opened is None or entry is None or side not in {"long", "short"}:
        return {**base, "status": "path_unavailable", "reasons": ["missing_entry_context"]}

    end = opened + timedelta(minutes=max(1, lookahead_minutes))
    response = client.klines(
        symbol,
        interval=interval,
        start_time=int(opened.timestamp() * 1000),
        end_time=int(end.timestamp() * 1000),
        limit=max(1, min(1500, int((lookahead_minutes * 60_000) / INTERVAL_MS[interval]) + 2)),
    )
    bars = [BacktestBar.from_binance_kline(symbol, item) for item in response.payload if isinstance(item, list)]
    if not bars:
        return {**base, "status": "path_unavailable", "reasons": ["no_post_entry_klines"]}

    path = _path_metrics(bars, side=side, entry=entry, stop=stop, target=target)
    classification = _classify_path(path)
    return {
        **base,
        "status": "path_analyzed",
        "bar_count": len(bars),
        "path": path,
        "classification": classification,
        "reasons": classification["labels"],
    }


def _path_metrics(
    bars: list[BacktestBar],
    *,
    side: str,
    entry: float,
    stop: float | None,
    target: float | None,
) -> dict[str, Any]:
    stop_distance_percent = abs(entry - stop) / entry * 100.0 if stop is not None else None
    target_distance_percent = abs(target - entry) / entry * 100.0 if target is not None else None
    favorable_values: list[float] = []
    adverse_values: list[float] = []
    close_returns: list[float] = []
    stop_index: int | None = None
    target_index: int | None = None
    same_direction_bars = 0
    opposite_direction_bars = 0
    for index, bar in enumerate(bars):
        if side == "long":
            favorable = (bar.high - entry) / entry * 100.0
            adverse = (entry - bar.low) / entry * 100.0
            close_return = (bar.close - entry) / entry * 100.0
            hit_stop = stop is not None and bar.low <= stop
            hit_target = target is not None and bar.high >= target
        else:
            favorable = (entry - bar.low) / entry * 100.0
            adverse = (bar.high - entry) / entry * 100.0
            close_return = (entry - bar.close) / entry * 100.0
            hit_stop = stop is not None and bar.high >= stop
            hit_target = target is not None and bar.low <= target
        favorable_values.append(favorable)
        adverse_values.append(adverse)
        close_returns.append(close_return)
        same_direction_bars += int(close_return > 0)
        opposite_direction_bars += int(close_return < 0)
        if stop_index is None and hit_stop:
            stop_index = index
        if target_index is None and hit_target:
            target_index = index

    max_favorable = max(favorable_values, default=0.0)
    max_adverse = max(adverse_values, default=0.0)
    final_return = close_returns[-1] if close_returns else 0.0
    stop_distance = stop_distance_percent or 0.0
    first_hit = _first_hit(stop_index, target_index)
    after_stop = bars[stop_index + 1 :] if stop_index is not None else []
    after_stop_mfe = _max_favorable_after_stop(after_stop, side=side, entry=entry)
    after_stop_final = _directional_close_return(after_stop[-1], side=side, entry=entry) if after_stop else None
    first_window = bars[: min(3, len(bars))]
    early_adverse = _max_adverse(first_window, side=side, entry=entry)
    early_favorable = _max_favorable(first_window, side=side, entry=entry)
    volume = _volume_metrics(bars)
    return {
        "window_start": bars[0].open_time_iso,
        "window_end": bars[-1].close_time_iso,
        "first_hit": first_hit,
        "stop_hit": stop_index is not None,
        "target_hit": target_index is not None,
        "stop_hit_at": bars[stop_index].close_time_iso if stop_index is not None else None,
        "target_hit_at": bars[target_index].close_time_iso if target_index is not None else None,
        "stop_distance_percent": round(stop_distance_percent, 4) if stop_distance_percent is not None else None,
        "target_distance_percent": round(target_distance_percent, 4) if target_distance_percent is not None else None,
        "max_favorable_percent": round(max_favorable, 4),
        "max_adverse_percent": round(max_adverse, 4),
        "max_favorable_r": round(max_favorable / stop_distance, 4) if stop_distance > 0 else None,
        "max_adverse_r": round(max_adverse / stop_distance, 4) if stop_distance > 0 else None,
        "final_directional_return_percent": round(final_return, 4),
        "direction_after_entry": _direction_label(final_return),
        "after_stop_max_favorable_percent": round(after_stop_mfe, 4) if after_stop else None,
        "after_stop_max_favorable_r": round(after_stop_mfe / stop_distance, 4) if after_stop and stop_distance > 0 else None,
        "after_stop_final_directional_return_percent": round(after_stop_final, 4) if after_stop_final is not None else None,
        "would_recover_to_entry_after_stop": after_stop_mfe > 0 if after_stop else False,
        "would_hit_target_after_stop": _would_hit_target(after_stop, side=side, target=target) if after_stop else False,
        "early_adverse_percent": round(early_adverse, 4),
        "early_favorable_percent": round(early_favorable, 4),
        "early_adverse_r": round(early_adverse / stop_distance, 4) if stop_distance > 0 else None,
        "early_favorable_r": round(early_favorable / stop_distance, 4) if stop_distance > 0 else None,
        "same_direction_bar_count": same_direction_bars,
        "opposite_direction_bar_count": opposite_direction_bars,
        **volume,
    }


def _classify_path(path: Mapping[str, Any]) -> dict[str, Any]:
    labels: list[str] = []
    final_return = _float_or_zero(path.get("final_directional_return_percent"))
    max_favorable_r = _float_or_zero(path.get("max_favorable_r"))
    after_stop_mfe_r = _float_or_zero(path.get("after_stop_max_favorable_r"))
    early_adverse_r = _float_or_zero(path.get("early_adverse_r"))
    early_favorable_r = _float_or_zero(path.get("early_favorable_r"))
    stop_hit = bool(path.get("stop_hit"))
    target_hit = bool(path.get("target_hit"))
    if target_hit and path.get("first_hit") == "target":
        labels.append("direction_right_target_reached")
    if stop_hit and (after_stop_mfe_r >= 1.0 or bool(path.get("would_hit_target_after_stop"))):
        labels.append("direction_right_stop_or_entry_bad")
    elif stop_hit and final_return > 0.15 and max_favorable_r >= 0.8:
        labels.append("direction_right_stop_too_tight")
    elif stop_hit and final_return < -0.15 and max_favorable_r < 0.5:
        labels.append("direction_wrong")
    elif stop_hit:
        labels.append("stopped_before_clear_follow_through")
    elif final_return < -0.15:
        labels.append("direction_decayed_after_entry")
    elif final_return > 0.15:
        labels.append("direction_right_but_exit_geometry_unresolved")
    else:
        labels.append("no_clear_direction_after_entry")
    if early_adverse_r >= 0.5 and early_favorable_r < 0.35:
        labels.append("entry_chased_late_or_too_close_to_noise")
    volume_change = _float_or_zero(path.get("volume_change_percent"))
    if volume_change <= -20:
        labels.append("post_entry_volume_faded")
    elif volume_change >= 20:
        labels.append("post_entry_volume_expanded")
    return {
        "labels": _dedupe(labels),
        "primary": labels[0] if labels else "unclassified",
    }


def _summary(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(
        label
        for item in analyses
        for label in _list(_mapping(item.get("classification")).get("labels"))
    )
    directions = Counter(str(_mapping(item.get("path")).get("direction_after_entry") or "unknown") for item in analyses)
    stop_count = sum(1 for item in analyses if _mapping(item.get("path")).get("stop_hit"))
    target_count = sum(1 for item in analyses if _mapping(item.get("path")).get("target_hit"))
    analyzed = [item for item in analyses if item.get("status") == "path_analyzed"]
    return {
        "outcome_count": len(analyses),
        "analyzed_count": len(analyzed),
        "stop_hit_count": stop_count,
        "target_hit_count": target_count,
        "classification_counts": dict(sorted(labels.items())),
        "direction_after_entry_counts": dict(sorted(directions.items())),
    }


def _report_reasons(analyses: list[dict[str, Any]]) -> list[str]:
    if not analyses:
        return ["post_trade_outcomes_missing"]
    if any(item.get("status") == "path_analyzed" for item in analyses):
        return ["post_trade_path_ready"]
    return ["post_trade_path_unavailable"]


def _order_intent(connection: sqlite3.Connection, event_id: int | None) -> dict[str, Any]:
    if event_id is None:
        return {}
    row = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        WHERE event_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "occurred_at": str(row["occurred_at"]),
        "symbol": str(row["symbol"] or ""),
        "intent": _mapping(json.loads(str(row["payload_json"])).get("intent")),
    }


def _artifact_by_ref(connection: sqlite3.Connection, table: str, ref_id: str) -> dict[str, Any]:
    row = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, ref_id, payload_json
        FROM {table}
        WHERE ref_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (ref_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "payload": json.loads(str(row["payload_json"])),
    }


def _first_hit(stop_index: int | None, target_index: int | None) -> str:
    if stop_index is None and target_index is None:
        return "none"
    if stop_index is None:
        return "target"
    if target_index is None:
        return "stop"
    if stop_index == target_index:
        return "same_bar_stop_first"
    return "stop" if stop_index < target_index else "target"


def _volume_metrics(bars: list[BacktestBar]) -> dict[str, Any]:
    midpoint = max(1, len(bars) // 2)
    early = sum(bar.quote_volume for bar in bars[:midpoint])
    late = sum(bar.quote_volume for bar in bars[midpoint:])
    change = ((late - early) / early * 100.0) if early > 0 else None
    return {
        "early_quote_volume": round(early, 4),
        "late_quote_volume": round(late, 4),
        "volume_change_percent": round(change, 4) if change is not None else None,
    }


def _max_favorable_after_stop(bars: list[BacktestBar], *, side: str, entry: float) -> float:
    return _max_favorable(bars, side=side, entry=entry)


def _max_favorable(bars: list[BacktestBar], *, side: str, entry: float) -> float:
    if side == "long":
        return max((((bar.high - entry) / entry) * 100.0 for bar in bars), default=0.0)
    return max((((entry - bar.low) / entry) * 100.0 for bar in bars), default=0.0)


def _max_adverse(bars: list[BacktestBar], *, side: str, entry: float) -> float:
    if side == "long":
        return max((((entry - bar.low) / entry) * 100.0 for bar in bars), default=0.0)
    return max((((bar.high - entry) / entry) * 100.0 for bar in bars), default=0.0)


def _directional_close_return(bar: BacktestBar, *, side: str, entry: float) -> float:
    if side == "long":
        return (bar.close - entry) / entry * 100.0
    return (entry - bar.close) / entry * 100.0


def _would_hit_target(bars: list[BacktestBar], *, side: str, target: float | None) -> bool:
    if target is None:
        return False
    if side == "long":
        return any(bar.high >= target for bar in bars)
    return any(bar.low <= target for bar in bars)


def _direction_label(value: float) -> str:
    if value > 0.15:
        return "same_direction"
    if value < -0.15:
        return "opposite_direction"
    return "flat"


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_float(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> float | None:
    return _positive_float(left.get(key)) or _positive_float(right.get(key))


def _side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"long", "short"}:
        return normalized
    if normalized == "buy":
        return "long"
    if normalized == "sell":
        return "short"
    return normalized or "unknown"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _positive_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
