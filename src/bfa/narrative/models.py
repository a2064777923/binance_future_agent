"""Narrative data models and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from bfa.narrative.symbols import extract_symbol_mentions


@dataclass(frozen=True)
class NormalizedNarrativeRecord:
    source: str
    source_id: str | None
    author: str | None
    symbol_mentions: list[str]
    text: str
    url: str | None
    published_at: str | None
    collected_at: str
    engagement: dict[str, int | float | str]
    raw: dict[str, Any]
    quality_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "author": self.author,
            "symbol_mentions": list(self.symbol_mentions),
            "text": self.text,
            "url": self.url,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "engagement": dict(self.engagement),
            "raw": dict(self.raw),
            "quality_flags": list(self.quality_flags),
        }


def normalize_narrative_record(
    raw: Mapping[str, Any],
    *,
    default_source: str | None = None,
    known_symbols: Iterable[str] | None = None,
    collected_at: str | None = None,
) -> NormalizedNarrativeRecord:
    source = _clean_optional(raw.get("source")) or _clean_optional(default_source)
    if not source:
        raise ValueError("narrative record source is required")

    text = _first_text(raw)
    if not text:
        raise ValueError("narrative record text is required")

    source_id = _clean_optional(raw.get("source_id") or raw.get("id") or raw.get("guid"))
    author = _clean_optional(raw.get("author") or raw.get("creator") or raw.get("user"))
    url = _clean_optional(raw.get("url") or raw.get("link"))
    published_at = _clean_optional(raw.get("published_at") or raw.get("published") or raw.get("pubDate"))
    collected = _clean_optional(collected_at) or _clean_optional(raw.get("collected_at")) or _now_iso()

    extraction = extract_symbol_mentions(text, known_symbols=known_symbols)
    raw_symbols = raw.get("symbol_mentions") or raw.get("symbols")
    symbols = _dedupe_strings([*_coerce_symbol_list(raw_symbols), *extraction.symbols])
    engagement = _coerce_engagement(raw.get("engagement"))
    quality_flags = _dedupe_strings(
        [
            *_coerce_string_list(raw.get("quality_flags")),
            *extraction.quality_flags,
            *([] if source_id else ["missing_source_id"]),
            *([] if author else ["missing_author"]),
            *([] if published_at else ["missing_published_at"]),
        ]
    )

    return NormalizedNarrativeRecord(
        source=source,
        source_id=source_id,
        author=author,
        symbol_mentions=symbols,
        text=text,
        url=url,
        published_at=published_at,
        collected_at=collected,
        engagement=engagement,
        raw=dict(raw),
        quality_flags=quality_flags,
    )


def _first_text(raw: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text", "content", "summary", "description", "title"):
        value = _clean_optional(raw.get(key))
        if value:
            parts.append(value)
    return "\n".join(_dedupe_strings(parts)).strip()


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _coerce_symbol_list(value: Any) -> list[str]:
    return [symbol.upper() for symbol in _coerce_string_list(value)]


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    elif isinstance(value, Iterable):
        values = [str(part).strip() for part in value]
    else:
        values = [str(value).strip()]
    return [value for value in values if value]


def _coerce_engagement(value: Any) -> dict[str, int | float | str]:
    if not isinstance(value, Mapping):
        return {}
    engagement: dict[str, int | float | str] = {}
    for key, raw_value in value.items():
        if raw_value is None:
            continue
        if isinstance(raw_value, bool):
            engagement[str(key)] = str(raw_value).lower()
        elif isinstance(raw_value, (int, float, str)):
            engagement[str(key)] = raw_value
        else:
            engagement[str(key)] = str(raw_value)
    return engagement


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

