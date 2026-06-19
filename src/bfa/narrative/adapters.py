"""Narrative collector interfaces."""

from __future__ import annotations

from typing import Protocol

from bfa.narrative.models import NormalizedNarrativeRecord


class NarrativeCollector(Protocol):
    def collect(self) -> list[NormalizedNarrativeRecord]:
        """Collect normalized narrative records."""

