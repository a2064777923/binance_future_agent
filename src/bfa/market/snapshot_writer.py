"""Local JSONL writer for normalized market snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from bfa.market.models import NormalizedMarketSnapshot


def write_jsonl_snapshots(path: str | Path, snapshots: Iterable[NormalizedMarketSnapshot]) -> int:
    records = [snapshot.to_dict() for snapshot in snapshots]
    if not records:
        return 0

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return len(records)
