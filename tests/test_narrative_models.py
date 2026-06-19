import json
import unittest

from bfa.narrative.models import NormalizedNarrativeRecord, normalize_narrative_record


class NarrativeModelTests(unittest.TestCase):
    def test_record_serializes_to_plain_dict(self):
        record = NormalizedNarrativeRecord(
            source="binance_square",
            source_id="square-1",
            author="author",
            symbol_mentions=["BTCUSDT"],
            text="BTCUSDT update",
            url="https://example.test/post",
            published_at="2026-06-19T09:00:00Z",
            collected_at="2026-06-19T09:01:00Z",
            engagement={"likes": 5},
            raw={"id": "square-1"},
            quality_flags=[],
        )

        payload = record.to_dict()
        json.dumps(payload)

        self.assertEqual(payload["source"], "binance_square")
        self.assertEqual(payload["symbol_mentions"], ["BTCUSDT"])
        self.assertEqual(payload["engagement"], {"likes": 5})

    def test_normalizes_and_preserves_source_author_raw_context(self):
        record = normalize_narrative_record(
            {
                "source": " binance_square ",
                "id": " square-1 ",
                "author": " poster ",
                "text": "BTCUSDT BTCUSDT and $SOL are active",
                "symbol_mentions": ["BTCUSDT"],
                "engagement": {"likes": 10, "views": "1000"},
                "published_at": "2026-06-19T09:00:00Z",
            },
            known_symbols=["SOLUSDT"],
            collected_at="2026-06-19T09:01:00Z",
        )

        self.assertEqual(record.source, "binance_square")
        self.assertEqual(record.source_id, "square-1")
        self.assertEqual(record.author, "poster")
        self.assertEqual(record.symbol_mentions, ["BTCUSDT", "SOLUSDT"])
        self.assertEqual(record.engagement, {"likes": 10, "views": "1000"})
        self.assertEqual(record.quality_flags, [])
        self.assertEqual(record.raw["id"], " square-1 ")

    def test_missing_optional_fields_add_quality_flags_without_crashing(self):
        record = normalize_narrative_record(
            {"source": "manual", "text": "No ticker in this note"},
            collected_at="2026-06-19T09:01:00Z",
        )

        self.assertEqual(record.engagement, {})
        self.assertIn("missing_source_id", record.quality_flags)
        self.assertIn("missing_author", record.quality_flags)
        self.assertIn("missing_published_at", record.quality_flags)
        self.assertIn("no_symbol_mentions", record.quality_flags)

    def test_missing_source_or_text_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_narrative_record({"text": "BTCUSDT"})

        with self.assertRaises(ValueError):
            normalize_narrative_record({"source": "manual", "text": " "})


if __name__ == "__main__":
    unittest.main()

