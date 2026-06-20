"""Read-only trade decision trace reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any

from bfa.event_store.migrations import connect


@dataclass(frozen=True)
class TraceArtifact:
    table: str
    id: int
    event_id: int | None
    occurred_at: str
    source: str | None
    symbol: str | None
    ref_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "id": self.id,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "source": self.source,
            "symbol": self.symbol,
            "ref_id": self.ref_id,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class TradeTraceReport:
    found: bool
    symbol: str | None = None
    decided_at: str | None = None
    status: str = "not_found"
    reason: str | None = None
    candidate: TraceArtifact | None = None
    trade_setup: TraceArtifact | None = None
    ai_decision: TraceArtifact | None = None
    order_intent: TraceArtifact | None = None
    exchange_responses: list[TraceArtifact] = field(default_factory=list)
    decision_flow: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "status": self.status,
            "reason": self.reason,
            "symbol": self.symbol,
            "decided_at": self.decided_at,
            "decision_flow": list(self.decision_flow),
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "trade_setup": self.trade_setup.to_dict() if self.trade_setup else None,
            "ai_decision": self.ai_decision.to_dict() if self.ai_decision else None,
            "order_intent": self.order_intent.to_dict() if self.order_intent else None,
            "exchange_responses": [item.to_dict() for item in self.exchange_responses],
        }


def build_trade_trace_report(
    *,
    db_path: str,
    event_id: int | None = None,
    symbol: str | None = None,
) -> TradeTraceReport:
    if event_id is None and not symbol:
        raise ValueError("event_id or symbol is required")
    connection = connect(db_path)
    try:
        order_intent = _order_intent(connection, event_id=event_id, symbol=symbol)
        if order_intent is None:
            return TradeTraceReport(found=False, reason="order_intent_not_found")
        intent = _payload_mapping(order_intent.payload.get("intent"))
        trace_symbol = str(intent.get("symbol") or order_intent.symbol or "").upper()
        decided_at = str(intent.get("decided_at") or order_intent.occurred_at)
        candidate = _artifact_by_ref(connection, "candidates", f"candidate:{trace_symbol}:{decided_at}")
        trade_setup = (
            _artifact_by_ref(connection, "trade_setups", f"trade_setup:{trace_symbol}:{decided_at}")
            if _table_exists(connection, "trade_setups")
            else None
        )
        ai_decision = _artifact_by_ref(connection, "ai_decisions", f"ai_decision:{trace_symbol}:{decided_at}")
        exchange_responses = _artifacts_by_ref_prefix(
            connection,
            "exchange_responses",
            f"exchange_response:",
            trace_symbol,
            decided_at,
        )
        return TradeTraceReport(
            found=True,
            status="trace_ready",
            symbol=trace_symbol,
            decided_at=decided_at,
            candidate=candidate,
            trade_setup=trade_setup,
            ai_decision=ai_decision,
            order_intent=order_intent,
            exchange_responses=exchange_responses,
            decision_flow=_decision_flow(
                candidate=candidate,
                trade_setup=trade_setup,
                ai_decision=ai_decision,
                order_intent=order_intent,
                exchange_responses=exchange_responses,
            ),
        )
    finally:
        connection.close()


def _order_intent(
    connection: sqlite3.Connection,
    *,
    event_id: int | None,
    symbol: str | None,
) -> TraceArtifact | None:
    if event_id is not None:
        row = connection.execute(
            """
            SELECT id, occurred_at, source, symbol, ref_id, payload_json, event_id
            FROM order_intents
            WHERE event_id = ? OR id = ?
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """,
            (event_id, event_id),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT id, occurred_at, source, symbol, ref_id, payload_json, event_id
            FROM order_intents
            WHERE symbol = ?
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """,
            (str(symbol).upper(),),
        ).fetchone()
    return _row_to_artifact("order_intents", row) if row else None


def _artifact_by_ref(connection: sqlite3.Connection, table: str, ref_id: str) -> TraceArtifact | None:
    row = connection.execute(
        f"""
        SELECT id, occurred_at, source, symbol, ref_id, payload_json, event_id
        FROM {table}
        WHERE ref_id = ?
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """,
        (ref_id,),
    ).fetchone()
    return _row_to_artifact(table, row) if row else None


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _artifacts_by_ref_prefix(
    connection: sqlite3.Connection,
    table: str,
    ref_prefix: str,
    symbol: str,
    decided_at: str,
) -> list[TraceArtifact]:
    rows = connection.execute(
        f"""
        SELECT id, occurred_at, source, symbol, ref_id, payload_json, event_id
        FROM {table}
        WHERE symbol = ? AND ref_id LIKE ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (symbol, f"{ref_prefix}%:{symbol}:{decided_at}"),
    ).fetchall()
    return [_row_to_artifact(table, row) for row in rows]


def _decision_flow(
    *,
    candidate: TraceArtifact | None,
    trade_setup: TraceArtifact | None,
    ai_decision: TraceArtifact | None,
    order_intent: TraceArtifact,
    exchange_responses: list[TraceArtifact],
) -> list[dict[str, Any]]:
    flow: list[dict[str, Any]] = []
    if candidate is not None:
        flow.append(
            {
                "stage": "candidate",
                "status": "ranked",
                "symbol": candidate.symbol,
                "score": candidate.payload.get("score"),
                "reason_codes": candidate.payload.get("reason_codes", []),
                "features": candidate.payload.get("features", {}),
            }
        )
    if trade_setup is not None:
        setup = _payload_mapping(trade_setup.payload.get("setup"))
        flow.append(
            {
                "stage": "quant_setup",
                "status": setup.get("decision"),
                "side": setup.get("side"),
                "entry_price": setup.get("entry_price"),
                "stop_price": setup.get("stop_price"),
                "target_price": setup.get("target_price"),
                "notional_usdt": setup.get("notional_usdt"),
                "hold_time_minutes": setup.get("hold_time_minutes"),
                "long_score": setup.get("long_score"),
                "short_score": setup.get("short_score"),
                "edge_score": setup.get("edge_score"),
                "regime": setup.get("regime"),
                "risk_reward_ratio": setup.get("risk_reward_ratio"),
                "stop_distance_percent": setup.get("stop_distance_percent"),
                "target_distance_percent": setup.get("target_distance_percent"),
                "price_basis": setup.get("price_basis", {}),
                "factor_scores": setup.get("factor_scores", []),
                "reasons": setup.get("reasons", []),
                "warnings": setup.get("warnings", []),
            }
        )
    if ai_decision is not None:
        validation = _payload_mapping(ai_decision.payload.get("validation"))
        decision = _payload_mapping(validation.get("decision"))
        flow.append(
            {
                "stage": "ai_overlay",
                "accepted": validation.get("accepted"),
                "decision": decision.get("decision"),
                "side": decision.get("side"),
                "confidence": decision.get("confidence"),
                "validation_errors": validation.get("validation_errors", []),
                "validation_warnings": validation.get("validation_warnings", []),
                "reasons": decision.get("reasons", []),
            }
        )
    risk = _payload_mapping(order_intent.payload.get("risk"))
    intent = _payload_mapping(order_intent.payload.get("intent"))
    flow.append(
        {
            "stage": "risk_and_intent",
            "status": order_intent.payload.get("status"),
            "risk_accepted": risk.get("accepted"),
            "risk_reasons": risk.get("reason_codes", []),
            "intent": intent,
        }
    )
    for response in exchange_responses:
        flow.append(
            {
                "stage": "exchange_response",
                "response_type": response.payload.get("response_type"),
                "response": response.payload.get("response"),
            }
        )
    return flow


def _row_to_artifact(table: str, row: sqlite3.Row) -> TraceArtifact:
    return TraceArtifact(
        table=table,
        id=int(row["id"]),
        event_id=int(row["event_id"]) if row["event_id"] is not None else None,
        occurred_at=str(row["occurred_at"]),
        source=row["source"],
        symbol=row["symbol"],
        ref_id=row["ref_id"],
        payload=json.loads(row["payload_json"]),
    )


def _payload_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
