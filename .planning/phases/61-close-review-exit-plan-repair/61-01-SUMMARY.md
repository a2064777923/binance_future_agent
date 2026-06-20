---
phase: 61
plan: 01
name: Close-Review Exit Plan Repair
status: complete
completed: 2026-06-21
requirements_addressed:
  - POS-01
  - POS-02
  - POS-04
requirements-completed: [POS-01, POS-02, POS-04]
---

# Phase 61 Summary

## Outcome

Phase 61 adds an additive `diagnostics` array to
`ops position-adjustment-plan`. Each active position now has an operator-readable
lifecycle decision with evidence states, failed preconditions, passed
preconditions, urgency, exchange-filter state, and an optional filter-aware
order-plan candidate.

The existing `plans` field and confirmation-gated execution flow are unchanged.
Manual positions remain visible in diagnostics but never become adjustment
candidates.

## Behavior Added

- Agent-managed `close_review` positions that pass filters report
  `lifecycle_decision=close_ready` and include a `full_close` market reduce
  order plan.
- Filter-blocked `close_review` positions report `lifecycle_decision=blocked`
  with exact failed preconditions such as `symbol_filters_missing`.
- Manual positions such as `BTWUSDT` report `manual_hold`,
  `manual_symbol=true`, no `order_plan`, and
  `manual_position_ignored`.
- Unprotected positions retain `urgency=urgent`, which remains higher than
  normal hold-time expiry at `urgency=high`.

## Server Evidence

Server smoke artifact:
`/opt/binance-futures-agent/runtime/phase61-position-adjustment-plan.json`.

The server smoke returned:

- `status=adjustment_plan_ready`
- `adjustment_allowed=True`
- `NEARUSDT`: `lifecycle_decision=close_ready`, candidate action `full_close`,
  manual flag `False`, urgency `high`
- `BTWUSDT`: `lifecycle_decision=manual_hold`, manual flag `True`, urgency
  `normal`
- `plans`: one agent-managed `NEARUSDT` `full_close` plan

No Phase 61 command submitted or canceled Binance orders.

## Files Changed

- `src/bfa/ops/position_adjustment.py`
- `tests/test_ops_position_adjustment.py`
- `tests/test_cli.py`
- `.planning/phases/61-close-review-exit-plan-repair/61-CONTEXT.md`
- `.planning/phases/61-close-review-exit-plan-repair/61-RESEARCH.md`
- `.planning/phases/61-close-review-exit-plan-repair/61-01-PLAN.md`
- `.planning/phases/61-close-review-exit-plan-repair/61-01-SUMMARY.md`
- `.planning/phases/61-close-review-exit-plan-repair/61-VERIFICATION.md`

## Residual Notes

Phase 61 makes the close/reduce plan state explainable and filter-aware. It does
not execute the plan. Guarded execution remains Phase 62.
