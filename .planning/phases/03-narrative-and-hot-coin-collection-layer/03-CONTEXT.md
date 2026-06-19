# Phase 3: Narrative And Hot-Coin Collection Layer - Context

**Gathered:** 2026-06-19T12:10:00Z
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 builds the narrative and hot-coin collection layer. It must ingest
Binance Square-style hot-coin signals and fallback narrative sources behind
replaceable collector adapters, normalize narrative records into a stable shape,
and deduplicate repeated posts or repeated symbol mentions before later scoring.

This phase is narrative-data only. It must not implement candidate scoring,
OpenAI trade decisions, Binance account/order APIs, live execution, durable
SQLite event storage, server deployment, or strategy promotion.

</domain>

<decisions>
## Implementation Decisions

### Source Priority And Access Modes
- **D-01:** Treat Binance Square as the primary narrative source because the
  user explicitly wants the hot-coin strategy inspired by Square posts and the
  screenshot shows the "马拉龙巴子" style of public Square trading logs.
- **D-02:** Do not assume a stable official public Square read API exists.
  Implement Square behind a replaceable adapter with supported modes:
  `manual`, `export_dir`, and optionally `browser_snapshot` / `http_snapshot`
  only if research finds an allowed and testable path.
- **D-03:** Manual/export ingestion is a first-class fallback, not a temporary
  hack. Users must be able to drop copied/exported Square or social records
  into a gitignored runtime/export path and get normalized narrative records.
- **D-04:** Add RSS/news ingestion early because it is low-secret and useful as
  a fallback narrative source. X and Telegram should be represented through
  adapter interfaces/config, but token-based live calls should be deferred until
  credentials and allowed access are explicitly available.

### Strategy Reference From User Screenshot
- **D-05:** The screenshot reference should guide signal design, not be treated
  as a reproducible private strategy. The visible pattern is: public poster
  claims an AI/agent bot watches hot coins, reacts to high-momentum tickers such
  as `ESPORTSUSDT`, runs on local/VPS automation, iterates prompts/settings, and
  uses small-capital futures compounding stories. Phase 3 should collect the
  evidence needed for this style: symbol mentions, engagement, author/source,
  text, screenshots/export metadata, timestamps, and confidence/data-quality
  notes.
- **D-06:** Do not hardcode or overfit to one public poster. The collector
  should support source/author fields so later strategy code can compare
  performance by source, but Phase 3 should not bless any author as reliable.

### Normalized Narrative Shape
- **D-07:** Normalize all narrative records into a typed model/dict with:
  `source`, `source_id`, `author`, `symbol_mentions`, `text`, `url`,
  `published_at`, `collected_at`, `engagement`, `raw`, and `quality_flags`.
- **D-08:** Symbol extraction should be conservative and futures-aware:
  uppercase explicit mentions such as `BTCUSDT`, `$BTC`, `BTC`, and Chinese text
  around coin symbols, then map to configured/known symbols where possible.
  Ambiguous symbols must be flagged, not silently traded.
- **D-09:** Engagement data should be optional and normalized as a dictionary
  such as likes/comments/shares/views when available. Missing engagement should
  not block ingestion.

### Deduplication And Storage Boundary
- **D-10:** Deduplicate by stable source ID when present; otherwise use a
  deterministic fingerprint over normalized source, author, text, URL, symbols,
  and a coarse timestamp bucket.
- **D-11:** Deduplication should collapse repeated records and repeated symbol
  mentions inside a record while preserving enough raw/context fields for audit.
- **D-12:** Phase 3 may write narrative JSONL under gitignored `data/`,
  `runtime/`, or `raw_exports/` paths for smoke tests. Durable SQLite event
  storage and replay belong to Phase 4.

### Safety, Secrets, And Boundaries
- **D-13:** Unit tests must use static fixtures only. No live Binance Square,
  X, Telegram, RSS, or news network calls in unit tests.
- **D-14:** Cookie/token paths such as `SQUARE_COOKIE_FILE`, `X_BEARER_TOKEN`,
  and `TELEGRAM_BOT_TOKEN` remain config placeholders only. Do not read real
  secret files during planning/tests and never commit secret values.
- **D-15:** Phase 3 source collectors must not call OpenAI, Binance private
  APIs, order endpoints, or server deployment commands. They produce narrative
  records for later phases.

### the agent's Discretion
- Prefer dependency-free parsers first: JSON/JSONL/manual export parsing,
  simple RSS XML parsing with `xml.etree`, and adapter protocols. Add browser
  automation or third-party packages only if research and planning show clear
  value and tests remain offline.
- Choose exact module names, but keep the shape obvious: narrative models,
  symbol extraction, source adapters, deduplication, JSONL writer, and CLI smoke
  commands.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Artifacts
- `.planning/PROJECT.md` — project scope, hot-coin strategy intent, screenshot
  inspiration, source preference, and isolation constraints.
- `.planning/REQUIREMENTS.md` — Phase 3 requirements NAR-01 through NAR-04.
- `.planning/ROADMAP.md` — Phase 3 goal and success criteria.
- `.planning/phases/02-binance-futures-market-data-layer/02-VERIFICATION.md`
  — verified market-data layer available to later candidate ranking.
- `.env.example` — existing narrative/source config placeholders:
  `SQUARE_COLLECTOR_MODE`, `SQUARE_COOKIE_FILE`, `SQUARE_EXPORT_DIR`,
  `RSS_FEED_URLS`, `X_BEARER_TOKEN`, `TELEGRAM_BOT_TOKEN`, and
  `TELEGRAM_CHANNELS`.

### User-Provided Reference
- `F:\xwechat_files\wxid_n2xnx95xrk3e22_1d05\temp\RWTemp\2026-06\eac9cd913cec07f5a967dcec9c02c992.jpg`
  — screenshot of a public Binance Square post/comment thread by "马拉龙巴子"
  describing an AI/agent bot that trades hot futures coins, references
  `ESPORTSUSDT`, local/VPS automation, and iterative prompt/settings tuning.
  Use as qualitative inspiration only; do not quote private credentials or
  assume a complete strategy.

### External Research Targets
- Binance Square official/product documentation — determine whether any
  supported read/export route exists for public Square content.
- Binance Square web UI / export behavior — if no official read API exists,
  design manual/export ingestion first and keep browser/http adapters
  replaceable.
- RSS/news source formats — standard RSS/Atom feeds for fallback narrative
  ingestion.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bfa/config.py`: already has narrative source config placeholders and
  `AppConfig.get_list` for comma-separated lists.
- `src/bfa/redaction.py`: should redact source tokens/cookies in any future
  CLI diagnostics.
- `src/bfa/cli.py`: thin argparse structure can add `narrative` smoke commands
  with injected collector factories for tests.
- `src/bfa/market/models.py`: `NormalizedMarketSnapshot` provides a good model
  pattern for a future `NormalizedNarrativeRecord`.
- `src/bfa/market/snapshot_writer.py`: JSONL writer pattern can be mirrored or
  generalized for narrative records.

### Established Patterns
- Standard-library-first Python modules under `src/bfa`.
- Tests use `unittest`, static fixtures, fake transports/collectors, and no live
  network calls.
- Runtime data and exports are gitignored: `data/`, `runtime/`, `raw_exports/`,
  and `*.jsonl`.
- CLI commands print JSON and are testable via injected factories.

### Integration Points
- Phase 3 should add a new `src/bfa/narrative/` package rather than mixing
  narrative source logic into `src/bfa/market/`.
- Config helpers should parse `RSS_FEED_URLS` and `TELEGRAM_CHANNELS` with the
  same comma-separated pattern used by `BFA_MARKET_SYMBOLS`.
- Later Phase 5 candidate ranking will combine normalized narrative records
  with Phase 2 market snapshots, so narrative records must preserve source,
  time, symbols, and quality flags.

</code_context>

<specifics>
## Specific Ideas

- Prioritize a "hot coin evidence packet" mindset: collect posts/records that
  explain why a symbol is being mentioned, who mentioned it, how much engagement
  it received, and when it appeared.
- Support the user's desire for many data sources, but keep the first phase
  controlled: Square/manual/export + RSS/news first; X/Telegram adapters can be
  interface/config-first until tokens and access are explicit.
- The screenshot's bot narrative reinforces the need for auditability: every
  later trade idea should be traceable back to raw narrative evidence, not just
  a symbol string.

</specifics>

<deferred>
## Deferred Ideas

- Narrative heat scoring, source reliability weighting, and candidate ranking
  belong to Phase 5.
- OpenAI prompt generation and AI trade decisions belong to Phase 6.
- SQLite durable storage and replay belong to Phase 4.
- Live/private API reads, order placement, and account state belong to Phase 7.
- Server scheduling/deployment belongs to Phase 8.
- Browser automation for Binance Square should be planned only if official or
  manual/export ingestion is insufficient and the access path is allowed.

</deferred>

---
*Phase: 3-Narrative And Hot-Coin Collection Layer*
*Context gathered: 2026-06-19T12:10:00Z*
