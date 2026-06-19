# Phase 2: Binance Futures Market Data Layer - Context

**Gathered:** 2026-06-19T10:35:51Z
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 builds the official Binance USD-M futures market data layer. It must
fetch exchange metadata and REST market metrics for selected symbols, define
live WebSocket market-stream handling, and produce normalized market snapshots
with source, symbol, and timestamp metadata.

This phase is market-data only. It must not implement Binance account/user data
streams, order placement, AI decisions, narrative ingestion, strategy ranking,
SQLite event-store persistence, or server deployment.

</domain>

<decisions>
## Implementation Decisions

### Binance API Surface
- **D-01:** Use only official Binance USD-M futures public market-data APIs in
  this phase. Base URLs come from the Phase 1 config contract:
  `BINANCE_FUTURES_BASE_URL` and `BINANCE_FUTURES_WS_BASE_URL`.
- **D-02:** Implement REST coverage for exchange metadata, klines, 24h ticker
  stats, funding-rate history, open interest, long/short ratios, and taker
  buy/sell volume. These map directly to MKT-01 and MKT-02.
- **D-03:** Treat WebSocket work as public market streams only: combined stream
  URL building, stream message parsing, reconnect/backoff hooks, and unit-testable
  handlers for ticker, kline, mark-price/book-ticker style market updates. Do
  not add private listen-key/user-data streams in Phase 2.

### Candidate Symbol Scope
- **D-04:** Phase 2 supports a configurable symbol allowlist for hot-coin
  candidates, defaulting to a small controlled set for tests and dry-run. It
  should not attempt broad-market scanning by default.
- **D-05:** Exchange metadata must expose symbol filters needed later for
  execution planning, especially status, contract type, quote asset,
  price/tick filters, quantity/step filters, and notional/min-notional style
  constraints when available.

### Normalization And Storage Boundary
- **D-06:** Normalize all collected market data into typed Python objects or
  dictionaries with `source`, `event_type`, `symbol`, `event_time`, and
  `received_at` fields plus source-specific payload data.
- **D-07:** Phase 2 may write JSONL snapshots under the gitignored `data/` or
  `runtime/` paths for smoke tests and local inspection, but durable SQLite event
  storage belongs to Phase 4.
- **D-08:** Network calls must be injectable/testable. Unit tests should use
  static fixtures or mocked HTTP/WebSocket transports, not live Binance calls.

### Error Handling And Rate Safety
- **D-09:** REST clients must preserve Binance response status, endpoint, params,
  and request-weight context in structured errors without leaking credentials.
  Public market-data calls should still avoid secrets entirely.
- **D-10:** Implement conservative request pacing hooks and timeout parameters,
  but do not build a full scheduler in this phase. The collector should make it
  hard to accidentally request all symbols across all heavy endpoints.

### the agent's Discretion
- Choose standard-library `urllib`/`json` or a small dependency-free transport
  abstraction for Phase 2 unless a later plan justifies a package. Phase 1 added
  no external dependencies, so dependency additions need explicit value.
- Choose exact internal module names, but keep the shape obvious: REST client,
  WebSocket stream utilities, normalization models, collector orchestration, and
  tests/fixtures.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Artifacts
- `.planning/PROJECT.md` — project scope, 100 USDT live-pilot context, isolation
  and safety constraints.
- `.planning/REQUIREMENTS.md` — Phase 2 requirements MKT-01 through MKT-04.
- `.planning/ROADMAP.md` — Phase 2 goal and success criteria.
- `.planning/phases/01-isolated-project-foundation/01-VERIFICATION.md` — verified
  foundation capabilities and config/secret boundaries.
- `.env.example` — Binance REST/WS base URL names and safe defaults.

### Official Binance USD-M Futures Docs
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`
  — general API rules, base endpoint, timing, limits, and error framing.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information`
  — exchange metadata and symbol filters for MKT-01.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics`
  — 24h ticker metrics for candidate market snapshots.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data`
  — kline/candlestick history for price and volatility features.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History`
  — funding-rate history for derivatives context.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest`
  — current open interest endpoint.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics`
  — historical open-interest statistics for anomaly features.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Top-Trader-Long-Short-Ratio`
  — top-trader long/short ratio endpoint.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Taker-BuySell-Volume`
  — taker buy/sell volume endpoint.
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams`
  — public market WebSocket stream naming and stream behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bfa/config.py`: load Binance REST/WS base URLs from the known config
  contract without exposing unrelated environment keys.
- `src/bfa/redaction.py`: redact structured diagnostics before future CLI or
  collector output.
- `src/bfa/cli.py`: thin argparse pattern for adding market-data commands later.

### Established Patterns
- Standard-library-first Python package under `src/bfa`.
- Unit tests use `unittest` and synthetic fixtures.
- Runtime paths such as `data/`, `runtime/`, and `logs/` are gitignored.
- Diagnostics should be JSON-like and redacted before display.

### Integration Points
- Phase 2 modules should import config through `load_config` / `validate_config`
  only when runtime config is needed.
- CLI additions should remain thin wrappers around testable modules.
- Any local snapshot writer must target gitignored runtime/data paths.

</code_context>

<specifics>
## Specific Ideas

The user wants "hot coins" first and prefers many useful data sources later, but
Phase 2 is the official Binance market-data layer only. Build it so Phase 3
narrative collectors and Phase 5 candidate ranking can request market features
for a small symbol set without needing live trading credentials.

</specifics>

<deferred>
## Deferred Ideas

- Binance Square, RSS/news, X, Telegram, and other narrative sources belong to
  Phase 3.
- Durable SQLite event storage and replay belong to Phase 4.
- Candidate scoring/ranking belongs to Phase 5.
- OpenAI decisioning belongs to Phase 6.
- Live/testnet order placement and account reconciliation belong to Phase 7.
- Server deployment belongs to Phase 8.

</deferred>

---
*Phase: 2-Binance Futures Market Data Layer*
*Context gathered: 2026-06-19T10:35:51Z*
