"""Composite narrative collection runner."""

from __future__ import annotations

from bfa.narrative.adapters import NarrativeCollector
from bfa.narrative.dedup import deduplicate_records
from bfa.narrative.jsonl_writer import write_jsonl_records
from bfa.narrative.models import NormalizedNarrativeRecord


class NarrativeCollectionRunner:
    def __init__(self, collectors: list[NarrativeCollector]) -> None:
        self.collectors = collectors

    def collect(self) -> list[NormalizedNarrativeRecord]:
        records: list[NormalizedNarrativeRecord] = []
        for collector in self.collectors:
            records.extend(collector.collect())
        return deduplicate_records(records)

    def collect_to_jsonl(self, output: str, *, append: bool = False) -> tuple[list[NormalizedNarrativeRecord], int]:
        records = self.collect()
        written = write_jsonl_records(output, records, append=append)
        return records, written

