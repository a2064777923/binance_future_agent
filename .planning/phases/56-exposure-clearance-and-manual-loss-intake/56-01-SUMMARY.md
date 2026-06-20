---
phase: 56
plan: 01
name: Exposure Clearance And Manual Loss Intake
status: complete
completed: 2026-06-21
requirements_completed:
  - EXP-01
  - EXP-02
  - EXP-03
  - LOSS-01
---

# Summary: Exposure Clearance And Manual Loss Intake

## What Changed

- Added read-only `src/bfa/ops/exposure_clearance.py`.
- Added append-only `src/bfa/ops/manual_loss.py`.
- Added CLI commands:
  - `ops exposure-clearance`
  - `ops manual-loss-record`
- Extended `ops operator-resume-decision` with
  `--exposure-clearance-report`.
- Added focused unit and CLI coverage for exposure classification, manual loss
  recording, and operator-decision clearance blocking.

## Exposure Clearance Logic

The clearance packet emits schema `bfa_exposure_clearance_v1` and classifies
active positions as:

- `agent_managed` when symbol, side, and quantity match an unreconciled local
  submitted intent.
- `manual` when the operator passes the symbol through
  `--manual-exposure-symbols`.
- `stale_attributed` when the symbol matches local submitted intent evidence
  but side or quantity no longer cleanly matches.
- `unknown` when the exchange position has no matching local submitted intent.

Manual, unknown, stale-attributed exposure, normal open orders, and orphan algo
orders keep the report at `status=resolve_exposure`.

## Manual Loss Intake

`ops manual-loss-record` records manual liquidation or failed-trade incidents as
`risk_state` artifacts with event type `manual_loss_incident` and schema
`bfa_manual_loss_incident_v1`. It captures symbol, side, leverage, entry price,
exit or liquidation price, stop-loss status, trigger reason, lessons, notes, and
timestamp. It does not call Binance or mutate server runtime state.

## Verification

- `python -m unittest tests.test_ops_exposure_clearance tests.test_ops_manual_loss tests.test_ops_operator_resume_decision tests.test_cli`
  passed: 59 tests.
- `python -m unittest discover -s tests` passed: 366 tests.
- `git diff --check` passed.
- Secret scan for the user-provided server password and AI keys found no
  matches in changed content.

## Operational Notes

- Phase 56 does not restore live automation.
- Phase 56 does not apply `30u_10x_multi_dynamic`.
- Phase 56 does not place, cancel, reduce, or modify Binance orders.
- The fastest safe next step is to deploy these read-only/append-only tools to
  the isolated server, run `ops exposure-clearance`, then feed the artifact into
  `ops operator-resume-decision`.
