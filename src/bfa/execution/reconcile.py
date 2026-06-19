"""Read-only exchange reconciliation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Iterable, Mapping, Protocol

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent


class ReconciliationClient(Protocol):
    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class LocalOrderIntent:
    event_id: int
    status: str
    intent: OrderIntent
    client_order_id: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "status": self.status,
            "client_order_id": self.client_order_id,
            "symbol": self.intent.symbol,
            "side": self.intent.side,
            "quantity": self.intent.quantity,
            "decided_at": self.intent.decided_at,
        }


@dataclass(frozen=True)
class ReconciliationReport:
    matched: list[dict[str, Any]] = field(default_factory=list)
    missing_on_exchange: list[dict[str, Any]] = field(default_factory=list)
    unknown_on_exchange: list[dict[str, Any]] = field(default_factory=list)
    position_symbols: list[str] = field(default_factory=list)
    local_intent_count: int = 0
    open_order_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": [dict(item) for item in self.matched],
            "missing_on_exchange": [dict(item) for item in self.missing_on_exchange],
            "unknown_on_exchange": [dict(item) for item in self.unknown_on_exchange],
            "position_symbols": list(self.position_symbols),
            "local_intent_count": self.local_intent_count,
            "open_order_count": self.open_order_count,
        }


def reconcile_exchange_state(
    store: EventStore,
    client: ReconciliationClient,
    *,
    symbol: str | None = None,
    local_statuses: Iterable[str] = ("submitted",),
) -> ReconciliationReport:
    """Compare local submitted intents with live exchange open orders/positions."""

    normalized_symbol = symbol.upper() if symbol else None
    local_intents = _load_local_order_intents(
        store.connection,
        symbol=normalized_symbol,
        local_statuses=set(local_statuses),
    )
    open_orders = client.open_orders(normalized_symbol)
    positions = client.position_risk(normalized_symbol)

    open_by_client_id = {
        client_id: order
        for order in open_orders
        if (client_id := _order_client_id(order))
    }
    active_positions = _active_position_sides(positions)

    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    matched_client_ids: set[str] = set()

    for local in local_intents:
        exchange_order = open_by_client_id.get(local.client_order_id)
        if exchange_order is not None:
            matched_client_ids.add(local.client_order_id)
            matched.append(
                {
                    **local.to_summary(),
                    "match_type": "open_order",
                    "exchange_order_id": exchange_order.get("orderId"),
                }
            )
            continue

        if _position_matches_intent(local.intent, active_positions):
            matched.append({**local.to_summary(), "match_type": "position"})
            continue

        missing.append(local.to_summary())

    unknown = []
    for order in open_orders:
        client_id = _order_client_id(order)
        if client_id not in matched_client_ids:
            unknown.append(_exchange_order_summary(order))

    return ReconciliationReport(
        matched=matched,
        missing_on_exchange=missing,
        unknown_on_exchange=unknown,
        position_symbols=sorted(active_positions),
        local_intent_count=len(local_intents),
        open_order_count=len(open_orders),
    )


def _load_local_order_intents(
    connection: sqlite3.Connection,
    *,
    symbol: str | None,
    local_statuses: set[str],
) -> list[LocalOrderIntent]:
    params: list[str] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol)
    rows = connection.execute(
        f"""
        SELECT event_id, payload_json
        FROM order_intents
        {where}
        ORDER BY id ASC
        """,
        params,
    ).fetchall()

    intents: list[LocalOrderIntent] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        status = str(payload.get("status", ""))
        intent_payload = payload.get("intent")
        if status not in local_statuses or not isinstance(intent_payload, dict):
            continue
        intent = _intent_from_payload(intent_payload)
        intents.append(
            LocalOrderIntent(
                event_id=int(row["event_id"]),
                status=status,
                intent=intent,
                client_order_id=_client_order_id(intent),
            )
        )
    return intents


def _intent_from_payload(payload: Mapping[str, Any]) -> OrderIntent:
    return OrderIntent(
        symbol=str(payload["symbol"]).upper(),
        side=str(payload["side"]).upper(),
        quantity=float(payload["quantity"]),
        notional_usdt=float(payload["notional_usdt"]),
        entry_price=float(payload["entry_price"]),
        stop_price=float(payload["stop_price"]),
        target_price=float(payload["target_price"]),
        leverage=int(payload["leverage"]),
        mode=str(payload["mode"]),
        decided_at=str(payload["decided_at"]),
        order_type=str(payload.get("order_type", "MARKET")),
        reduce_only=bool(payload.get("reduce_only", False)),
        reason_codes=[str(item) for item in payload.get("reason_codes", [])],
        metadata=dict(payload.get("metadata", {})),
    )


def _client_order_id(intent: OrderIntent) -> str:
    explicit = intent.metadata.get("client_order_id")
    if explicit:
        return str(explicit)
    cleaned_time = "".join(ch for ch in intent.decided_at if ch.isdigit())
    return f"bfa-{intent.symbol.lower()}-{cleaned_time}"[:36]


def _order_client_id(order: Mapping[str, Any]) -> str | None:
    for key in ("clientOrderId", "newClientOrderId", "origClientOrderId"):
        value = order.get(key)
        if value:
            return str(value)
    return None


def _exchange_order_summary(order: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "client_order_id": _order_client_id(order),
        "exchange_order_id": order.get("orderId"),
        "symbol": str(order.get("symbol", "")).upper(),
        "side": str(order.get("side", "")).upper(),
        "status": order.get("status"),
    }


def _active_position_sides(positions: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    active: dict[str, str] = {}
    for position in positions:
        amount = _float(position.get("positionAmt"))
        if amount == 0:
            continue
        symbol = str(position.get("symbol", "")).upper()
        if symbol:
            active[symbol] = "BUY" if amount > 0 else "SELL"
    return active


def _position_matches_intent(intent: OrderIntent, active_positions: Mapping[str, str]) -> bool:
    return active_positions.get(intent.symbol) == intent.side


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
