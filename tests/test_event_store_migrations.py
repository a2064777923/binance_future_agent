import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.event_store.migrations import (
    CATEGORY_TABLES,
    SCHEMA_VERSION,
    SQLITE_BUSY_TIMEOUT_MS,
    connect,
    migrate,
)


class EventStoreMigrationTests(unittest.TestCase):
    def test_migration_creates_required_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = connect(Path(tmp) / "agent.sqlite")
            try:
                migrate(connection)
                tables = _table_names(connection)
            finally:
                connection.close()

        self.assertIn("schema_version", tables)
        self.assertIn("events", tables)
        self.assertIn("pending_limit_entries", tables)
        self.assertIn("latest_states", tables)
        for table in CATEGORY_TABLES:
            self.assertIn(table, tables)

    def test_file_connections_wait_for_concurrent_writer_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = connect(Path(tmp) / "agent.sqlite")
            try:
                timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(timeout, SQLITE_BUSY_TIMEOUT_MS)
        self.assertEqual(str(journal_mode).lower(), "wal")

    def test_migration_is_idempotent_and_preserves_schema_version(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row

        migrate(connection)
        migrate(connection)

        versions = connection.execute("SELECT version FROM schema_version").fetchall()
        self.assertEqual([row["version"] for row in versions], [SCHEMA_VERSION])

    def test_replay_indexes_exist(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        migrate(connection)

        indexes = _index_names(connection)

        self.assertIn("idx_events_time_id", indexes)
        self.assertIn("idx_events_symbol_time", indexes)
        self.assertIn("idx_narratives_time_id", indexes)
        self.assertIn("idx_market_snapshots_symbol_time", indexes)
        self.assertIn("idx_pending_limit_entries_status_expiry", indexes)
        self.assertIn("idx_pending_limit_entries_symbol_status", indexes)
        self.assertIn("idx_fills_ref_id", indexes)
        self.assertIn("idx_latest_states_type_updated", indexes)

    def test_pending_limit_query_uses_status_expiry_index(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        migrate(connection)

        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT intent_event_id
            FROM pending_limit_entries
            WHERE status = 'pending'
            ORDER BY expires_at ASC, intent_event_id ASC
            LIMIT 10
            """
        ).fetchall()

        detail = " ".join(str(row[3]) for row in plan)
        self.assertIn("idx_pending_limit_entries_status_expiry", detail)


def _table_names(connection):
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _index_names(connection):
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }


if __name__ == "__main__":
    unittest.main()
