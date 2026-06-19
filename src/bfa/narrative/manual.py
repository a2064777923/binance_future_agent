"""Manual/export narrative ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from bfa.narrative.models import NormalizedNarrativeRecord, normalize_narrative_record


SUPPORTED_SUFFIXES = {".json", ".jsonl", ".txt"}


class ManualExportCollector:
    def __init__(
        self,
        export_dir: str | Path,
        *,
        default_source: str = "binance_square",
        known_symbols: Iterable[str] | None = None,
        collected_at: str | None = None,
        tolerant: bool = False,
    ) -> None:
        self.export_dir = Path(export_dir)
        self.default_source = default_source
        self.known_symbols = list(known_symbols or [])
        self.collected_at = collected_at
        self.tolerant = tolerant

    def collect(self) -> list[NormalizedNarrativeRecord]:
        if not self.export_dir.exists():
            return []
        if not self.export_dir.is_dir():
            raise ValueError(f"export path is not a directory: {self.export_dir}")

        records: list[NormalizedNarrativeRecord] = []
        for path in sorted(self.export_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                records.extend(self._read_file(path))
            except ValueError:
                if not self.tolerant:
                    raise
        return records

    def _read_file(self, path: Path) -> list[NormalizedNarrativeRecord]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else [payload]
            return [self._normalize(item, path) for item in items]
        if suffix == ".jsonl":
            records: list[NormalizedNarrativeRecord] = []
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_no}") from exc
                records.append(self._normalize(payload, path))
            return records
        if suffix == ".txt":
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return []
            return [
                normalize_narrative_record(
                    {"source": self.default_source, "text": text, "source_id": path.stem},
                    default_source=self.default_source,
                    known_symbols=self.known_symbols,
                    collected_at=self.collected_at,
                )
            ]
        raise ValueError(f"unsupported export file: {path}")

    def _normalize(self, item: object, path: Path) -> NormalizedNarrativeRecord:
        if not isinstance(item, dict):
            raise ValueError(f"manual export item must be an object in {path}")
        return normalize_narrative_record(
            item,
            default_source=self.default_source,
            known_symbols=self.known_symbols,
            collected_at=self.collected_at,
        )

