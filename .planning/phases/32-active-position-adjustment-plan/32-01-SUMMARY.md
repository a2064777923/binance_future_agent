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
- Full local suite passed: 289 tests.
- Server focused suite passed: 72 tests.
- Server full suite passed: 289 tests.
- Server secret-safe health check passed with Binance public and DeepSeek API
  checks enabled.
- Server read-only `ops position-adjustment-plan` preview returned
  `adjustment_plan_empty` for a protected `SOLUSDT` LONG because the position
  was still within its 15-minute hold window and review recommendation was
  `hold`.
- Post-deploy live cycle included `position_review` and
  `position_adjustment_plan` summaries, then exited `entry_capacity_blocked`
  with no submission under the unchanged one-position profile.
- HYPEUSDT closed-outcome reconciliation was persisted after deployment:
  net realized PnL `0.03577392` USDT. A follow-up 10x/two-position readiness
  preview returned `ready_for_profile_switch`; no profile apply was run.

## Operational Result

The system no longer treats an open HYPE-style position as just a blocker. Each
live cycle can surface whether the position should be held, watched, partially
reduced, or fully closed, while live mutation remains confirmation-gated.
