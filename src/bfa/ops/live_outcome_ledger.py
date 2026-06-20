"""Live outcome ledger and recommendation-only guard feedback."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import json
import sqlite3
from typing import Any, Iterable, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.store import EventStore
from bfa.execution.outcome import TradeOutcomeSweepReport, reconcile_submitted_trade_outcomes


@dataclass(frozen=True)
class LiveOutcomeLedgerReport:
    status: str
    reasons: list[str]
    summary: dict[str, Any]
    filters: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] | None = None
    latest_outcomes: list[dict[str, Any]] = field(default_factory=list)
    groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    guard_feedback: list[dict[str, Any]] = field(default_factory=list)
    mutation_proof: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_live_outcome_ledger_v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "filters": dict(self.filters),
            "summary": dict(self.summary),
            "reconciliation": dict(self.reconciliation) if self.reconciliation else None,
            "latest_outcomes": [dict(item) for item in self.latest_outcomes],
            "groups": {key: [dict(item) for item in value] for key, value in self.groups.items()},
            "guard_feedback": [dict(item) for item in self.guard_feedback],
            "mutation_proof": dict(self.mutation_proof),
        }


def build_live_outcome_ledger_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    symbol: str | None = None,
    since: str | None = None,
    latest_limit: int = 10,
    min_group_outcomes: int = 1,
    reconcile: bool = False,
    persist_closed: bool = False,
    signed_client=None,
) -> LiveOutcomeLedgerReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    normalized_symbol = symbol.upper() if symbol else None
    filters = {
        "symbol": normalized_symbol,
        "since": since,
        "latest_limit": latest_limit,
        "min_group_outcomes": min_group_outcomes,
        "reconcile": reconcile,
        "persist_closed": persist_closed,
    }
    reconciliation_report: TradeOutcomeSweepReport | None = None
    if persist_closed and not reconcile:
        return _blocked_report(
            filters=filters,
            reason="persist_closed_requires_reconcile",
            persist_closed=persist_closed,
        )
    if reconcile:
        if signed_client is None:
            return _blocked_report(
                filters=filters,
                reason="signed_client_required_for_reconcile",
                persist_closed=persist_closed,
            )
        connection = connect(resolved_db_path)
        try:
            store = EventStore(connection)
            reconciliation_report = reconcile_submitted_trade_outcomes(
                store,
                signed_client,
                symbol=normalized_symbol,
                persist_closed=persist_closed,
            )
        finally:
            connection.close()

    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        rows = _ledger_rows(connection, symbol=normalized_symbol, since=since)
        open_submitted = _open_submitted_intent_count(connection, symbol=normalized_symbol)
    finally:
        connection.close()

    summary = _summary(rows, open_submitted_count=open_submitted)
    groups = _groups(rows, min_group_outcomes=max(1, min_group_outcomes))
    feedback = _guard_feedback(groups)
    reasons = _reasons(rows, feedback)
    return LiveOutcomeLedgerReport(
        status=_status(rows),
        reasons=reasons,
        filters=filters,
        summary=summary,
        reconciliation=reconciliation_report.to_dict()["summary"] if reconciliation_report else None,
        latest_outcomes=_latest(rows, latest_limit=latest_limit),
        groups=groups,
        guard_feedback=feedback,
        mutation_proof=_mutation_proof(persist_closed=persist_closed),
    )


def _blocked_report(*, filters: dict[str, Any], reason: str, persist_closed: bool) -> LiveOutcomeLedgerReport:
    return LiveOutcomeLedgerReport(
        status="ledger_blocked",
        reasons=[reason],
        filters=filters,
        summary=_summary([], open_submitted_count=0),
        mutation_proof=_mutation_proof(persist_closed=persist_closed),
    )


def _ledger_rows(
    connection: sqlite3.Connection,
    *,
    symbol: str | None,
    since: str | None,
) -> list[dict[str, Any]]:
    params: list[str] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol)
    outcome_rows = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM outcomes
        {where}
        ORDER BY occurred_at ASC, id ASC
        """,
        params,
    ).fetchall()
    rows: list[dict[str, Any]] = []
    for row in outcome_rows:
        payload = json.loads(str(row["payload_json"]))
        item = _ledger_row(connection, row, payload)
        if since and str(item.get("closed_at") or item.get("occurred_at") or "") < since:
            continue
        rows.append(item)
    return rows


def _ledger_row(connection: sqlite3.Connection, row: sqlite3.Row, payload: Mapping[str, Any]) -> dict[str, Any]:
    outcome_intent = _mapping(payload.get("intent"))
    intent_event_id = _int_or_none(outcome_intent.get("event_id"))
    order_intent = _order_intent(connection, intent_event_id)
    intent_payload = _mapping(order_intent.get("intent"))
    symbol = str(payload.get("symbol") or row["symbol"] or outcome_intent.get("symbol") or intent_payload.get("symbol") or "").upper()
    decided_at = str(intent_payload.get("decided_at") or order_intent.get("occurred_at") or outcome_intent.get("occurred_at") or "")
    trade_setup = _artifact_by_ref(connection, "trade_setups", f"trade_setup:{symbol}:{decided_at}") if decided_at else {}
    ai_decision = _artifact_by_ref(connection, "ai_decisions", f"ai_decision:{symbol}:{decided_at}") if decided_at else {}
    setup = _mapping(trade_setup.get("payload", {}).get("setup"))
    factors = [_mapping(item) for item in _list(setup.get("factor_scores")) if isinstance(item, dict)]
    opened_at = str(outcome_intent.get("occurred_at") or order_intent.get("occurred_at") or payload.get("first_trade_time") or row["occurred_at"])
    closed_at = str(payload.get("last_trade_time") or row["occurred_at"])
    hold_minutes = _elapsed_minutes(opened_at, closed_at)
    side = _side(intent_payload.get("side") or outcome_intent.get("side") or setup.get("side"))
    net_pnl = _float_or_zero(payload.get("net_realized_pnl_usdt"))
    return {
        "outcome_event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "intent_event_id": intent_event_id,
        "trade_setup_event_id": trade_setup.get("event_id"),
        "ai_decision_event_id": ai_decision.get("event_id"),
        "symbol": symbol,
        "side": side,
        "status": str(payload.get("status") or "unknown"),
        "opened_at": opened_at,
        "closed_at": closed_at,
        "hold_minutes": hold_minutes,
        "hold_bucket": _hold_bucket(hold_minutes),
        "exit_reason": _exit_reason(payload),
        "net_pnl_usdt": net_pnl,
        "gross_pnl_usdt": _float_or_zero(payload.get("gross_realized_pnl_usdt")),
        "commission_usdt": _float_or_zero(payload.get("commission_usdt")),
        "trade_count": _int_or_zero(payload.get("trade_count")),
        "setup_profile": _setup_profile(setup),
        "setup_reasons": [str(item) for item in _list(setup.get("reasons")) if str(item)],
        "setup_warnings": [str(item) for item in _list(setup.get("warnings")) if str(item)],
        "factor_names": [str(item.get("name")) for item in factors if str(item.get("name"))],
        "negative_factor_names": [
            str(item.get("name"))
            for item in factors
            if str(item.get("name")) and _float_or_zero(item.get("weighted_score")) < 0
        ],
        "factor_reasons": sorted(
            {
                str(reason)
                for factor in factors
                for reason in _list(factor.get("reasons"))
                if str(reason)
            }
        ),
        "ai_decision": _ai_decision_summary(ai_decision),
        "trace_ids": {
            "outcome_event_id": int(row["event_id"]) if row["event_id"] is not None else None,
            "order_intent_event_id": intent_event_id,
            "trade_setup_event_id": trade_setup.get("event_id"),
            "ai_decision_event_id": ai_decision.get("event_id"),
        },
    }


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
    payload = json.loads(str(row["payload_json"]))
    return {
        "event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "occurred_at": str(row["occurred_at"]),
        "symbol": str(row["symbol"] or ""),
        "intent": _mapping(payload.get("intent")),
        "status": payload.get("status"),
        "risk": _mapping(payload.get("risk")),
    }


def _artifact_by_ref(connection: sqlite3.Connection, table: str, ref_id: str) -> dict[str, Any]:
    if not _table_exists(connection, table):
        return {}
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
        "occurred_at": str(row["occurred_at"]),
        "symbol": str(row["symbol"] or ""),
        "ref_id": str(row["ref_id"] or ""),
        "payload": json.loads(str(row["payload_json"])),
    }


def _open_submitted_intent_count(connection: sqlite3.Connection, *, symbol: str | None) -> int:
    params: list[Any] = []
    where = "WHERE json_extract(payload_json, '$.status') = 'submitted'"
    if symbol:
        where += " AND symbol = ?"
        params.append(symbol)
    rows = connection.execute(
        f"""
        SELECT event_id
        FROM order_intents
        {where}
        """,
        params,
    ).fetchall()
    return sum(1 for row in rows if not _has_closed_outcome(connection, int(row["event_id"])))


def _has_closed_outcome(connection: sqlite3.Connection, intent_event_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM outcomes
        WHERE ref_id = ?
           OR json_extract(payload_json, '$.intent.event_id') = ?
        LIMIT 1
        """,
        (f"outcome:{intent_event_id}:closed", intent_event_id),
    ).fetchone()
    return row is not None


def _summary(rows: list[dict[str, Any]], *, open_submitted_count: int) -> dict[str, Any]:
    pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in rows]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    exit_counts = Counter(str(item.get("exit_reason") or "unknown") for item in rows)
    return {
        "outcome_count": len(rows),
        "open_or_unreconciled_submitted_intents": open_submitted_count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": _ratio(len(wins), len(rows)),
        "total_net_pnl_usdt": round(sum(pnl_values), 8),
        "average_net_pnl_usdt": round(_ratio(sum(pnl_values), len(rows)), 8),
        "gross_profit_usdt": round(gross_profit, 8),
        "gross_loss_abs_usdt": round(gross_loss_abs, 8),
        "profit_factor": _profit_factor(gross_profit, gross_loss_abs),
        "worst_drawdown_usdt": _worst_drawdown(rows),
        "exit_reason_counts": dict(sorted(exit_counts.items())),
    }


def _groups(rows: list[dict[str, Any]], *, min_group_outcomes: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "symbols": _group(rows, "symbol", min_group_outcomes=min_group_outcomes),
        "sides": _group(rows, "side", min_group_outcomes=min_group_outcomes),
        "exit_reasons": _group(rows, "exit_reason", min_group_outcomes=min_group_outcomes),
        "holding_buckets": _group(rows, "hold_bucket", min_group_outcomes=min_group_outcomes),
        "setup_profiles": _group(rows, "setup_profile", min_group_outcomes=min_group_outcomes),
        "setup_reasons": _group_tokens(rows, "setup_reasons", min_group_outcomes=min_group_outcomes),
        "factor_names": _group_tokens(rows, "negative_factor_names", min_group_outcomes=min_group_outcomes),
        "factor_reasons": _group_tokens(rows, "factor_reasons", min_group_outcomes=min_group_outcomes),
    }


def _group(rows: list[dict[str, Any]], key: str, *, min_group_outcomes: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return _rank_groups(grouped.items(), min_group_outcomes=min_group_outcomes)


def _group_tokens(rows: list[dict[str, Any]], key: str, *, min_group_outcomes: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        values = [str(item) for item in _list(row.get(key)) if str(item)]
        for value in values or ["<none>"]:
            grouped.setdefault(value, []).append(row)
    return _rank_groups(grouped.items(), min_group_outcomes=min_group_outcomes)


def _rank_groups(
    items: Iterable[tuple[str, list[dict[str, Any]]]],
    *,
    min_group_outcomes: int,
) -> list[dict[str, Any]]:
    ranked = []
    for name, group_rows in items:
        if len(group_rows) < min_group_outcomes:
            continue
        pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in group_rows]
        losses = [value for value in pnl_values if value < 0]
        ranked.append(
            {
                "name": name,
                "outcome_count": len(group_rows),
                "win_rate": _ratio(len([value for value in pnl_values if value > 0]), len(pnl_values)),
                "total_net_pnl_usdt": round(sum(pnl_values), 8),
                "average_net_pnl_usdt": round(_ratio(sum(pnl_values), len(pnl_values)), 8),
                "gross_loss_abs_usdt": round(abs(sum(losses)), 8),
                "loss_count": len(losses),
            }
        )
    return sorted(ranked, key=lambda item: (float(item["total_net_pnl_usdt"]), -int(item["outcome_count"]), str(item["name"])))


def _guard_feedback(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    actions = {
        "symbols": "quarantine_or_reduce_symbol",
        "sides": "tighten_side_filter",
        "exit_reasons": "inspect_exit_geometry",
        "holding_buckets": "inspect_holding_behavior",
        "setup_reasons": "tighten_setup_reason",
        "factor_names": "raise_or_reweight_factor",
        "factor_reasons": "tighten_factor_reason",
    }
    feedback: list[dict[str, Any]] = []
    for group_name, action in actions.items():
        for row in groups.get(group_name, [])[:3]:
            if _float_or_zero(row.get("total_net_pnl_usdt")) >= 0:
                continue
            feedback.append(
                {
                    "action": action,
                    "group": group_name,
                    "name": row["name"],
                    "outcome_count": row["outcome_count"],
                    "total_net_pnl_usdt": row["total_net_pnl_usdt"],
                    "win_rate": row["win_rate"],
                    "applies_changes": False,
                    "raises_risk": False,
                    "reason": "negative_live_outcome_group",
                }
            )
    return feedback


def _latest(rows: list[dict[str, Any]], *, latest_limit: int) -> list[dict[str, Any]]:
    selected = sorted(rows, key=lambda item: (str(item.get("closed_at") or ""), int(item.get("outcome_event_id") or 0)), reverse=True)
    keys = (
        "outcome_event_id",
        "intent_event_id",
        "symbol",
        "side",
        "closed_at",
        "hold_minutes",
        "hold_bucket",
        "exit_reason",
        "net_pnl_usdt",
        "setup_profile",
        "setup_reasons",
        "factor_reasons",
        "trace_ids",
    )
    return [{key: item.get(key) for key in keys} for item in selected[: max(0, latest_limit)]]


def _reasons(rows: list[dict[str, Any]], feedback: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["live_outcomes_missing"]
    if feedback:
        return ["live_outcome_ledger_ready", "guard_feedback_recommendations_present"]
    return ["live_outcome_ledger_ready"]


def _status(rows: list[dict[str, Any]]) -> str:
    return "ledger_ready" if rows else "no_live_outcomes"


def _mutation_proof(*, persist_closed: bool) -> dict[str, bool]:
    return {
        "places_orders": False,
        "cancels_orders": False,
        "changes_systemd_state": False,
        "writes_env_files": False,
        "raises_risk": False,
        "applies_guard_changes": False,
        "persists_closed_fills_and_outcomes": bool(persist_closed),
    }


def _ai_decision_summary(ai_decision: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = _mapping(ai_decision.get("payload"))
    validation = _mapping(payload.get("validation"))
    decision = _mapping(validation.get("decision"))
    if not payload:
        return None
    return {
        "accepted": validation.get("accepted"),
        "decision": decision.get("decision"),
        "side": decision.get("side"),
        "confidence": decision.get("confidence"),
        "validation_errors": validation.get("validation_errors", []),
    }


def _exit_reason(payload: Mapping[str, Any]) -> str:
    explicit = payload.get("exit_reason")
    if explicit:
        return str(explicit)
    trades = _list(payload.get("trades"))
    if trades:
        return "closed_by_exchange_fills"
    return str(payload.get("status") or "unknown")


def _side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"long", "short"}:
        return normalized
    if normalized == "buy":
        return "long"
    if normalized == "sell":
        return "short"
    return normalized or "unknown"


def _setup_profile(setup: Mapping[str, Any]) -> str:
    price_basis = _mapping(setup.get("price_basis"))
    return str(price_basis.get("profile") or "unknown")


def _hold_bucket(minutes: float | None) -> str:
    if minutes is None:
        return "unknown"
    if minutes < 15:
        return "under_15m"
    if minutes < 60:
        return "15m_to_1h"
    if minutes < 240:
        return "1h_to_4h"
    return "over_4h"


def _elapsed_minutes(start: str, end: str) -> float | None:
    try:
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return round((ended - started).total_seconds() / 60.0, 4)


def _worst_drawdown(rows: list[dict[str, Any]]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for row in sorted(rows, key=lambda item: (str(item.get("closed_at") or ""), int(item.get("outcome_event_id") or 0))):
        cumulative += _float_or_zero(row.get("net_pnl_usdt"))
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return round(worst, 8)


def _profit_factor(gross_profit: float, gross_loss_abs: float) -> float | None:
    if gross_loss_abs == 0:
        return None
    return round(gross_profit / gross_loss_abs, 8)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 8)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
