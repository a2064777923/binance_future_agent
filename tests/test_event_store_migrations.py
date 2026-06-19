import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.event_store.migrations import CATEGORY_TABLES, SCHEMA_VERSION, connect, migrate


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
        for table in CATEGORY_TABLES:
            self.assertIn(table, tables)

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
