# Phase 67: Adaptive Hot-Symbol Breadth And Guarded Queue - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 67-Adaptive Hot-Symbol Breadth And Guarded Queue
**Areas discussed:** Hot-symbol breadth, Source health, Weak-evidence guard, Guarded candidate queue, Manual boundary

---

## Hot-Symbol Breadth

| Option | Description | Selected |
|--------|-------------|----------|
| Keep 40 symbols | Preserve current breadth and rely on future phases for expansion. | |
| Raise default to 80 symbols | Support at least 80 live auto-hot symbols with env override and current liquidity/change floors. | yes |
| Use unbounded exchange universe | Scan every USDT contract each live cycle. | |

**User's choice:** Auto-selected recommended default: raise support to at least 80 symbols.
**Notes:** This matches SCAN-01 while keeping filters and manual-symbol exclusions.

---

## Source Health

| Option | Description | Selected |
|--------|-------------|----------|
| Ticker-only health | Only report 24h ticker selection counts. | |
| Multi-source health | Report ticker, klines, open interest, funding, taker flow, narrative/manual/RSS availability. | yes |
| Full external social ingestion | Add new social adapters in this phase. | |

**User's choice:** Auto-selected recommended default: multi-source health.
**Notes:** New social adapters are not required for Phase 67; exposing available sources is enough.

---

## Weak-Evidence Guard

| Option | Description | Selected |
|--------|-------------|----------|
| Suppress weak evidence | Let recent weak paper/live groups block symbols, sides, or factor patterns. | yes |
| Report only | Show weak evidence without changing candidate behavior. | |
| Let AI decide | Pass weak evidence to AI and skip deterministic guard suppression. | |

**User's choice:** Auto-selected recommended default: suppress weak evidence.
**Notes:** Suppression must only reduce risk. It cannot raise leverage, size, or capacity.

---

## Guarded Candidate Queue

| Option | Description | Selected |
|--------|-------------|----------|
| Continue after retryable skips | Evaluate later candidates after setup pass, AI pass, duplicate exposure, filter/min-notional, or guard skips. | yes |
| Stop after first evaluated candidate | Preserve older one-candidate behavior. | |
| Allow multiple orders per cycle | Submit more than one live order per timer cycle. | |

**User's choice:** Auto-selected recommended default: continue after retryable skips.
**Notes:** The live cycle still submits at most one order by default.

---

## Manual Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Hard manual exclusion | Keep `BTWUSDT` and configured manual symbols visible but outside all bot actions. | yes |
| Diagnostics-only warning | Show manual symbols but allow scan/management to continue. | |
| Allow transfer to bot | Add a handoff path for manual positions. | |

**User's choice:** Auto-selected recommended default: hard manual exclusion.
**Notes:** The operator explicitly clarified `BTWUSDT` is manual.

---

## The agent's Discretion

- Implementation may introduce a small runner-local source-health helper.
- Tests should prioritize behavior over implementation shape.

## Deferred Ideas

- Phase 68: multi-factor point geometry.
- Phase 69: adaptive sizing and high-leverage governor.
- Phase 70: server canary and manual-boundary proof.
