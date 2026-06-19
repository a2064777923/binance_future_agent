"""Narrative source ingestion and normalization."""

from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.dedup import deduplicate_records
from bfa.narrative.models import NormalizedNarrativeRecord, normalize_narrative_record
from bfa.narrative.symbols import SymbolExtractionResult, extract_symbol_mentions

__all__ = [
    "NarrativeCollectionRunner",
    "NormalizedNarrativeRecord",
    "SymbolExtractionResult",
    "deduplicate_records",
    "extract_symbol_mentions",
    "normalize_narrative_record",
]
