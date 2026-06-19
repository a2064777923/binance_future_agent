import unittest

from bfa.narrative.dedup import dedup_key, deduplicate_records
from bfa.narrative.models import normalize_narrative_record


class NarrativeDedupTests(unittest.TestCase):
    def test_records_with_same_source_id_collapse(self):
        first = normalize_narrative_record(
            {"source": "binance_square", "source_id": "one", "text": "BTCUSDT first"},
            collected_at="2026-06-19T09:00:00Z",
        )
        second = normalize_narrative_record(
            {"source": "binance_square", "source_id": "one", "text": "BTCUSDT second"},
            collected_at="2026-06-19T09:01:00Z",
        )

        self.assertEqual(deduplicate_records([first, second]), [first])

    def test_records_without_source_id_collapse_by_fingerprint(self):
        first = normalize_narrative_record(
            {
                "source": "manual",
                "author": "desk",
                "text": "BTCUSDT   momentum",
                "published_at": "2026-06-19T09:11:00Z",
            },
            collected_at="2026-06-19T09:12:00Z",
        )
        second = normalize_narrative_record(
            {
                "source": "manual",
                "author": "desk",
                "text": "btcusdt momentum",
                "published_at": "2026-06-19T09:59:00Z",
            },
            collected_at="2026-06-19T09:59:30Z",
        )

        self.assertEqual(dedup_key(first), dedup_key(second))
        self.assertEqual(deduplicate_records([first, second]), [first])

    def test_non_duplicates_preserve_first_seen_order(self):
        first = normalize_narrative_record({"source": "manual", "source_id": "1", "text": "BTCUSDT"})
        second = normalize_narrative_record({"source": "manual", "source_id": "2", "text": "ETHUSDT"})

        self.assertEqual(deduplicate_records([first, second]), [first, second])


if __name__ == "__main__":
    unittest.main()

