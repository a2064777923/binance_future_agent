---
phase: 67-adaptive-hot-symbol-breadth-and-guarded-queue
plan: 01
subsystem: strategy-runner
tags: [live-runner, auto-hot, source-health, candidate-queue, paper-guard]

requires:
  - phase: 66-live-cycle-explainability-and-ledger-cadence
    provides: live-cycle explainability surface and evaluated-symbol diagnostics
provides:
  - 80-symbol live auto-hot default with manual-symbol exclusion before ranking
  - live source-health payloads for ticker, market, narrative, market-heat, and paper-guard sources
  - per-candidate setup, AI, execution, risk, and continuation diagnostics
  - retryable candidate queue continuation without relaxing global account risk gates
affects: [phase-68-edge, phase-69-sizing, phase-70-server-canary]

tech-stack:
  added: []
  patterns:
    - result-payload source-health summaries
    - per-candidate queue diagnostics
    - ranking-before-manual-exclusion guard

key-files:
  created:
    - .planning/phases/67-adaptive-hot-symbol-breadth-and-guarded-queue/67-01-SUMMARY.md
    - .planning/phases/67-adaptive-hot-symbol-breadth-and-guarded-queue/67-VERIFICATION.md
  modified:
    - src/bfa/agent.py
    - src/bfa/config.py
    - .env.example
    - deploy/server-env.example
    - README.md
    - tests/test_agent_runner.py
    - tests/test_config.py
    - tests/test_deploy_assets.py

key-decisions:
  - "Manual symbols are removed from auto-hot ticker rows before ranking so top-N capacity is not consumed by operator-owned exposure."
  - "Live source health is returned in AgentRunResult rather than persisted as a new table for this phase."
  - "Retryable queue expansion is limited to candidate-local AI/setup/filter/risk geometry; global account and portfolio blockers still stop the cycle."

patterns-established:
  - "AgentRunResult carries both compact source_health and candidate_evaluations for operator-facing explanation."
  - "Forward-paper guard diagnostics are summarized in source_health without raising risk, leverage, or concurrency."

requirements-completed: [SCAN-01, SCAN-02, SCAN-03, SCAN-04]

duration: 18 min
completed: 2026-06-21
status: complete
---

# Phase 67 Plan 01: Adaptive Hot-Symbol Breadth And Guarded Queue Summary

**Live runner now scans a configurable 80-symbol hot universe, reports source health, and explains each candidate queue step without relaxing manual-symbol or global risk boundaries.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-21T00:44:56Z
- **Completed:** 2026-06-21T01:02:04Z
- **Tasks:** 9/9
- **Files modified:** 10

## Accomplishments

- Raised the live auto-hot default from 40 to 80 symbols in config and deploy examples.
- Added live `source_health` covering Binance ticker selection, manual exclusions, market snapshots, narrative sources, market-heat fallback, and paper-guard state.
- Added `candidate_evaluations` so each evaluated symbol shows setup, AI, execution/risk outcome, continuation, and end reason.
- Kept `BTWUSDT` and other manual symbols out of auto-hot ranking, market collection inputs, candidate generation, AI, and execution.
- Expanded retryable queue handling for candidate-local filter/notional/risk geometry while preserving one-order-per-cycle and non-retryable global blockers.

## Task Commits

1. **Tasks 1-8: Live breadth, source health, candidate diagnostics, retryable queue behavior, docs, and tests** - `1fcf1f2` (`feat`)

**Plan metadata:** created by closeout commit.

## Files Created/Modified

- `src/bfa/agent.py` - Adds source-health helpers, candidate diagnostics, ranking-time manual exclusion, and retryable queue refinements.
- `src/bfa/config.py` - Raises `BFA_LIVE_AUTO_HOT_TOP_N` default to `80`.
- `.env.example` - Documents the new live auto-hot default.
- `deploy/server-env.example` - Documents the new deploy env default without mutating the server.
- `README.md` - Documents 80-symbol scanning, source-health output, candidate queue diagnostics, manual-symbol guard, and one-order-per-cycle behavior.
- `tests/test_agent_runner.py` - Adds coverage for 80-symbol scanning, source-health, AI-pass continuation, retryable risk continuation, non-retryable stop, and manual `BTWUSDT` exclusion.
- `tests/test_config.py` - Updates config default expectations.
- `tests/test_deploy_assets.py` - Updates deploy env default expectation.

## Decisions Made

- Manual symbols are excluded before hot ranking, not after, so configured top-N breadth is preserved for bot-eligible symbols.
- Source health stays in the live result payload for this phase; no new event-store table was added.
- `risk_exceeds_cap`, `notional_exceeds_cap`, missing/invalid candidate geometry, and exchange filter failures may continue to later candidates, but portfolio caps, position caps, missing credentials, kill switch, cooldown, and balance/global blockers remain non-retryable.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope creep; server env and systemd state were not changed by this phase.

## Issues Encountered

- A focused test showed AI `decision=pass` was initially recorded as generic AI accepted because the validation layer correctly accepts pass decisions. The candidate diagnostics now explicitly label that path as `ai_pass`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 68 can now build deeper multi-factor edge and point-precision logic on top of a broader scan surface and explicit per-candidate traces. Phase 70 still owns server canary deployment and manual-boundary proof.

---
*Phase: 67-adaptive-hot-symbol-breadth-and-guarded-queue*
*Completed: 2026-06-21*
