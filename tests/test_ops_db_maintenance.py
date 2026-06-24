import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.market.models import NormalizedMarketSnapshot
from bfa.narrative.models import normalize_narrative_record
from bfa.ops.db_maintenance import build_db_maintenance_report, build_raw_feed_maintenance_report


class DbMaintenanceTests(unittest.TestCase):
    def test_execute_deletes_only_old_market_snapshot_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                store = EventStore(connection)
                store.insert_market_snapshot(
                    _snapshot("OLDISOUSDT", "2026-06-23T05:00:00Z")
                )
                store.insert_market_snapshot(
                    _snapshot("NEWISOUSDT", "2026-06-23T08:00:00Z")
                )
                store.insert_market_snapshot(_snapshot("OLDEPOCHUSDT", 1_700_000_000_000))
                store.insert_narrative(
                    normalize_narrative_record(
                        {
                            "source": "test",
                            "source_id": "old-narrative",
                            "text": "BTCUSDT old narrative",
                            "published_at": "2026-06-23T04:00:00Z",
                        },
                        collected_at="2026-06-23T04:01:00Z",
                    )
                )
                store.insert_artifact(
                    "order_intents",
                    occurred_at="2026-06-23T04:02:00Z",
                    source="test",
                    symbol="BTCUSDT",
                    ref_id="old-order-intent",
                    event_type="order_intent",
                    payload={"status": "submitted"},
                )
            finally:
                connection.close()

            preview = build_db_maintenance_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
            )
            applied = build_db_maintenance_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
                execute=True,
            )
            market_count = _count(db_path, "market_snapshots")
            narrative_count = _count(db_path, "narratives")
            order_intent_count = _count(db_path, "order_intents")
            rows = _event_rows(db_path)

        self.assertEqual(preview.status, "db_maintenance_preview")
        self.assertEqual(preview.deletion_candidates, {"market_snapshots": 2, "events": 2})
        self.assertEqual(preview.batch_size, 5000)
        self.assertEqual(preview.max_delete_rows, 25000)
        self.assertEqual(applied.deleted, {"market_snapshots": 2, "events": 2})
        self.assertEqual(market_count, 1)
        self.assertEqual(narrative_count, 1)
        self.assertEqual(order_intent_count, 1)
        self.assertEqual(
            [(row["event_type"], row["ref_id"]) for row in rows],
            [
                ("narrative", "old-narrative"),
                ("order_intent", "old-order-intent"),
                ("market_snapshot", "ticker_24h:NEWISOUSDT:2026-06-23T08:00:00Z"),
            ],
        )

    def test_execute_deletes_old_epoch_ms_strings_without_cast_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                store = EventStore(connection)
                store.insert_market_snapshot(_snapshot("OLDEPCHUSDT", "1782160000000"))
                store.insert_market_snapshot(_snapshot("NEWEPOCHUSDT", "1782200000000"))
            finally:
                connection.close()

            applied = build_db_maintenance_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
                execute=True,
            )
            rows = _event_rows(db_path)

        self.assertEqual(applied.deletion_candidates, {"market_snapshots": 1, "events": 1})
        self.assertEqual(applied.deleted, {"market_snapshots": 1, "events": 1})
        self.assertEqual(
            [(row["event_type"], row["ref_id"]) for row in rows],
            [("market_snapshot", "ticker_24h:NEWEPOCHUSDT:1782200000000")],
        )

    def test_execute_limits_market_snapshot_deletes_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                store = EventStore(connection)
                for index in range(5):
                    store.insert_market_snapshot(
                        _snapshot(f"OLD{index}USDT", "2026-06-23T05:00:00Z")
                    )
            finally:
                connection.close()

            applied = build_db_maintenance_report(
                load_config(
                    {
                        "BFA_DB_PATH": str(db_path),
                        "BFA_DB_MAINTENANCE_BATCH_SIZE": "2",
                        "BFA_DB_MAINTENANCE_MAX_DELETE_ROWS": "3",
                    }
                ),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
                execute=True,
            )
            market_count = _count(db_path, "market_snapshots")
            event_count = len(_event_rows(db_path))

        self.assertEqual(applied.deletion_candidates, {"market_snapshots": 5, "events": 5})
        self.assertEqual(applied.deleted, {"market_snapshots": 3, "events": 3})
        self.assertEqual(applied.batch_size, 2)
        self.assertEqual(applied.max_delete_rows, 3)
        self.assertIn("delete_limited", applied.reasons)
        self.assertEqual(market_count, 2)
        self.assertEqual(event_count, 2)

    def test_vacuum_is_noop_in_preview_and_runs_with_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                EventStore(connection).insert_market_snapshot(
                    _snapshot("OLDISOUSDT", "2026-06-23T05:00:00Z")
                )
            finally:
                connection.close()

            preview = build_db_maintenance_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
                vacuum=True,
            )
            applied = build_db_maintenance_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                retention_hours=6,
                now="2026-06-23T12:00:00Z",
                execute=True,
                vacuum=True,
            )

        self.assertIn("vacuum_requested_but_execute_false", preview.reasons)
        self.assertEqual(preview.deleted, {"market_snapshots": 0, "events": 0})
        self.assertEqual(applied.status, "db_maintenance_applied_vacuumed")
        self.assertIn("vacuum_applied", applied.reasons)

    def test_raw_feed_cleanup_only_tracks_binance_raw_gzip_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old_raw = directory / "binance-usdm-raw-20260621T000000Z.gz"
            new_raw = directory / "binance-usdm-raw-20260623T110000Z.gz"
            other_gzip = directory / "unrelated.gz"
            old_raw.write_bytes(b"old")
            new_raw.write_bytes(b"new")
            other_gzip.write_bytes(b"keep")
            old_time = datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC).timestamp()
            new_time = datetime(2026, 6, 23, 11, 0, 0, tzinfo=UTC).timestamp()
            for path, mtime in (
                (old_raw, old_time),
                (new_raw, new_time),
                (other_gzip, old_time),
            ):
                path.touch()
                path.chmod(0o600)
                path.stat()
                os.utime(path, (mtime, mtime))

            report = build_raw_feed_maintenance_report(
                load_config({}),
                raw_feed_dir=str(directory),
                retention_hours=24,
                now="2026-06-23T12:00:00Z",
                execute=True,
            )
            old_raw_exists = old_raw.exists()
            new_raw_exists = new_raw.exists()
            other_gzip_exists = other_gzip.exists()

        self.assertEqual(report.before_file_count, 2)
        self.assertEqual([Path(item.path).name for item in report.deleted_files], [old_raw.name])
        self.assertFalse(old_raw_exists)
        self.assertTrue(new_raw_exists)
        self.assertTrue(other_gzip_exists)


def _snapshot(symbol: str, event_time) -> NormalizedMarketSnapshot:
    return NormalizedMarketSnapshot(
        source="binance_usdm",
        event_type="ticker_24h",
        symbol=symbol,
        event_time=event_time,
        received_at=event_time,
        payload={"last_price": "1.0"},
    )


def _count(db_path: Path, table: str) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    finally:
        connection.close()


def _event_rows(db_path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            """
            SELECT event_type, ref_id
            FROM events
            ORDER BY occurred_at ASC, id ASC
            """
        ).fetchall()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
