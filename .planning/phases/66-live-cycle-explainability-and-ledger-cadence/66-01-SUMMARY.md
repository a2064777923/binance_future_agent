---
phase: 66-live-cycle-explainability-and-ledger-cadence
plan: 01
subsystem: ops
tags: [binance, live-cycle, explainability, live-outcomes, sizing]
requires:
  - phase: 63-live-cycle-position-stewardship
    provides: position lifecycle decision artifacts
  - phase: 64-live-outcome-ledger-and-guard-feedback
    provides: live outcome ledger and reconciliation cadence
  - phase: 65-server-canary-and-pilot-learning-packet
    provides: packet composition and mutation-proof patterns
provides:
  - read-only ops live-cycle-explainability command
  - recent submitted and no-order live cycle summaries
  - sizing/risk limiting-factor explanations
  - ledger cadence integration with explicit non-mutation proof
affects: [live-ops, explainability, learning-loop, operator-review]
tech-stack:
  added: []
  patterns: [event-store cycle reconstruction, read-only ops report composition, mutation proof]
key-files:
  created:
    - src/bfa/ops/live_cycle_explainability.py
    - tests/test_ops_live_cycle_explainability.py
  modified:
    - src/bfa/cli.py
    - tests/test_cli.py
    - README.md
key-decisions:
  - "Cycle reconstruction groups artifacts by symbol plus decided_at/ref ID and includes lifecycle-only/no-order cycles, not only submitted order intents."
  - "Ledger cadence reuses build_live_outcome_ledger_report so reconciliation guard behavior stays consistent with ops live-outcome-ledger."
  - "Mutation proof distinguishes exchange mutation, env/systemd/risk/guard mutation, and optional local closed-outcome persistence."
patterns-established:
  - "Operator explainability reports should include sizing_explanation.limiting_factors for small-position review."
  - "Manual symbols remain visible in lifecycle diagnostics while bot_managed=false."
requirements-completed: [OPS-03, LEARN-04]
duration: 20 min
completed: 2026-06-21
status: complete
---

# Phase 66 Plan 01: Live Cycle Explainability And Ledger Cadence Summary

**Read-only live-cycle explainability is implemented locally with ledger cadence integration and sizing-cap explanations.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-06-21T00:05:00Z
- **Completed:** 2026-06-21T00:25:00Z
- **Tasks:** 8
- **Files modified:** 7 implementation/test/docs/planning files

## Accomplishments

- Added `ops live-cycle-explainability`, a read-only report that reconstructs recent live cycles from local event-store artifacts.
- Included submitted cycles, AI/quant no-order cycles, rejected/risk-blocked cycles, missing-artifact evidence-quality notes, and lifecycle-only manual-symbol diagnostics.
- Added `sizing_explanation` with dynamic/fixed sizing output, configured caps, risk reasons, and limiting factors such as `stop_risk_cap`, `margin_fraction_cap`, `effective_notional_cap`, `below_min_executable_notional`, `risk_exceeds_cap`, and portfolio cap reasons.
- Reused `build_live_outcome_ledger_report()` for optional ledger cadence and reconciliation so `--reconcile --persist-closed` keeps the existing idempotent local fills/outcomes behavior.
- Added explicit mutation proof showing no order placement, cancelation, exchange mutation, env writes, systemd changes, risk raises, or guard applications.
- Documented command usage and how to interpret small-position sizing reasons in `README.md`.

## Task Commits

1. **Tasks 1-7: Explainability module, CLI, docs, tests, and local verification** - pending closeout commit.

## Files Created/Modified

- `src/bfa/ops/live_cycle_explainability.py` - Builds the read-only cycle report from lifecycle, candidate, setup, AI, order, exchange, outcome, and ledger evidence.
- `src/bfa/cli.py` - Adds `ops live-cycle-explainability` with `--env-file`, `--db`, `--since`, `--latest-cycles`, `--no-ledger`, `--reconcile`, and `--persist-closed`.
- `tests/test_ops_live_cycle_explainability.py` - Covers submitted, no-order, risk-blocked, missing-artifact, manual-symbol, sizing, ledger, and mutation-proof behavior.
- `tests/test_cli.py` - Covers CLI JSON shape and reconciliation flag plumbing through a fake signed client.
- `README.md` - Adds usage and sizing-reason interpretation guidance.

## Decisions Made

- The report remains local-DB read-only by default; a signed client is only constructed for `--reconcile`.
- `--persist-closed` is represented as optional local event-store persistence only, not exchange/env/systemd/risk mutation.
- No server deploy was performed in Phase 66; server canary/deployment remains planned for Phase 70.

## Deviations from Plan

None - plan executed as written with inline sequential GSD fallback because this Codex run did not have user-authorized subagent execution.

## Issues Encountered

- None blocking. `git diff --check` reported only expected Windows CRLF conversion warnings.

## Verification

- Focused local: `python -m unittest tests.test_ops_live_cycle_explainability tests.test_cli` -> 60 tests OK.
- Full local: `python -m unittest discover -s tests` -> 409 tests OK.
- Diff check: `git diff --check` -> no whitespace errors; CRLF warnings only.
- GSD audit: `node $HOME/.codex/gsd-core/bin/gsd-tools.cjs query audit-open --json` -> `has_open_items=false`, `total=0`.
- CLI empty-DB smoke: `python -m bfa.cli ops live-cycle-explainability --db runtime\phase66-smoke.sqlite --no-ledger --latest-cycles 1` -> `schema=bfa_live_cycle_explainability_v1`, `status=no_live_cycles`, mutation proof false.
- CLI fixture smoke: temporary DB with SOLUSDT rejected intent -> `status=explainability_ready`, `cycle_count=1`, `risk_reasons=["risk_exceeds_cap"]`, mutation proof false.

## User Setup Required

None. The command uses the existing event-store DB and existing Binance credentials only when `--reconcile` is explicitly requested.

## Next Phase Readiness

Phase 67 can now use this explainability surface before broadening hot-symbol breadth and guarded queue behavior.

---
*Phase: 66-live-cycle-explainability-and-ledger-cadence*
*Completed: 2026-06-21*
