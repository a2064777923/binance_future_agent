# Phase 3 Research: Narrative And Hot-Coin Collection Layer

**Researched:** 2026-06-19
**Status:** Ready for planning

## Executive Summary

Phase 3 should build a source-adapter layer around normalized narrative records,
not a fragile one-off scraper. Binance Square remains the primary strategy
inspiration, but current public evidence supports a conservative conclusion:
Binance exposes public/product surfaces and a Skill/OpenAPI-style posting path,
yet there is no stable, official, documented public read API for collecting
Square feed posts in the Binance USD-M futures developer docs. Therefore the
first reliable Square ingestion path should be manual/export ingestion, backed
by the same normalized record model that later browser or HTTP snapshot
adapters can feed.

The best low-risk Phase 3 slice is:

1. Define narrative contracts and conservative futures-aware symbol extraction.
2. Implement manual/export ingestion for Square and copied social/news records.
3. Implement RSS/Atom ingestion with injectable transports and static fixtures.
4. Add deterministic deduplication and JSONL output.
5. Wire CLI smoke commands with fake/offline tests only.

This satisfies NAR-01 through NAR-04 without cookies, private APIs, OpenAI,
SQLite, execution, or server deployment.

## Source Access Research

### Binance Square

Findings:

- Binance Square is a public product/content surface for creator and community
  posts, but the Binance USD-M futures API docs are exchange/data/order docs and
  do not document a supported public Square read endpoint.
- Public Binance examples around "square post" are oriented toward creating or
  publishing content through a Skill/OpenAPI-style integration, not harvesting a
  feed for trading signals.
- Treating undocumented web endpoints as a core dependency would make the
  trading system brittle and may create access-policy risk.

Implementation implication:

- `source="binance_square"` should exist from Phase 3.
- `manual` and `export_dir` are the supported baseline modes.
- `browser_snapshot` or `http_snapshot` may be added later behind the same
  adapter interface only when access is explicit, testable, and allowed.
- Cookie paths such as `SQUARE_COOKIE_FILE` remain config placeholders and must
  not be read in Phase 3 tests.

### Manual And Export Records

Manual/export ingestion is not a temporary workaround; it is the control plane
for uncertain sources. It should accept JSON, JSONL, and simple text exports so
the user can copy Square posts, Telegram snippets, X posts, or news notes into a
gitignored runtime directory.

Recommended accepted fields:

- `source`
- `source_id`
- `author`
- `text`
- `url`
- `published_at`
- `collected_at`
- `engagement`
- `raw`

If fields are missing, the normalizer should keep the record but add
`quality_flags` such as `missing_source_id`, `missing_published_at`,
`missing_author`, or `no_symbol_mentions`.

### RSS And Atom

RSS 2.0 and Atom are stable XML formats and fit Phase 3 well because they can be
tested offline with static fixtures. They are useful fallback narrative sources
for crypto news, exchange announcements, and market headlines.

Implementation implication:

- Use Python standard library XML parsing first.
- Parse RSS items from `channel/item` and Atom entries from `feed/entry`.
- Normalize ID from `guid`, `id`, or `link`; title/description/summary/content
  into text; `pubDate`, `published`, or `updated` into `published_at`.
- Network calls should be behind an injectable transport. Unit tests should use
  fixture XML strings and no live feeds.

### X And Telegram

Both can be valuable later, but live ingestion requires tokens, channel access,
and rate-limit handling. Phase 3 should not block on them.

Implementation implication:

- Keep config placeholders and adapter naming in mind.
- Do not call X or Telegram APIs in Phase 3.
- Manual/export records should be source-agnostic so X/Telegram exports can be
  normalized immediately when copied into the export directory.

## Normalized Record Design

Use a typed standard-library dataclass matching the Phase 3 context:

```python
NormalizedNarrativeRecord(
    source: str,
    source_id: str | None,
    author: str | None,
    symbol_mentions: list[str],
    text: str,
    url: str | None,
    published_at: str | None,
    collected_at: str,
    engagement: dict[str, str | int | float],
    raw: dict[str, object],
    quality_flags: list[str],
)
```

Keep all values JSON-serializable through `to_dict()`.

## Symbol Extraction Research

The extractor must be conservative because Phase 7 may eventually execute real
futures trades. It should identify explicit crypto/futures mentions but flag
ambiguity rather than inventing tradable contracts.

Recommended Phase 3 behavior:

- Recognize explicit futures pairs like `BTCUSDT`, `ESPORTSUSDT`.
- Recognize cashtags like `$BTC` and map to `BTCUSDT` when the quote suffix is
  configured as `USDT`.
- Recognize slash/dash pairs like `BTC/USDT` or `BTC-USDT`.
- Optionally map bare uppercase tokens such as `BTC` to `BTCUSDT` only when the
  token appears in an allowlist derived from configured market symbols or caller
  input.
- Deduplicate symbol mentions per record while preserving order.
- Add quality flags for `no_symbol_mentions` and `ambiguous_symbol_mentions`.

Avoid:

- Free-form fuzzy matching.
- Treating every uppercase word as a coin.
- Adding leverage, side, or trade intent in Phase 3.

## Deduplication Research

Deduplication should be deterministic and explainable.

Recommended keys:

1. If `(source, source_id)` exists, use it.
2. Otherwise build a fingerprint from normalized source, author, URL, normalized
   text, symbols, and a coarse date/time bucket.

Collision behavior:

- Preserve the first record.
- Merge repeated symbol mentions by order-preserving set semantics.
- Add a quality flag such as `duplicate_collapsed` only if useful for audit.
- Do not perform semantic clustering or model-based duplicate detection in
  Phase 3.

## Storage Boundary

Phase 3 can write JSONL narrative records to caller-provided paths under
gitignored runtime/data/export directories. Durable SQLite tables and replay
queries belong to Phase 4.

The existing market snapshot JSONL writer pattern is sufficient to mirror:

- Parent directory creation.
- One JSON object per line.
- UTF-8 encoding.
- Append mode only if explicitly supported.

## Test Strategy

Unit tests should be fully offline:

- Manual/export JSON and JSONL fixtures.
- RSS and Atom XML fixtures.
- Deduplication fixtures with source ID and fingerprint duplicates.
- CLI tests using temporary directories and injected collectors.
- Boundary greps for OpenAI, Binance private endpoints, account/order code,
  cookie/token reads, SQLite, deployment, and `F:\stock`.

## Recommended Plan Breakdown

1. Narrative contracts and symbol extraction.
2. Manual/export and RSS/Atom source adapters.
3. Deduplication, JSONL writer, and CLI smoke commands.

This is enough for Phase 3 success criteria while keeping later scoring, AI,
event store, execution, and deployment out of scope.

## References Used

- Binance USD-M futures developer documentation provided by the user:
  `https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`
- Binance Square public/product and Skill/OpenAPI posting material discovered
  during research; treated as evidence for content/product existence, not as a
  supported public read API.
- RSS 2.0 and Atom/RFC 4287 format conventions for feed parsing.
- Python standard-library XML and JSON tooling for dependency-free ingestion.

