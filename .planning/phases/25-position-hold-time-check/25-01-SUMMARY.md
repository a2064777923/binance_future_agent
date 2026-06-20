# Summary 25-01: Position Hold-Time Check

## Completed

- Added `ops position-hold-check`.
- Reused `live-status` exchange evidence with injectable signed-client support.
- Matched active positions to unclosed submitted order intents by symbol and
  position side.
- Reported hold-time elapsed minutes, overdue status, unrealized PnL, algo
  protection count, and reasons.
- Kept the command read-only: no exchange mutation, no env changes, no timer
  changes, and no position close.
- Deployed the Phase 25 source and tests to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local focused ops/CLI suite passed: 43 tests.
- Local full suite passed: 238 tests.
- Server focused suite passed: 6 tests.
- Server full suite passed: 238 tests.
- Server `ops position-hold-check` returned exit `1`,
  `status=review_required`, and `reasons=["hold_time_expired"]`.
- Server live BNBUSDT evidence:
  - `position_amt=0.01`
  - `position_side=LONG`
  - `hold_time_minutes=60`
  - `elapsed_minutes=69.82`
  - `algo_protection_count=2`
  - `overdue=true`

## Operational Result

The live BNBUSDT position remains protected but has exceeded the AI decision's
suggested hold window. This does not trigger automatic closure; it gives the
operator and future phases a clear, scriptable review signal.
