"""Closed-trade outcome reconstruction from read-only Binance fills."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
import sqlite3
from typing import Any, Mapping, Protocol

from bfa.event_store.store import EventStore


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
    source_status: str = "submitted"
    original_event_id: int | None = None
    client_order_id: str | None = None
    exchange_order_id: int | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "leverage": self.leverage,
            "source_status": self.source_status,
            "original_event_id": self.original_event_id,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "persist_closed": self.persist_closed,
            "include_reconciled": self.include_reconciled,
            "summary": {
                "submitted_intents": len(self.items),
                "checked": sum(1 for item in self.items if item.fetched),
                "fetch_error": sum(1 for item in self.items if item.status == "fetch_error"),
                "already_reconciled": sum(
                    1 for item in self.items if item.status == "already_reconciled"
                ),
                "closed": sum(1 for item in self.items if item.status == "closed"),
                "open_or_partial": sum(1 for item in self.items if item.status == "open_or_partial"),
                "unreconciled": sum(1 for item in self.items if item.status == "unreconciled"),
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
            "items": [item.to_dict() for item in self.items],
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
    start_time = _iso_to_epoch_ms(intent.occurred_at)
    trades = client.user_trades(
        intent.symbol,
        start_time=start_time,
        end_time=_capped_user_trades_end_time(start_time),
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
    max_intents: int | None = None,
) -> TradeOutcomeSweepReport:
    intents = load_submitted_intents(store.connection, symbol=symbol, max_intents=max_intents)
    fetchable_intents = [
        intent
        for intent in intents
        if include_reconciled or not _has_closed_outcome_for_intent(store.connection, intent)
    ]
    trade_batches, fetch_errors = _fetch_trade_batches(client, fetchable_intents, limit=limit)
    used_trade_keys = _persisted_trade_keys(store.connection, trade_batches)
    known_entry_order_ids = _known_entry_order_ids_by_symbol(fetchable_intents)
    items: list[TradeOutcomeSweepItem] = []
    for intent in intents:
        if _has_closed_outcome_for_intent(store.connection, intent) and not include_reconciled:
            items.append(
                TradeOutcomeSweepItem(
                    intent=intent,
                    status="already_reconciled",
                    fetched=False,
                    reason="closed_outcome_exists",
                )
            )
            continue
        if intent.symbol in fetch_errors:
            exc = fetch_errors[intent.symbol]
            items.append(
                TradeOutcomeSweepItem(
                    intent=intent,
                    status="fetch_error",
                    fetched=False,
                    reason=f"{exc.__class__.__name__}:{exc}",
                )
            )
            continue
        trades = _trades_for_intent(
            intent,
            trade_batches.get(intent.symbol, []),
            used_trade_keys=used_trade_keys,
            known_entry_order_ids=known_entry_order_ids.get(intent.symbol, set()),
        )
        if trades is None:
            items.append(
                TradeOutcomeSweepItem(
                    intent=intent,
                    status="unreconciled",
                    fetched=True,
                    reason="ambiguous_trade_attribution",
                )
            )
            continue
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
        used_trade_keys.update(_trade_keys(intent.symbol, trades))
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
        if str(payload.get("status") or "") != "submitted":
            continue
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            continue
        if not _is_entry_intent(intent):
            continue
        if _watchdog_submitted_intent_explicitly_unfilled(connection, intent):
            continue
        return _local_intent_from_payload(row, payload, intent)
    return None


def load_submitted_intents(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
    max_intents: int | None = None,
) -> list[LocalSubmittedIntent]:
    params: list[str] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol.upper())
    limit_clause = ""
    if max_intents is not None and max_intents > 0:
        limit_clause = "LIMIT ?"
        params.append(str(max_intents))
    rows = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM (
            SELECT event_id, occurred_at, symbol, payload_json, id
            FROM order_intents
            {where}
            ORDER BY occurred_at DESC, id DESC
            {limit_clause}
        )
        ORDER BY occurred_at ASC, id ASC
        """,
        params,
    ).fetchall()
    intents: list[LocalSubmittedIntent] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        status = str(payload.get("status") or "")
        if status != "submitted":
            continue
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            continue
        if not _is_entry_intent(intent):
            continue
        if _watchdog_submitted_intent_explicitly_unfilled(connection, intent):
            continue
        intents.append(_local_intent_from_payload(row, payload, intent))
    return intents


def _local_intent_from_payload(
    row: sqlite3.Row,
    payload: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> LocalSubmittedIntent:
    metadata = intent.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    original_event_id = _int_or_none(metadata.get("pending_intent_event_id"))
    client_order_id = metadata.get("client_order_id") or metadata.get("pending_client_order_id")
    exchange_order_id = metadata.get("exchange_order_id")
    occurred_at = str(row["occurred_at"])
    original_time = _original_pending_time(metadata, intent)
    if original_event_id is not None and original_time:
        # Pending-limit watchdog rows are written when a late fill is reconciled.
        # Use the original signal/intent time for trade-history windows so the
        # entry fill is not missed.
        occurred_at = original_time
    return LocalSubmittedIntent(
        event_id=int(row["event_id"]),
        occurred_at=occurred_at,
        symbol=str(row["symbol"] or intent.get("symbol", "")).upper(),
        side=str(intent.get("side", "")).upper(),
        quantity=float(intent.get("quantity", 0)),
        entry_price=float(intent.get("entry_price", 0)),
        leverage=int(intent.get("leverage", 0)),
        source_status=str(payload.get("status") or "submitted"),
        original_event_id=original_event_id,
        client_order_id=str(client_order_id) if client_order_id is not None else None,
        exchange_order_id=exchange_order_id,
    )


def _original_pending_time(metadata: Mapping[str, Any], intent: Mapping[str, Any]) -> str | None:
    latency = metadata.get("latency")
    if isinstance(latency, Mapping):
        for key in ("agent_started_at", "signal_time"):
            value = latency.get(key)
            if value:
                return str(value)
        for key in ("entry_submit_started_at_ms", "signal_time_ms", "agent_started_at_ms"):
            value = latency.get(key)
            iso = _epoch_ms_to_iso(value)
            if iso:
                return iso
    for key in ("created_at", "submitted_at"):
        value = metadata.get(key)
        if value:
            return str(value)
    decided_at = intent.get("decided_at")
    return str(decided_at) if decided_at else None


def _is_entry_intent(intent: Mapping[str, Any]) -> bool:
    metadata = intent.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("position_adjustment"):
        return False
    if bool(intent.get("reduce_only")):
        return False
    order_type = str(intent.get("order_type") or "MARKET").upper()
    return order_type in {"MARKET", "LIMIT"}


def _fetch_trade_batches(
    client: TradeHistoryClient,
    intents: list[LocalSubmittedIntent],
    *,
    limit: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Exception]]:
    by_symbol: dict[str, list[LocalSubmittedIntent]] = {}
    for intent in intents:
        by_symbol.setdefault(intent.symbol, []).append(intent)
    batches: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, Exception] = {}
    for symbol, symbol_intents in by_symbol.items():
        start_time = min(_iso_to_epoch_ms(intent.occurred_at) for intent in symbol_intents)
        try:
            batches[symbol] = list(
                client.user_trades(
                    symbol,
                    start_time=start_time,
                    end_time=_capped_user_trades_end_time(start_time),
                    limit=limit,
                )
            )
        except Exception as exc:
            errors[symbol] = exc
    return batches, errors


def _trades_for_intent(
    intent: LocalSubmittedIntent,
    trades: list[Mapping[str, Any]],
    *,
    used_trade_keys: set[tuple[str, str]],
    known_entry_order_ids: set[str],
) -> list[Mapping[str, Any]] | None:
    available = [
        trade
        for trade in trades
        if _trade_key(intent.symbol, trade) not in used_trade_keys
        and int(trade.get("time") or 0) >= _iso_to_epoch_ms(intent.occurred_at)
    ]
    if intent.exchange_order_id is not None:
        entries = [trade for trade in available if str(trade.get("orderId")) == str(intent.exchange_order_id)]
        if not entries:
            return []
        return _round_trip_prefix(
            intent,
            available,
            required_entry_order_id=intent.exchange_order_id,
            known_entry_order_ids=known_entry_order_ids,
        )
    # No exchange order id means attribution cannot be made safely when the
    # symbol has more than one possible entry-side order.
    entry_order_ids = {
        str(trade.get("orderId"))
        for trade in available
        if str(trade.get("side") or "").upper() == intent.side.upper()
        and abs(_float(trade.get("realizedPnl"))) < 1e-12
    }
    if len(entry_order_ids) != 1:
        return None if available else []
    only_order_id = next(iter(entry_order_ids))
    return _round_trip_prefix(
        intent,
        available,
        required_entry_order_id=only_order_id,
        known_entry_order_ids=known_entry_order_ids,
    )


def _round_trip_prefix(
    intent: LocalSubmittedIntent,
    trades: list[Mapping[str, Any]],
    *,
    required_entry_order_id: int | str,
    known_entry_order_ids: set[str],
) -> list[Mapping[str, Any]] | None:
    ordered = sorted(trades, key=lambda item: int(item.get("time") or 0))
    selected: list[Mapping[str, Any]] = []
    net_quantity = 0.0
    started = False
    for trade in ordered:
        if not started:
            if str(trade.get("orderId")) != str(required_entry_order_id):
                if (
                    str(trade.get("side") or "").upper() == intent.side.upper()
                    and str(trade.get("orderId")) in known_entry_order_ids
                ):
                    return None
                continue
            started = True
        elif (
            str(trade.get("side") or "").upper() == intent.side.upper()
            and str(trade.get("orderId")) in known_entry_order_ids
            and str(trade.get("orderId")) != str(required_entry_order_id)
        ):
            return None
        quantity = _float(trade.get("qty"))
        side = str(trade.get("side") or "").upper()
        selected.append(trade)
        net_quantity += quantity if side == "BUY" else -quantity
        if len(selected) > 1 and abs(net_quantity) < 1e-12:
            break
    return selected


def _known_entry_order_ids_by_symbol(
    intents: list[LocalSubmittedIntent],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for intent in intents:
        if intent.exchange_order_id is None:
            continue
        result.setdefault(intent.symbol, set()).add(str(intent.exchange_order_id))
    return result


def _persisted_trade_keys(
    connection: sqlite3.Connection,
    trade_batches: Mapping[str, list[Mapping[str, Any]]],
) -> set[tuple[str, str]]:
    ref_ids = sorted(
        {
            f"fill:{symbol.upper()}:{trade.get('id')}"
            for symbol, trades in trade_batches.items()
            for trade in trades
        }
    )
    rows = []
    for offset in range(0, len(ref_ids), 500):
        batch = ref_ids[offset : offset + 500]
        if not batch:
            continue
        placeholders = ",".join("?" for _ in batch)
        rows.extend(
            connection.execute(
                f"SELECT symbol, ref_id FROM fills WHERE ref_id IN ({placeholders})",
                batch,
            ).fetchall()
        )
    keys: set[tuple[str, str]] = set()
    for row in rows:
        ref_id = str(row["ref_id"] or "")
        trade_id = ref_id.rsplit(":", 1)[-1]
        keys.add((str(row["symbol"] or "").upper(), trade_id))
    return keys


def _trade_keys(symbol: str, trades: list[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {_trade_key(symbol, trade) for trade in trades}


def _trade_key(symbol: str, trade: Mapping[str, Any]) -> tuple[str, str]:
    return (str(symbol).upper(), str(trade.get("id")))


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


_BINANCE_USER_TRADES_MAX_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000


def _capped_user_trades_end_time(
    start_time_ms: int,
    *,
    requested_end_time: int | None = None,
    now_ms: int | None = None,
) -> int:
    max_end_time = start_time_ms + _BINANCE_USER_TRADES_MAX_INTERVAL_MS - 1000
    current_end_time = int(datetime.now(tz=UTC).timestamp() * 1000) if now_ms is None else int(now_ms)
    max_end_time = min(max_end_time, current_end_time)
    if requested_end_time is None:
        return max(max_end_time, start_time_ms + 1)
    return max(min(requested_end_time, max_end_time), start_time_ms + 1)


def _next_same_symbol_start_ms(intents: list[LocalSubmittedIntent], current_index: int) -> int | None:
    current = intents[current_index]
    current_start = _iso_to_epoch_ms(current.occurred_at)
    for later in intents[current_index + 1 :]:
        if later.symbol != current.symbol:
            continue
        later_start = _iso_to_epoch_ms(later.occurred_at)
        if later_start <= current_start:
            continue
        return later_start - 1
    return None


def _has_closed_outcome_for_intent(connection: sqlite3.Connection, intent: LocalSubmittedIntent) -> bool:
    if _has_closed_outcome_for_event(connection, intent.event_id):
        return True
    if intent.original_event_id is not None and _has_closed_outcome_for_event(connection, intent.original_event_id):
        return True
    return False


def _watchdog_submitted_intent_explicitly_unfilled(
    connection: sqlite3.Connection,
    intent: Mapping[str, Any],
) -> bool:
    metadata = intent.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    pending_event_id = _int_or_none(metadata.get("pending_intent_event_id"))
    if pending_event_id is None:
        return False
    client_order_id = metadata.get("pending_client_order_id") or metadata.get("client_order_id")
    rows = connection.execute(
        """
        SELECT payload_json
        FROM exchange_responses
        WHERE payload_json LIKE ?
          AND payload_json LIKE ?
        ORDER BY occurred_at DESC, id DESC
        LIMIT 20
        """,
        (
            "%pending_limit_watchdog%",
            f"%{pending_event_id}%",
        ),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        response = payload.get("response")
        if not isinstance(response, Mapping):
            continue
        if _int_or_none(response.get("pending_intent_event_id")) != pending_event_id:
            continue
        if client_order_id and str(response.get("client_order_id") or "") != str(client_order_id):
            continue
        query = response.get("entry_order_query")
        if not isinstance(query, Mapping):
            return False
        status = str(query.get("status") or "").upper()
        executed = _float(query.get("executedQty")) or _float(query.get("executedQuantity")) or 0.0
        return status != "FILLED" and executed <= 0.0
    return False


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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
