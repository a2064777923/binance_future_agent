# Milestones

## v1.22 Portfolio Risk And Multi-Position (Active: 2026-06-20)

**Phases completed:** 2 phases, 2 plans; Phase 32 local implementation in progress

**Key accomplishments:**

- Added portfolio-level margin, margin fraction, notional, and same-direction
  notional caps.
- Let multi-position mode continue scanning when an existing position is open
  and capacity remains.
- Added top-N candidate queue evaluation so retryable first-candidate skips do
  not end the whole cycle.
- Added a confirmation-gated `30u_10x_multi_dynamic` profile for higher
  leverage and two concurrent positions.
- Allowed risk-profile readiness to carry protected active exposure into the
  target profile only when portfolio caps can absorb it.
- Extended exposure status with portfolio budget context.
- Added read-only active-position review and local active-position adjustment
  planning for partial take-profit/full-close actions.

**Known deferred items at close:**

- Active-position adjustment execution and any live env switch remain
  confirmation-token gated.

---

## v1.21 Live Pilot Risk Controls (Shipped: 2026-06-20)

**Phases completed:** 21 phases, 21 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.21-ROADMAP.md`
- `.planning/milestones/v1.21-REQUIREMENTS.md`
- `.planning/milestones/v1.21-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Activated and monitored the live small-capital Binance USD-M pilot with
  protective-order evidence and AI timeout/backoff behavior.
- Added short-window backtesting, tradability filtering, and a controlled
  hot-coin symbol universe for small notional caps.
- Hardened live execution around margin mode, hedge position side, entry-order
  failures, and account-balance preflight checks.
- Switched live AI decisions to DeepSeek while preserving strict JSON schema
  validation and deterministic risk gates.
- Reconciled closed live trade outcomes from Binance fills and added sweep
  tooling for submitted live intents.
- Added resume, hold-time, time-exit, risk-change, dynamic sizing, and
  confirmation-gated profile switch controls.

**Known deferred items at close:**

- HYPEUSDT remains open and protected; the 8x/dynamic profile apply must wait
  until the position closes, closed outcome evidence is persisted, and
  `risk-change-check --target-leverage 8` returns allowed.

---

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
