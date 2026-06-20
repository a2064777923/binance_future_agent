# Milestones

## v1.22 Portfolio Risk And Multi-Position (Shipped: 2026-06-20)

**Phases completed:** 18 phases, 18 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.22-ROADMAP.md`
- `.planning/milestones/v1.22-REQUIREMENTS.md`
- `.planning/milestones/v1.22-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Added portfolio-level margin, margin-fraction, total-notional, and
  same-direction exposure caps for controlled multi-position profiles.

- Added active-position review plus confirmation-gated adjustment planning so
  open positions are reviewed before new entries are scanned.

- Moved side, entry, stop, target, notional, hold time, and traceability into a
  deterministic multi-factor setup layer with AI as overlay/veto only.

- Added setup-driven backtesting, strategy promotion gates, calibrated variants,
  and interval-aware forward-paper gates.

- Deployed paper-only forward evidence collection with performance checks, loss
  attribution, guarded calibration, and adaptive paper guards.

- Added live auto-hot dry-run proof while keeping unattended live auto-hot and
  live service/timer disabled.

**Known deferred items at close:**

- Live automation remains inactive until all-interval strategy promotion and
  forward-paper performance evidence improve.

- `30u_10x_multi_dynamic` remains preview/confirmation-gated and was not
  applied.

- The adaptive paper guard reduces repeated losing samples but does not prove
  profitability.

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
