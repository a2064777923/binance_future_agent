import json
import tempfile
import unittest
from pathlib import Path

from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.jsonl_writer import write_jsonl_records
from bfa.narrative.models import normalize_narrative_record


class FakeCollector:
    def __init__(self, records):
        self.records = records

    def collect(self):
        return list(self.records)


class NarrativeCollectorTests(unittest.TestCase):
    def test_runner_combines_and_deduplicates_adapter_records(self):
        duplicate_a = normalize_narrative_record(
            {"source": "manual", "source_id": "same", "text": "BTCUSDT first"}
        )
        duplicate_b = normalize_narrative_record(
            {"source": "manual", "source_id": "same", "text": "BTCUSDT second"}
        )
        other = normalize_narrative_record({"source": "rss:test", "source_id": "rss-1", "text": "ETHUSDT"})

        runner = NarrativeCollectionRunner([FakeCollector([duplicate_a]), FakeCollector([duplicate_b, other])])

        self.assertEqual(runner.collect(), [duplicate_a, other])

    def test_jsonl_writer_writes_one_record_per_line(self):
        record = normalize_narrative_record({"source": "manual", "source_id": "1", "text": "BTCUSDT"})
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested" / "narrative.jsonl"
            written = write_jsonl_records(output, [record])
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(written, 1)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["symbol_mentions"], ["BTCUSDT"])

    def test_collect_to_jsonl_returns_records_and_written_count(self):
        record = normalize_narrative_record({"source": "manual", "source_id": "1", "text": "BTCUSDT"})
        runner = NarrativeCollectionRunner([FakeCollector([record])])
        with tempfile.TemporaryDirectory() as tmp:
            records, written = runner.collect_to_jsonl(str(Path(tmp) / "narrative.jsonl"))

        self.assertEqual(records, [record])
        self.assertEqual(written, 1)


if __name__ == "__main__":
    unittest.main()

