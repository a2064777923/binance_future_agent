# Summary 32-01: Active Position Adjustment Plan

## Completed

- Added `ops position-adjustment-plan`, a read-only mapper from active-position
  review recommendations to adjustment plans.
- Added `ops position-adjustment-execute`, which requires live mode, inactive
  live service, and an exact confirmation token before submitting reduce orders.
- Added partial take-profit planning for `trail_or_reduce` positions.
- Added full-close planning for overdue or unsafe `close_review` positions.
- Extended `agent run-once` live results with active-position review and
  adjustment plan summaries before candidate scanning.
- Added config knobs for adjustment enablement, review interval, and partial
  take-profit fraction.

## Evidence

- Focused local suites passed: position adjustment, position review, agent
  runner, CLI, and config.

## Operational Result

The system no longer treats an open HYPE-style position as just a blocker. Each
live cycle can surface whether the position should be held, watched, partially
reduced, or fully closed, while live mutation remains confirmation-gated.
