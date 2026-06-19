import json
import tempfile
import unittest
from pathlib import Path

from bfa.narrative.manual import ManualExportCollector


class NarrativeManualTests(unittest.TestCase):
    def test_reads_json_array_export_as_square_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "square.json"
            export.write_text(
                json.dumps(
                    [
                        {
                            "source_id": "square-1",
                            "author": "poster",
                            "text": "ESPORTSUSDT is hot and $SOL follows",
                            "published_at": "2026-06-19T09:00:00Z",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            records = ManualExportCollector(
                tmp,
                known_symbols=["SOLUSDT"],
                collected_at="2026-06-19T09:01:00Z",
            ).collect()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "binance_square")
        self.assertEqual(records[0].source_id, "square-1")
        self.assertEqual(records[0].symbol_mentions, ["ESPORTSUSDT", "SOLUSDT"])

    def test_reads_jsonl_and_text_exports_in_deterministic_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.jsonl").write_text(
                json.dumps({"source": "manual", "text": "BTCUSDT update", "source_id": "a1"}) + "\n",
                encoding="utf-8",
            )
            Path(tmp, "b.txt").write_text("ETH-USDT copied from chat", encoding="utf-8")

            records = ManualExportCollector(tmp, collected_at="now").collect()

        self.assertEqual([record.source_id for record in records], ["a1", "b"])
        self.assertEqual(records[0].symbol_mentions, ["BTCUSDT"])
        self.assertEqual(records[1].symbol_mentions, ["ETHUSDT"])

    def test_missing_export_dir_returns_no_records(self):
        records = ManualExportCollector("does-not-exist").collect()

        self.assertEqual(records, [])

    def test_malformed_file_raises_unless_tolerant(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.jsonl").write_text("{bad-json", encoding="utf-8")

            with self.assertRaises(ValueError):
                ManualExportCollector(tmp).collect()

            self.assertEqual(ManualExportCollector(tmp, tolerant=True).collect(), [])


if __name__ == "__main__":
    unittest.main()

