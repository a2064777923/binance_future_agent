"""Deterministic narrative record deduplication."""

from __future__ import annotations

import hashlib

from bfa.narrative.models import NormalizedNarrativeRecord


def dedup_key(record: NormalizedNarrativeRecord) -> str:
    if record.source_id:
        return f"id:{record.source}:{record.source_id}"
    fingerprint = "|".join(
        [
            record.source,
            record.author or "",
            record.url or "",
            _normalize_text(record.text),
            ",".join(record.symbol_mentions),
            _time_bucket(record.published_at or record.collected_at),
        ]
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"fp:{digest}"


def deduplicate_records(records: list[NormalizedNarrativeRecord]) -> list[NormalizedNarrativeRecord]:
    deduped: list[NormalizedNarrativeRecord] = []
    seen: set[str] = set()
    for record in records:
        key = dedup_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _time_bucket(value: str | None) -> str:
    if not value:
        return ""
    return value[:13]

