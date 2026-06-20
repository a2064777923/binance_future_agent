---
phase: 63
plan: 01
name: Live Cycle Position Stewardship
status: complete
completed: 2026-06-21
requirements_addressed:
  - POS-03
  - EXIT-02
---

# Phase 63 Summary

## Outcome

Phase 63 makes each live agent cycle persist active-position lifecycle decisions
before new-entry scanning, market snapshots, candidate generation, trade setup,
or AI calls.

The persisted event is a `risk_state` artifact with
`event_type=position_lifecycle_decision`. It records the position review,
adjustment-plan diagnostics, manual-symbol exclusions, and the dormant
auto-management gate state. `BTWUSDT` remains classified as manual and is not
managed by the agent.

## Behavior Added

- Live runs now persist `persisted.position_lifecycle` before entry-capacity
  short-circuiting or candidate scanning.
- `_position_adjustment_summary()` now exposes Phase 61 diagnostics in normal
  agent run output.
- Added dormant env flags:
  - `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`
  - `BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE=1`
- Lifecycle payloads include read-only mutation proof:
  no orders, cancels, systemd changes, or env writes are performed by the
  lifecycle recorder.

## Server Evidence

Server artifact:

- `/opt/binance-futures-agent/runtime/phase63-live-cycle-smoke.json`
  - `status=entry_capacity_blocked`
  - `submitted=false`
  - `candidate_count=0`
  - `market_snapshot_count=0`
  - `persisted.position_lifecycle=432677`

The next normal live timer run also wrote lifecycle event `432682` before live
candidate event `439056`. The lifecycle diagnostics showed:

- `NEARUSDT`: `close_ready`, `manual_symbol=false`
- `BTWUSDT`: `manual_hold`, `manual_symbol=true`
- `auto_management.status=disabled`

## Files Changed

- `src/bfa/agent.py`
- `src/bfa/config.py`
- `.env.example`
- `deploy/server-env.example`
- `tests/test_agent_runner.py`
- `tests/test_config.py`
- `.planning/phases/63-live-cycle-position-stewardship/63-CONTEXT.md`
- `.planning/phases/63-live-cycle-position-stewardship/63-RESEARCH.md`
- `.planning/phases/63-live-cycle-position-stewardship/63-01-PLAN.md`
- `.planning/phases/63-live-cycle-position-stewardship/63-01-SUMMARY.md`
- `.planning/phases/63-live-cycle-position-stewardship/63-VERIFICATION.md`

## Commits

- `7bc7d86` — `feat(63-01): persist live position lifecycle decisions`

## Deviations from Plan

None - plan executed as written. Automatic position execution remains disabled
on the server; this phase records lifecycle and gate state rather than enabling
unconfirmed live exits.

## Residual Notes

Phase 64 should reconcile live outcomes and turn lifecycle/exit evidence into
operator-facing guard feedback. `NEARUSDT` remains eligible for a guarded
close/reduce plan, but Phase 63 did not execute it.
