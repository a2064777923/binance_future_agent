---
phase: 64-live-outcome-ledger-and-guard-feedback
plan: 01
subsystem: ops
tags: [binance, live-outcomes, ledger, reconciliation, guard-feedback]
requires:
  - phase: 63-live-cycle-position-stewardship
    provides: live lifecycle artifacts and manual-position boundaries
provides:
  - ops live-outcome-ledger command
  - live outcome attribution by symbol, side, setup, factor, exit, and hold bucket
  - recommendation-only guard feedback for weak live outcome groups
  - optional idempotent closed outcome reconciliation before ledger reporting
affects: [live-ops, outcome-learning, pilot-promotion, guard-feedback]
tech-stack:
  added: []
  patterns: [read-only ops report, idempotent event-store reconciliation, non-mutating guard feedback]
key-files:
  created:
    - src/bfa/ops/live_outcome_ledger.py
    - tests/test_ops_live_outcome_ledger.py
  modified:
    - src/bfa/cli.py
    - tests/test_cli.py
key-decisions:
  - "Ledger DB reads are default; signed Binance reads only happen when --reconcile is explicit."
  - "Guard feedback is recommendation-only and carries mutation proof instead of applying strategy/risk changes."
patterns-established:
  - "Live outcome attribution joins outcomes back to order_intents and trace artifacts through intent_event_id and ref_id patterns."
  - "Reconciliation persistence remains limited to idempotent fills/outcomes."
requirements-completed: [LEARN-01, LEARN-02, LEARN-03]
duration: 27 min
completed: 2026-06-21
status: complete
---

# Phase 64 Plan 01: Live Outcome Ledger And Guard Feedback Summary

**Live outcome ledger with optional idempotent reconciliation and recommendation-only guard feedback**

## Performance

- **Duration:** 27 min
- **Started:** 2026-06-20T22:28:53Z
- **Completed:** 2026-06-20T22:55:17Z
- **Tasks:** 7
- **Files modified:** 4 phase implementation/test files

## Accomplishments

- Added `ops live-outcome-ledger`, a compact live ledger that summarizes closed outcomes, open/unreconciled submitted intents, win/loss counts, PnL, profit factor, worst drawdown, and exit reason counts.
- Added attribution groups for symbols, sides, exit reasons, holding buckets, setup profiles, setup reasons, negative factor names, and factor reasons.
- Added recommendation-only guard feedback for negative live groups with explicit non-mutation proof.
- Added optional `--reconcile --persist-closed` support that reuses existing idempotent fill/outcome persistence.
- Deployed to `/opt/binance-futures-agent/app` with timers paused and restored after server verification.

## Task Commits

1. **Tasks 1-5: Ledger module, reconciliation, attribution, CLI, tests** - `2557bd1` (`feat(64-01): add live outcome ledger`)

**Plan metadata:** pending in closeout commit.

## Files Created/Modified

- `src/bfa/ops/live_outcome_ledger.py` - Builds the live outcome ledger, groups attribution, runs optional reconciliation, and emits mutation proof.
- `src/bfa/cli.py` - Adds `ops live-outcome-ledger` and flags for filtering/reconciliation.
- `tests/test_ops_live_outcome_ledger.py` - Covers aggregation, guard feedback, blocked reconcile inputs, and fake Binance reconciliation persistence.
- `tests/test_cli.py` - Covers CLI JSON shape, non-mutation proof, and fake signed-client reconciliation.

## Decisions Made

- Reconciliation is explicit. DB-only ledger reads do not require Binance credentials or a signed client.
- `--persist-closed` is blocked unless `--reconcile` is also present.
- Guard feedback never raises risk, edits env, changes systemd state, places orders, cancels orders, or applies strategy changes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- A separate operator-requested live capacity/manual-position hotfix was completed and committed first as `5c08574`; it was kept out of the Phase 64 implementation commit.

## Verification

- Local focused: `python -m unittest tests.test_ops_live_outcome_ledger tests.test_cli` -> 59 tests OK.
- Local full: `python -m unittest discover -s tests` -> 402 tests OK.
- Local lint: `git diff --check` -> no whitespace errors; CRLF warnings only.
- Server focused: `/opt/binance-futures-agent/.venv/bin/python -m unittest tests.test_ops_live_outcome_ledger tests.test_cli` -> 59 tests OK.
- Server full: `/opt/binance-futures-agent/.venv/bin/python -m unittest discover -s tests` -> 402 tests OK.
- Server read-only ledger smoke: `schema=bfa_live_outcome_ledger_v1`, `status=ledger_ready`, `outcome_count=4`, `places_orders=false`, `writes_env_files=false`.
- Server reconcile smoke: `status=ledger_ready`, `submitted_intents=5`, `closed=1`, `persisted_outcomes_inserted=1`, final `outcome_count=5`, `open_or_unreconciled_submitted_intents=0`, `total_net_pnl_usdt=0.21357602`, mutation proof still shows no orders/env/systemd/risk changes.
- Final server state: live timer active, paper timer active, live service inactive, paper service inactive.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 65 can now use live ledger output as current pilot learning evidence. The server has five reconciled closed live outcomes and recommendation-only guard feedback available without mutating live strategy or risk settings.

---
*Phase: 64-live-outcome-ledger-and-guard-feedback*
*Completed: 2026-06-21*
