"""JSONL writer for normalized narrative records."""

from __future__ import annotations

import json
from pathlib import Path

from bfa.narrative.models import NormalizedNarrativeRecord


def write_jsonl_records(
    path: str | Path,
    records: list[NormalizedNarrativeRecord],
    *,
    append: bool = False,
) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    return len(records)

