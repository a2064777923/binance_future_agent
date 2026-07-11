"""SQLite schema management for the local event store."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 4
SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_CONNECT_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1000.0

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
    connection = sqlite3.connect(db_path, timeout=SQLITE_CONNECT_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if db_path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
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

        CREATE TABLE IF NOT EXISTS pending_limit_entries (
            intent_event_id INTEGER PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            client_order_id TEXT NOT NULL UNIQUE,
            strategy_leg TEXT,
            status TEXT NOT NULL,
            intent_json TEXT NOT NULL,
            resolved_at TEXT,
            resolution_status TEXT,
            FOREIGN KEY(intent_event_id) REFERENCES events(id)
        );

        CREATE INDEX IF NOT EXISTS idx_pending_limit_entries_status_expiry
            ON pending_limit_entries (status, expires_at, intent_event_id);
        CREATE INDEX IF NOT EXISTS idx_pending_limit_entries_symbol_status
            ON pending_limit_entries (symbol, status);

        CREATE TABLE IF NOT EXISTS position_excursions (
            position_key TEXT PRIMARY KEY,
            intent_event_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            position_side TEXT,
            entry_price REAL,
            stop_price REAL,
            target_price REAL,
            best_favorable_price REAL,
            worst_adverse_price REAL,
            max_favorable_r REAL NOT NULL DEFAULT 0,
            max_adverse_r REAL NOT NULL DEFAULT 0,
            max_target_progress REAL NOT NULL DEFAULT 0,
            first_observed_at TEXT NOT NULL,
            last_observed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_position_excursions_last_observed
            ON position_excursions (last_observed_at, position_key);
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

    connection.execute("CREATE INDEX IF NOT EXISTS idx_fills_ref_id ON fills (ref_id)")

    connection.execute(
        "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()
