"""Repository helpers for the SQLite event store."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Mapping

from bfa.event_store.migrations import CATEGORY_TABLES, migrate
from bfa.event_store.models import StoredEvent
from bfa.market.models import NormalizedMarketSnapshot
from bfa.narrative.models import NormalizedNarrativeRecord


SQLITE_LOCK_RETRY_DELAYS_SECONDS = (0.05, 0.15, 0.35)


class EventStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        migrate(self.connection)

    def insert_narrative(self, record: NormalizedNarrativeRecord) -> int:
        payload = record.to_dict()
        return self.insert_artifact(
            "narratives",
            occurred_at=record.published_at or record.collected_at,
            source=record.source,
            symbol=record.symbol_mentions[0] if record.symbol_mentions else None,
            ref_id=record.source_id,
            payload=payload,
            event_type="narrative",
        )

    def insert_market_snapshot(self, snapshot: NormalizedMarketSnapshot) -> int:
        payload = snapshot.to_dict()
        return self.insert_artifact(
            "market_snapshots",
            occurred_at=str(snapshot.event_time or snapshot.received_at),
            source=snapshot.source,
            symbol=snapshot.symbol,
            ref_id=f"{snapshot.event_type}:{snapshot.symbol}:{snapshot.event_time}",
            payload=payload,
            event_type="market_snapshot",
        )

    def insert_artifact(
        self,
        category: str,
        *,
        occurred_at: str,
        payload: Mapping[str, Any],
        source: str | None = None,
        symbol: str | None = None,
        ref_id: str | None = None,
        event_type: str | None = None,
    ) -> int:
        _validate_category(category)
        payload_json = _to_json(payload)
        return self._with_lock_retry(
            lambda: self._insert_artifact_once(
                category,
                occurred_at=occurred_at,
                payload_json=payload_json,
                source=source,
                symbol=symbol,
                ref_id=ref_id,
                event_type=event_type,
            )
        )

    def _insert_artifact_once(
        self,
        category: str,
        *,
        occurred_at: str,
        payload_json: str,
        source: str | None,
        symbol: str | None,
        ref_id: str | None,
        event_type: str | None,
    ) -> int:
        event_cursor = self.connection.execute(
            """
            INSERT INTO events (event_type, occurred_at, source, symbol, ref_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_type or category, occurred_at, source, symbol, ref_id, payload_json),
        )
        event_id = int(event_cursor.lastrowid)
        self.connection.execute(
            f"""
            INSERT INTO {category} (occurred_at, source, symbol, ref_id, payload_json, event_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (occurred_at, source, symbol, ref_id, payload_json, event_id),
        )
        self.connection.commit()
        return event_id

    def _with_lock_retry(self, operation):
        delays = (*SQLITE_LOCK_RETRY_DELAYS_SECONDS, None)
        for delay in delays:
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                if not _is_database_locked(exc) or delay is None:
                    raise
                self.connection.rollback()
                time.sleep(delay)
        raise RuntimeError("unreachable sqlite lock retry state")

    def events_between(
        self,
        start: str,
        end: str,
        *,
        symbol: str | None = None,
    ) -> list[StoredEvent]:
        params: list[str] = [start, end]
        where = "occurred_at >= ? AND occurred_at <= ?"
        if symbol:
            where += " AND symbol = ?"
            params.append(symbol.upper())
        rows = self.connection.execute(
            f"""
            SELECT id, event_type, occurred_at, source, symbol, ref_id, payload_json
            FROM events
            WHERE {where}
            ORDER BY occurred_at ASC, id ASC
            """,
            params,
        ).fetchall()
        return [_row_to_event(row) for row in rows]


def _validate_category(category: str) -> None:
    if category not in CATEGORY_TABLES:
        allowed = ", ".join(CATEGORY_TABLES)
        raise ValueError(f"event category must be one of: {allowed}")


def _to_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, ensure_ascii=False)


def _is_database_locked(exc: sqlite3.OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


def _row_to_event(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        id=int(row["id"]),
        event_type=str(row["event_type"]),
        occurred_at=str(row["occurred_at"]),
        source=row["source"],
        symbol=row["symbol"],
        ref_id=row["ref_id"],
        payload=json.loads(row["payload_json"]),
    )

