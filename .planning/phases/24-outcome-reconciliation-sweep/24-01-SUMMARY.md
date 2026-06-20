# Summary 24-01: Outcome Reconciliation Sweep

## Completed

- Added `ops reconcile-outcomes` to sweep submitted live order intents.
- Added closed-only persistence with `--persist-closed`; open or partial
  outcomes are reported but not persisted by default.
- Added default skipping of submitted intents that already have
  `outcome:{event_id}:closed`.
- Reused existing fill/outcome accounting and idempotent persistence logic.
- Deployed the Phase 24 source and tests to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local focused suite passed: 8 tests.
- Local full suite passed: 232 tests.
- `git diff --check` passed with Windows LF-to-CRLF warnings only.
- Server focused suite passed: 7 tests.
- Server full suite passed: 232 tests.
- Server `ops reconcile-outcomes --persist-closed` returned:
  - `submitted_intents=2`
  - `already_reconciled=1` for ZECUSDT
  - `checked=1` for BNBUSDT
  - `open_or_partial=1`
  - `persisted_outcomes_inserted=0`
  - `persisted_fills_inserted=0`
- Server `ops risk-change-check --target-leverage 8` still returned exit `1`,
  `status=keep_current_profile`, and `risk_change_allowed=false` while BNBUSDT
  remained open and protected by two algo orders.

## Operational Result

The command now provides a safe one-shot sweep. After BNBUSDT closes, rerunning
`ops reconcile-outcomes --persist-closed` can persist the final closed outcome
without needing to remember the symbol-specific `trade-outcome` command.
