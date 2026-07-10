import sqlite3
import unittest
from unittest.mock import patch

from bfa.event_store.store import EventStore, SQLITE_LOCK_RETRY_DELAYS_SECONDS
from bfa.market.models import NormalizedMarketSnapshot
from bfa.narrative.models import normalize_narrative_record


class EventStoreRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def test_inserts_narrative_and_market_snapshot_with_event_rows(self):
        narrative = normalize_narrative_record(
            {
                "source": "binance_square",
                "source_id": "square-1",
                "author": "poster",
                "text": "BTCUSDT is hot",
                "published_at": "2026-06-19T09:00:00Z",
            },
            collected_at="2026-06-19T09:01:00Z",
        )
        snapshot = NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="ticker_24h",
            symbol="BTCUSDT",
            event_time="2026-06-19T09:00:30Z",
            received_at="2026-06-19T09:00:31Z",
            payload={"last_price": "70100"},
        )

        narrative_event_id = self.store.insert_narrative(narrative)
        market_event_id = self.store.insert_market_snapshot(snapshot)

        self.assertEqual(_count(self.connection, "narratives"), 1)
        self.assertEqual(_count(self.connection, "market_snapshots"), 1)
        self.assertEqual(_count(self.connection, "events"), 2)
        self.assertLess(narrative_event_id, market_event_id)

    def test_generic_category_inserts_future_artifacts(self):
        categories = [
            "candidates",
            "ai_decisions",
            "order_intents",
            "exchange_responses",
            "fills",
            "risk_state",
            "outcomes",
            "paper_signals",
            "paper_observations",
            "paper_outcomes",
        ]

        for category in categories:
            self.store.insert_artifact(
                category,
                occurred_at="2026-06-19T10:00:00Z",
                source="test",
                symbol="BTCUSDT",
                ref_id=f"{category}-1",
                payload={"category": category},
            )

        for category in categories:
            self.assertEqual(_count(self.connection, category), 1)
        self.assertEqual(_count(self.connection, "events"), len(categories))

    def test_events_between_is_stable_and_filters_by_symbol(self):
        self.store.insert_artifact(
            "candidates",
            occurred_at="2026-06-19T10:00:00Z",
            source="test",
            symbol="ETHUSDT",
            ref_id="eth",
            payload={"rank": 2},
        )
        self.store.insert_artifact(
            "candidates",
            occurred_at="2026-06-19T09:00:00Z",
            source="test",
            symbol="BTCUSDT",
            ref_id="btc",
            payload={"rank": 1},
        )

        all_events = self.store.events_between("2026-06-19T00:00:00Z", "2026-06-20T00:00:00Z")
        btc_events = self.store.events_between(
            "2026-06-19T00:00:00Z",
            "2026-06-20T00:00:00Z",
            symbol="BTCUSDT",
        )

        self.assertEqual([event.ref_id for event in all_events], ["btc", "eth"])
        self.assertEqual([event.ref_id for event in btc_events], ["btc"])
        self.assertEqual(btc_events[0].payload["rank"], 1)

    def test_invalid_category_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.insert_artifact(
                "not_a_table",
                occurred_at="2026-06-19T10:00:00Z",
                payload={},
            )

    def test_insert_artifact_retries_transient_database_lock(self):
        flaky = _FlakyConnection()
        store = EventStore(flaky)

        with patch("bfa.event_store.store.time.sleep") as sleep:
            event_id = store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-19T10:00:00Z",
                source="test",
                symbol="BTCUSDT",
                ref_id="order-1",
                payload={"status": "pending"},
            )

        self.assertEqual(event_id, 42)
        self.assertEqual(flaky.rollback_count, 1)
        sleep.assert_called_once_with(SQLITE_LOCK_RETRY_DELAYS_SECONDS[0])


def _count(connection, table):
    return connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]


class _Cursor:
    lastrowid = 42


class _FlakyConnection:
    row_factory = None

    def __init__(self):
        self.rollback_count = 0
        self._event_insert_attempts = 0

    def executescript(self, _script):
        return None

    def execute(self, sql, _params=()):
        if "INSERT INTO schema_version" in sql:
            return _Cursor()
        if "INSERT INTO events" in sql:
            self._event_insert_attempts += 1
            if self._event_insert_attempts == 1:
                raise sqlite3.OperationalError("database is locked")
        return _Cursor()

    def commit(self):
        return None

    def rollback(self):
        self.rollback_count += 1


if __name__ == "__main__":
    unittest.main()
