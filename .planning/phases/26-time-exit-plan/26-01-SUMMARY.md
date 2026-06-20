# Summary 26-01: Time Exit Plan

## Completed

- Added `ops time-exit-plan`.
- Reused the Phase 25 hold-time check rather than adding another exchange
  evidence path.
- Added read-only close-order planning for overdue, protected active positions.
- Added hedge-mode close-order shape: `positionSide` is included and
  `reduceOnly` is not set.
- Added unit and CLI tests covering ready and blocked plans.
- Deployed the Phase 26 source and tests to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local focused suite passed: 7 tests.
- Local ops/CLI suite passed: 46 tests.
- Local full suite passed: 241 tests.
- Server focused suite passed: 7 tests.
- Server full suite passed: 241 tests.
- Server `ops time-exit-plan` returned exit `0`, `status=exit_plan_ready`,
  and `exit_allowed=true`.
- Server live BNBUSDT plan:
  - `side=SELL`
  - `order_type=MARKET`
  - `quantity=0.01`
  - `position_side=LONG`
  - `reduce_only=false`
  - `elapsed_minutes=79.25`
  - `hold_time_minutes=60`

## Operational Result

The system can now show the exact close-order shape for an overdue protected
position without placing the order. Actual time-exit execution remains a future
operator-approved phase.
