# Phase 61 Research: Close-Review Exit Plan Repair

**Mode:** Inline fallback research. No subagent was spawned because this Codex
session requires explicit user authorization before delegation.

## Findings

1. `time-exit-plan` is hold-time centric.
   - It lives in `src/bfa/ops/position_hold_check.py`.
   - It checks overdue hold time, algo protection, matching submitted intent,
     and zero position amount.
   - It does not consult Binance symbol filters, so it cannot fully answer
     "can this close/reduce order pass exchange quantity constraints?"

2. `position-adjustment-plan` is the better repair surface.
   - It already consumes `position_review` recommendations.
   - It builds `full_close` for `close_review` and `partial_take_profit` for
     `trail_or_reduce`.
   - It already supports exchange filters via `SymbolExecutionFilters`.
   - It feeds the existing confirmation-gated execution path.

3. The missing operator-facing layer is diagnostic, not a new executor.
   - Existing reports expose `position_review` and actionable `plans`.
   - They do not expose a compact per-position lifecycle decision that says
     `manual_hold`, `watch`, `reduce`, `close_ready`, `blocked`, or `hold`.
   - Adding diagnostics is additive and avoids disturbing execution semantics.

4. Manual positions must be non-blocking.
   - Adding manual positions directly into the existing `plans` list would make
     allowed agent-managed plans look blocked because report status currently
     treats any non-allowed plan as a failed precondition.
   - A separate diagnostics list can show manual exclusions without blocking
     valid close/reduce candidates.

## Recommended Implementation

- Add a `PositionLifecycleDiagnostic` dataclass to
  `src/bfa/ops/position_adjustment.py`.
- Include `diagnostics` on `PositionAdjustmentPlanReport`.
- Derive diagnostics from `PositionReviewReport.positions` and existing
  adjustment plan items.
- Use lifecycle decisions:
  - `manual_hold` for manual symbols.
  - `close_ready` for allowed full-close `close_review` plans.
  - `reduce` for allowed partial take-profit plans.
  - `blocked` for actionable recommendations whose preconditions fail.
  - `watch` for watch-only positions.
  - `hold` for normal hold positions.
- Preserve `plans` and `adjustment_allowed` semantics exactly.

## Pitfalls

- Do not make manual diagnostics block agent-managed close plans.
- Do not submit or cancel Binance orders in Phase 61.
- Do not remove existing `time-exit-plan`; later phases may still reference it.
- Keep schema additive so existing CLI tests and live-runner JSON consumers keep
  working.
