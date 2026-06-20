import sqlite3
import unittest

from bfa.event_store.store import EventStore
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


def _count(connection, table):
    return connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]


if __name__ == "__main__":
    unittest.main()
