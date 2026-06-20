# Summary 23-01: Closed Outcome Risk Change Strictness

## Completed

- Changed risk-change reconciliation checks to require a closed outcome ref:
  `outcome:{event_id}:closed`.
- Added a regression test proving `open_or_partial` outcomes do not clear
  submitted intents for risk-change readiness.
- Deployed the Phase 23 source and focused test to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local focused suite passed: 30 tests.
- Local full suite passed: 229 tests.
- Server focused suite passed: 6 tests.
- Server `ops risk-change-check --target-leverage 8` still returned exit `1`,
  `status=keep_current_profile`, and `risk_change_allowed=false` while BNBUSDT
  remained open and lacked a closed outcome.
- Timer remained active and service inactive after the read-only check.
