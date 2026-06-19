import sqlite3
import unittest

from bfa.event_store.store import EventStore
from bfa.strategy.candidates import CandidateSignal
from bfa.strategy.store import persist_candidates


class StrategyStoreTests(unittest.TestCase):
    def test_persists_candidate_payloads(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            score=42.0,
            narrative_score=20.0,
            market_score=22.0,
            reason_codes=["narrative_heat", "price_momentum"],
            data_quality_notes=[],
            source_event_ids=[1],
            market_event_ids=[2],
            generated_at="2026-06-19T09:30:00Z",
            features={"mention_count": 1},
        )

        event_ids = persist_candidates(store, [candidate])

        self.assertEqual(len(event_ids), 1)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) AS count FROM candidates").fetchone()["count"],
            1,
        )
        payload = connection.execute("SELECT payload_json FROM candidates").fetchone()["payload_json"]
        self.assertIn("price_momentum", payload)


if __name__ == "__main__":
    unittest.main()

