"""Closed-trade outcome reconstruction from read-only Binance fills."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
import sqlite3
from typing import Any, Mapping, Protocol

from bfa.event_store.store import EventStore


RECONCILABLE_INTENT_STATUSES = frozenset(
    {
        "submitted",
        "entry_order_partial_filled_protected",
        "entry_order_reconciled_from_position",
        "entry_order_filled_no_active_position",
        "protective_order_degraded_stop_only",
        "protective_order_failed_open",
        "protective_order_failed_closed",
        "protective_order_failed_no_position",
    }
)


class TradeHistoryClient(Protocol):
    def user_trades(
        self,
        symbol: str,
        *,
        start_time=None,
        end_time=None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class LocalSubmittedIntent:
    event_id: int
    occurred_at: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    leverage: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "leverage": self.leverage,
        }


@dataclass(frozen=True)
class TradeOutcome:
    intent: LocalSubmittedIntent
    status: str
    trade_count: int
    net_quantity: float
    gross_realized_pnl_usdt: float
    commission_usdt: float
    net_realized_pnl_usdt: float
    first_trade_time: str | None = None
    last_trade_time: str | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    persisted: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "status": self.status,
            "trade_count": self.trade_count,
            "net_quantity": self.net_quantity,
            "gross_realized_pnl_usdt": self.gross_realized_pnl_usdt,
            "commission_usdt": self.commission_usdt,
            "net_realized_pnl_usdt": self.net_realized_pnl_usdt,
            "first_trade_time": self.first_trade_time,
            "last_trade_time": self.last_trade_time,
            "trades": [dict(item) for item in self.trades],
            "persisted": dict(self.persisted),
        }


@dataclass(frozen=True)
class TradeOutcomeSweepItem:
    intent: LocalSubmittedIntent
    status: str
    fetched: bool
    outcome: TradeOutcome | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "status": self.status,
            "fetched": self.fetched,
            "reason": self.reason,
            "outcome": self.outcome.to_dict() if self.outcome else None,
        }


@dataclass(frozen=True)
class TradeOutcomeSweepReport:
    persist_closed: bool
    include_reconciled: bool
    items: list[TradeOutcomeSweepItem] = field(default_factory=list)

    def to_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        return {
            "persist_closed": self.persist_closed,
            "include_reconciled": self.include_reconciled,
            "summary": {
                "submitted_intents": len(self.items),
                "reconcilable_intents": len(self.items),
                "checked": sum(1 for item in self.items if item.fetched),
                "already_reconciled": sum(
                    1 for item in self.items if item.status == "already_reconciled"
                ),
                "closed": sum(1 for item in self.items if item.status == "closed"),
                "open_or_partial": sum(1 for item in self.items if item.status == "open_or_partial"),
                "persisted_outcomes_inserted": sum(
                    int((item.outcome.persisted or {}).get("outcome_inserted", 0))
                    for item in self.items
                    if item.outcome is not None
                ),
                "persisted_fills_inserted": sum(
                    int((item.outcome.persisted or {}).get("fills", 0))
                    for item in self.items
                    if item.outcome is not None
                ),
                "existing_fills": sum(
                    int((item.outcome.persisted or {}).get("fills_existing", 0))
                    for item in self.items
                    if item.outcome is not None
                ),
            },
            "items": [item.to_dict() for item in self.items] if include_items else [],
        }


def build_latest_trade_outcome(
    store: EventStore,
    client: TradeHistoryClient,
    *,
    symbol: str | None = None,
    persist: bool = False,
) -> TradeOutcome | None:
    intent = load_latest_submitted_intent(store.connection, symbol=symbol)
    if intent is None:
        return None
    trades = client.user_trades(
        intent.symbol,
        start_time=_iso_to_epoch_ms(intent.occurred_at),
        limit=500,
    )
    outcome = summarize_trade_outcome(intent, trades)
    if persist:
        persisted = persist_trade_outcome(store, outcome)
        outcome = TradeOutcome(
            intent=outcome.intent,
            status=outcome.status,
            trade_count=outcome.trade_count,
            net_quantity=outcome.net_quantity,
            gross_realized_pnl_usdt=outcome.gross_realized_pnl_usdt,
            commission_usdt=outcome.commission_usdt,
            net_realized_pnl_usdt=outcome.net_realized_pnl_usdt,
            first_trade_time=outcome.first_trade_time,
            last_trade_time=outcome.last_trade_time,
            trades=list(outcome.trades),
            persisted=persisted,
        )
    return outcome


def reconcile_submitted_trade_outcomes(
    store: EventStore,
    client: TradeHistoryClient,
    *,
    symbol: str | None = None,
    persist_closed: bool = False,
    include_reconciled: bool = False,
    limit: int = 500,
    since: str | None = None,
) -> TradeOutcomeSweepReport:
    intents = load_submitted_intents(store.connection, symbol=symbol, since=since)
    items: list[TradeOutcomeSweepItem] = []
    for index, intent in enumerate(intents):
        if _has_closed_outcome_for_event(store.connection, intent.event_id) and not include_reconciled:
            items.append(
                TradeOutcomeSweepItem(
                    intent=intent,
                    status="already_reconciled",
                    fetched=False,
                    reason="closed_outcome_exists",
                )
            )
            continue
        trades = client.user_trades(
            intent.symbol,
            start_time=_iso_to_epoch_ms(intent.occurred_at),
            end_time=_next_same_symbol_start_ms(intents, index),
            limit=limit,
        )
        outcome = summarize_trade_outcome(intent, trades)
        if persist_closed and outcome.status == "closed":
            outcome = replace(outcome, persisted=persist_trade_outcome(store, outcome))
        items.append(
            TradeOutcomeSweepItem(
                intent=intent,
                status=outcome.status,
                fetched=True,
                outcome=outcome,
            )
        )
    return TradeOutcomeSweepReport(
        persist_closed=persist_closed,
        include_reconciled=include_reconciled,
        items=items,
    )


def load_latest_submitted_intent(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
) -> LocalSubmittedIntent | None:
    params: list[str] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol.upper())
    rows = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        {where}
        ORDER BY occurred_at DESC, id DESC
        """,
        params,
    ).fetchall()
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if str(payload.get("status") or "") not in RECONCILABLE_INTENT_STATUSES:
            continue
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            continue
        return LocalSubmittedIntent(
            event_id=int(row["event_id"]),
            occurred_at=str(row["occurred_at"]),
            symbol=str(row["symbol"] or intent.get("symbol", "")).upper(),
            side=str(intent.get("side", "")).upper(),
            quantity=float(intent.get("quantity", 0)),
            entry_price=float(intent.get("entry_price", 0)),
            leverage=int(intent.get("leverage", 0)),
        )
    return None


def load_submitted_intents(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
    since: str | None = None,
) -> list[LocalSubmittedIntent]:
    params: list[str] = []
    filters: list[str] = []
    if symbol:
        filters.append("symbol = ?")
        params.append(symbol.upper())
    if since:
        filters.append("occurred_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        {where}
        ORDER BY occurred_at ASC, id ASC
        """,
        params,
    ).fetchall()
    intents: list[LocalSubmittedIntent] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if str(payload.get("status") or "") not in RECONCILABLE_INTENT_STATUSES:
            continue
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            continue
        intents.append(
            LocalSubmittedIntent(
                event_id=int(row["event_id"]),
                occurred_at=str(row["occurred_at"]),
                symbol=str(row["symbol"] or intent.get("symbol", "")).upper(),
                side=str(intent.get("side", "")).upper(),
                quantity=float(intent.get("quantity", 0)),
                entry_price=float(intent.get("entry_price", 0)),
                leverage=int(intent.get("leverage", 0)),
            )
        )
    return intents


def summarize_trade_outcome(
    intent: LocalSubmittedIntent,
    trades: list[Mapping[str, Any]],
) -> TradeOutcome:
    normalized = [_trade_summary(trade) for trade in sorted(trades, key=lambda item: int(item.get("time", 0)))]
    net_quantity = 0.0
    for trade in normalized:
        qty = float(trade["qty"])
        side = str(trade["side"]).upper()
        net_quantity += qty if side == "BUY" else -qty
    gross_pnl = sum(float(trade["realized_pnl_usdt"]) for trade in normalized)
    commission = sum(float(trade["commission_usdt"]) for trade in normalized)
    status = "closed" if normalized and abs(net_quantity) < 1e-12 else "open_or_partial"
    return TradeOutcome(
        intent=intent,
        status=status,
        trade_count=len(normalized),
        net_quantity=round(net_quantity, 12),
        gross_realized_pnl_usdt=round(gross_pnl, 8),
        commission_usdt=round(commission, 8),
        net_realized_pnl_usdt=round(gross_pnl - commission, 8),
        first_trade_time=normalized[0]["time_iso"] if normalized else None,
        last_trade_time=normalized[-1]["time_iso"] if normalized else None,
        trades=normalized,
    )


def persist_trade_outcome(store: EventStore, outcome: TradeOutcome) -> dict[str, int]:
    fill_ids = []
    existing_fills = 0
    for trade in outcome.trades:
        ref_id = f"fill:{outcome.intent.symbol}:{trade['trade_id']}"
        existing_fill_id = _existing_event_id(store.connection, "fills", ref_id)
        if existing_fill_id is not None:
            existing_fills += 1
            continue
        fill_ids.append(
            store.insert_artifact(
                "fills",
                occurred_at=str(trade["time_iso"]),
                source="binance_usdm",
                symbol=outcome.intent.symbol,
                ref_id=ref_id,
                payload={"intent_event_id": outcome.intent.event_id, "trade": trade},
                event_type="fill",
            )
        )
    outcome_ref_id = f"outcome:{outcome.intent.event_id}:{outcome.status}"
    existing_outcome_id = _existing_event_id(store.connection, "outcomes", outcome_ref_id)
    outcome_inserted = 0
    if existing_outcome_id is None:
        outcome_id = store.insert_artifact(
            "outcomes",
            occurred_at=outcome.last_trade_time or outcome.intent.occurred_at,
            source="binance_usdm",
            symbol=outcome.intent.symbol,
            ref_id=outcome_ref_id,
            payload={key: value for key, value in outcome.to_dict().items() if key != "persisted"},
            event_type="outcome",
        )
        outcome_inserted = 1
    else:
        outcome_id = existing_outcome_id
    return {
        "fills": len(fill_ids),
        "fills_existing": existing_fills,
        "outcomes": outcome_id,
        "outcome_inserted": outcome_inserted,
    }


def _trade_summary(trade: Mapping[str, Any]) -> dict[str, Any]:
    commission_asset = str(trade.get("commissionAsset", "USDT")).upper()
    commission = _float(trade.get("commission"))
    return {
        "trade_id": trade.get("id"),
        "order_id": trade.get("orderId"),
        "symbol": str(trade.get("symbol", "")).upper(),
        "side": str(trade.get("side", "")).upper(),
        "position_side": str(trade.get("positionSide", "")),
        "qty": _float(trade.get("qty")),
        "price": _float(trade.get("price")),
        "quote_qty": _float(trade.get("quoteQty")),
        "realized_pnl_usdt": _float(trade.get("realizedPnl")),
        "commission_usdt": commission if commission_asset == "USDT" else 0.0,
        "commission_asset": commission_asset,
        "buyer": bool(trade.get("buyer")),
        "maker": bool(trade.get("maker")),
        "time": trade.get("time"),
        "time_iso": _epoch_ms_to_iso(trade.get("time")),
    }


def _iso_to_epoch_ms(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def _next_same_symbol_start_ms(intents: list[LocalSubmittedIntent], current_index: int) -> int | None:
    current = intents[current_index]
    for later in intents[current_index + 1 :]:
        if later.symbol != current.symbol:
            continue
        return max(_iso_to_epoch_ms(later.occurred_at) - 1, _iso_to_epoch_ms(current.occurred_at))
    return None


def _epoch_ms_to_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _existing_event_id(connection: sqlite3.Connection, category: str, ref_id: str) -> int | None:
    row = connection.execute(
        f"""
        SELECT event_id
        FROM {category}
        WHERE ref_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (ref_id,),
    ).fetchone()
    if row is None or row["event_id"] is None:
        return None
    return int(row["event_id"])


def _has_closed_outcome_for_event(connection: sqlite3.Connection, event_id: int) -> bool:
    return _existing_event_id(connection, "outcomes", f"outcome:{event_id}:closed") is not None
