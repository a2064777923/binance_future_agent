"""SQLite schema management for the local event store."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1

CATEGORY_TABLES = (
    "narratives",
    "market_snapshots",
    "decision_snapshots",
    "candidates",
    "trade_setups",
    "ai_decisions",
    "order_intents",
    "exchange_responses",
    "fills",
    "risk_state",
    "outcomes",
    "paper_signals",
    "paper_observations",
    "paper_outcomes",
)


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = str(path)
    if db_path not in {":memory:", ""}:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if db_path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source TEXT,
            symbol TEXT,
            ref_id TEXT,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_time_id
            ON events (occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_events_symbol_time
            ON events (symbol, occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_events_type_time
            ON events (event_type, occurred_at, id);
        """
    )

    for table in CATEGORY_TABLES:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                source TEXT,
                symbol TEXT,
                ref_id TEXT,
                payload_json TEXT NOT NULL,
                event_id INTEGER,
                FOREIGN KEY(event_id) REFERENCES events(id)
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_time_id ON {table} (occurred_at, id)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_symbol_time ON {table} (symbol, occurred_at, id)"
        )

    connection.execute(
        "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()
