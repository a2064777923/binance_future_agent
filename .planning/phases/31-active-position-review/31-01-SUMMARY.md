# Summary 31-01: Active Position Review

## Completed

- Added `ops position-review`, a read-only active-position review command.
- Extended submitted-intent hold evidence with entry, stop, and target prices.
- Added deterministic review metrics:
  - PnL percent
  - stop-risk R multiple
  - target progress
  - hold-time progress
  - algo protection count
  - matching submitted intent event id
- Added recommendations:
  - `hold`
  - `watch`
  - `trail_or_reduce`
  - `close_review`
- Added tests for near-target, expired-hold, unprotected, and CLI output cases.

## Evidence

- Focused local suite passed: 42 tests.
- Full local suite passed: 282 tests.

## Operational Result

The system now has the deterministic review layer needed before implementing
execution-capable staged exits or trailing-stop adjustment.
