"""RSS and Atom narrative ingestion."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from urllib.parse import urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from bfa.narrative.models import NormalizedNarrativeRecord, normalize_narrative_record


Fetcher = Callable[[str], str]
ATOM_NS = "{http://www.w3.org/2005/Atom}"


class RssFeedCollector:
    def __init__(
        self,
        urls: Iterable[str],
        *,
        fetcher: Fetcher | None = None,
        known_symbols: Iterable[str] | None = None,
        collected_at: str | None = None,
    ) -> None:
        self.urls = [url.strip() for url in urls if url and url.strip()]
        self.fetcher = fetcher or _default_fetcher
        self.known_symbols = list(known_symbols or [])
        self.collected_at = collected_at

    def collect(self) -> list[NormalizedNarrativeRecord]:
        records: list[NormalizedNarrativeRecord] = []
        for url in self.urls:
            records.extend(parse_feed(self.fetcher(url), source=_source_from_url(url), known_symbols=self.known_symbols, collected_at=self.collected_at))
        return records


def parse_feed(
    xml_text: str,
    *,
    source: str,
    known_symbols: Iterable[str] | None = None,
    collected_at: str | None = None,
) -> list[NormalizedNarrativeRecord]:
    root = ET.fromstring(xml_text)
    if _strip_namespace(root.tag) == "rss":
        return _parse_rss(root, source=source, known_symbols=known_symbols, collected_at=collected_at)
    if _strip_namespace(root.tag) == "feed":
        return _parse_atom(root, source=source, known_symbols=known_symbols, collected_at=collected_at)
    raise ValueError("unsupported feed root")


def _parse_rss(root: ET.Element, *, source: str, known_symbols: Iterable[str] | None, collected_at: str | None) -> list[NormalizedNarrativeRecord]:
    records: list[NormalizedNarrativeRecord] = []
    for item in root.findall("./channel/item"):
        payload = {
            "source": source,
            "source_id": _text(item, "guid") or _text(item, "link"),
            "author": _text(item, "author") or _text(item, "source"),
            "title": _text(item, "title"),
            "description": _text(item, "description"),
            "url": _text(item, "link"),
            "published_at": _text(item, "pubDate"),
            "raw": _children_dict(item),
        }
        records.append(normalize_narrative_record(payload, default_source=source, known_symbols=known_symbols, collected_at=collected_at))
    return records


def _parse_atom(root: ET.Element, *, source: str, known_symbols: Iterable[str] | None, collected_at: str | None) -> list[NormalizedNarrativeRecord]:
    records: list[NormalizedNarrativeRecord] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        payload = {
            "source": source,
            "source_id": _atom_text(entry, "id") or _atom_link(entry),
            "author": _atom_author(entry),
            "title": _atom_text(entry, "title"),
            "summary": _atom_text(entry, "summary") or _atom_text(entry, "content"),
            "url": _atom_link(entry),
            "published_at": _atom_text(entry, "published") or _atom_text(entry, "updated"),
            "raw": _children_dict(entry),
        }
        records.append(normalize_narrative_record(payload, default_source=source, known_symbols=known_symbols, collected_at=collected_at))
    return records


def _default_fetcher(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def _source_from_url(url: str) -> str:
    host = urlparse(url).netloc or "feed"
    return f"rss:{host.lower()}"


def _text(parent: ET.Element, tag: str) -> str | None:
    child = parent.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _atom_text(parent: ET.Element, tag: str) -> str | None:
    child = parent.find(f"{ATOM_NS}{tag}")
    return child.text.strip() if child is not None and child.text else None


def _atom_link(parent: ET.Element) -> str | None:
    link = parent.find(f"{ATOM_NS}link")
    if link is None:
        return None
    return (link.attrib.get("href") or "").strip() or None


def _atom_author(parent: ET.Element) -> str | None:
    name = parent.find(f"{ATOM_NS}author/{ATOM_NS}name")
    return name.text.strip() if name is not None and name.text else None


def _children_dict(parent: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in list(parent):
        key = _strip_namespace(child.tag)
        if child.text and child.text.strip():
            values[key] = child.text.strip()
        elif child.attrib:
            values[key] = dict(child.attrib)  # type: ignore[assignment]
    return values


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

