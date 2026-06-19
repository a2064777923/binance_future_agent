"""Conservative crypto/futures symbol extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


PAIR_RE = re.compile(r"\b([A-Z0-9]{2,20})(?:[/\-]?)(USDT)\b")
CASHTAG_RE = re.compile(r"(?<![A-Z0-9])\$([A-Z][A-Z0-9]{1,19})\b")
UPPER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,19})\b")
DEFAULT_QUOTE_ASSETS = ("USDT",)
IGNORED_UPPER_TOKENS = {
    "AI",
    "API",
    "ATH",
    "BTCUSDT",  # explicit pair regex owns this.
    "ETF",
    "FOMO",
    "NFT",
    "OI",
    "PNL",
    "ROI",
    "USD",
    "USDT",
    "VPS",
}


@dataclass(frozen=True)
class SymbolExtractionResult:
    symbols: list[str]
    quality_flags: list[str]
    ambiguous_mentions: list[str]


def extract_symbol_mentions(
    text: str,
    *,
    known_symbols: Iterable[str] | None = None,
    quote_assets: Iterable[str] = DEFAULT_QUOTE_ASSETS,
) -> SymbolExtractionResult:
    """Extract explicit futures symbols while flagging ambiguous uppercase tokens."""

    known = {symbol.upper() for symbol in known_symbols or [] if symbol}
    quotes = tuple(quote.upper() for quote in quote_assets if quote)
    symbols: list[str] = []
    ambiguous: list[str] = []
    seen_tokens: set[str] = set()

    def add_symbol(symbol: str) -> None:
        normalized = symbol.upper()
        if normalized not in symbols:
            symbols.append(normalized)

    for match in PAIR_RE.finditer(text.upper()):
        base, quote = match.groups()
        if quote in quotes:
            add_symbol(f"{base}{quote}")

    for match in CASHTAG_RE.finditer(text.upper()):
        base = match.group(1)
        if base in IGNORED_UPPER_TOKENS:
            continue
        mapped = _map_base_to_symbol(base, known, quotes)
        if mapped:
            add_symbol(mapped)
        else:
            _add_once(ambiguous, base)

    for match in UPPER_TOKEN_RE.finditer(text.upper()):
        token = match.group(1)
        if token in seen_tokens:
            continue
        seen_tokens.add(token)
        if token in IGNORED_UPPER_TOKENS:
            continue
        if token in symbols:
            continue
        if any(token.endswith(quote) for quote in quotes):
            continue
        mapped = _map_base_to_symbol(token, known, quotes)
        if mapped:
            add_symbol(mapped)
        elif not known and _looks_like_coin_candidate(token):
            _add_once(ambiguous, token)

    flags: list[str] = []
    if not symbols:
        flags.append("no_symbol_mentions")
    if ambiguous:
        flags.append("ambiguous_symbol_mentions")

    return SymbolExtractionResult(
        symbols=symbols,
        quality_flags=flags,
        ambiguous_mentions=ambiguous,
    )


def _map_base_to_symbol(base: str, known_symbols: set[str], quote_assets: tuple[str, ...]) -> str | None:
    for quote in quote_assets:
        candidate = f"{base}{quote}"
        if candidate in known_symbols:
            return candidate
    return None


def _looks_like_coin_candidate(token: str) -> bool:
    return 2 <= len(token) <= 12 and token not in IGNORED_UPPER_TOKENS


def _add_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
