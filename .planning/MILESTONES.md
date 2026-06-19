# Milestones

## v1.0 Dry-Run Binance Futures Agent (Shipped: 2026-06-19)

**Phases completed:** 8 phases, 28 plans

**Archived artifacts:**

- `.planning/milestones/v1.0-ROADMAP.md`
- `.planning/milestones/v1.0-REQUIREMENTS.md`
- `.planning/milestones/v1.0-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Created an isolated Python project at `F:\binance_futures_agent` without
  coupling to the existing stock repository.
- Built Binance USD-M public market-data collectors, symbol filters, and
  normalized snapshot persistence.
- Added manual/export and RSS-style narrative ingestion for hot-coin signals.
- Implemented a SQLite event store, deterministic replay packets, and review
  metrics foundations.
- Added hot-coin candidate scoring, OpenAI structured decision validation, and
  secret-safe AI journaling.
- Built risk-gated dry-run/live execution helpers, server deployment assets, and
  isolated health checks under `/opt/binance-futures-agent`.

**Known deferred items at close:**

- Server OpenAI live health remains skipped until `OPENAI_API_KEY` is configured
  out of band.
- Live automated trading activation is tracked in v1.1 and remains disabled
  until the operator approves one-cycle live validation.

---

