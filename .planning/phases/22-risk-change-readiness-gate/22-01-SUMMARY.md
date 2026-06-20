# Summary 22-01: Risk Change Readiness Gate

## Completed

- Added `ops risk-change-check`.
- Added a read-only report for leverage/risk-cap change readiness.
- Reused live-status exchange evidence for account, positions, normal orders,
  algo orders, and AI backoff.
- Added local event-store inspection for submitted order intents that do not yet
  have persisted outcomes.
- Added tests for active protected positions, orphan orders, missing exchange
  evidence, and unreconciled submitted intents.
- Deployed the Phase 22 source and focused tests to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local full suite passed: 228 tests.
- Server focused suite passed: 29 tests.
- Server `ops risk-change-check --target-leverage 8` returned exit `1`,
  `status=keep_current_profile`, `risk_change_allowed=false`.
- Server reasons were:
  - `active_position_present`
  - `position_has_algo_protection`
  - `submitted_intents_missing_outcomes`
- The unreconciled submitted intent was BNBUSDT event `138150`, leverage `5`,
  quantity `0.01`.
- Timer remained active and service inactive after the read-only check.
