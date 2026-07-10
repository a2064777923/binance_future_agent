"""Persist execution artifacts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import sqlite3
from typing import Any, Mapping

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision


def persist_order_intent(
    store: EventStore,
    *,
    intent: OrderIntent,
    status: str,
    risk: RiskDecision,
) -> int:
    event_id = store.insert_artifact(
        "order_intents",
        occurred_at=intent.decided_at,
        source=f"execution.{intent.mode}",
        symbol=intent.symbol,
        ref_id=f"order_intent:{intent.symbol}:{intent.decided_at}",
        payload={
            "status": status,
            "intent": intent.to_dict(),
            "risk": risk.to_dict(),
        },
        event_type="order_intent",
    )
    if status == "entry_order_pending":
        register_pending_limit_entry(store.connection, intent_event_id=event_id, intent=intent)
    return event_id


def register_pending_limit_entry(
    connection: sqlite3.Connection,
    *,
    intent_event_id: int,
    intent: OrderIntent,
) -> None:
    """Register a live pending entry for indexed watchdog reads."""

    client_order_id = str(intent.metadata.get("client_order_id") or "").strip()
    if not client_order_id:
        raise ValueError("pending limit entry requires client_order_id")
    strategy_leg = str(intent.metadata.get("strategy_leg") or "").strip().lower() or None
    wait_seconds = _positive_float(intent.limit_wait_seconds, default=45.0)
    expires_at = _iso_after_seconds(intent.decided_at, wait_seconds)
    connection.execute(
        """
        INSERT INTO pending_limit_entries (
            intent_event_id,
            occurred_at,
            expires_at,
            symbol,
            client_order_id,
            strategy_leg,
            status,
            intent_json,
            resolved_at,
            resolution_status
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)
        ON CONFLICT(client_order_id) DO UPDATE SET
            intent_event_id = excluded.intent_event_id,
            occurred_at = excluded.occurred_at,
            expires_at = excluded.expires_at,
            symbol = excluded.symbol,
            strategy_leg = excluded.strategy_leg,
            status = 'pending',
            intent_json = excluded.intent_json,
            resolved_at = NULL,
            resolution_status = NULL
        """,
        (
            int(intent_event_id),
            intent.decided_at,
            expires_at,
            intent.symbol.upper(),
            client_order_id,
            strategy_leg,
            json.dumps(intent.to_dict(), sort_keys=True, ensure_ascii=False),
        ),
    )
    connection.commit()


def load_pending_limit_entry_rows(
    connection: sqlite3.Connection,
    *,
    max_items: int,
    excluded_symbols: set[str] | None = None,
) -> list[sqlite3.Row]:
    limit = max(0, int(max_items))
    if limit <= 0:
        return []
    excluded = sorted({str(symbol).upper() for symbol in (excluded_symbols or set()) if str(symbol).strip()})
    params: list[Any] = ["pending"]
    excluded_clause = ""
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        excluded_clause = f" AND symbol NOT IN ({placeholders})"
        params.extend(excluded)
    params.append(limit)
    return connection.execute(
        f"""
        SELECT
            intent_event_id,
            occurred_at,
            expires_at,
            symbol,
            client_order_id,
            strategy_leg,
            status,
            intent_json
        FROM pending_limit_entries
        WHERE status = ?{excluded_clause}
        ORDER BY expires_at ASC, intent_event_id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()


def resolve_pending_limit_entry(
    connection: sqlite3.Connection,
    *,
    intent_event_id: int,
    resolved_at: str,
    resolution_status: str,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE pending_limit_entries
        SET status = 'resolved', resolved_at = ?, resolution_status = ?
        WHERE intent_event_id = ? AND status = 'pending'
        """,
        (resolved_at, resolution_status, int(intent_event_id)),
    )
    connection.commit()
    return cursor.rowcount > 0


def order_intent_from_mapping(payload: Mapping[str, Any]) -> OrderIntent:
    quantity = _float_or_zero(payload.get("quantity"))
    entry_price = _float_or_zero(payload.get("entry_price"))
    notional = _float_or_none(payload.get("notional_usdt"))
    metadata = payload.get("metadata")
    limit_wait_seconds = _float_or_none(payload.get("limit_wait_seconds"))
    return OrderIntent(
        symbol=str(payload.get("symbol") or "").upper(),
        side=str(payload.get("side") or "").upper(),
        quantity=quantity,
        notional_usdt=notional if notional is not None else quantity * entry_price,
        entry_price=entry_price,
        stop_price=_float_or_zero(payload.get("stop_price")),
        target_price=_float_or_zero(payload.get("target_price")),
        leverage=max(int(_float_or_zero(payload.get("leverage")) or 1), 1),
        mode=str(payload.get("mode") or "live"),
        decided_at=str(payload.get("decided_at") or ""),
        order_type=str(payload.get("order_type") or "LIMIT"),
        time_in_force=str(payload.get("time_in_force")) if payload.get("time_in_force") is not None else None,
        limit_wait_seconds=int(limit_wait_seconds) if limit_wait_seconds is not None else None,
        reduce_only=bool(payload.get("reduce_only", False)),
        reason_codes=[str(item) for item in payload.get("reason_codes", [])],
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def persist_exchange_response(
    store: EventStore,
    *,
    intent: OrderIntent,
    response: Mapping[str, Any],
    response_type: str = "new_order",
) -> int:
    return store.insert_artifact(
        "exchange_responses",
        occurred_at=intent.decided_at,
        source="binance_usdm",
        symbol=intent.symbol,
        ref_id=f"exchange_response:{response_type}:{intent.symbol}:{intent.decided_at}",
        payload={"response_type": response_type, "response": dict(response), "intent": intent.to_dict()},
        event_type="exchange_response",
    )


def _positive_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _iso_after_seconds(value: str, seconds: float) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed.astimezone(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
