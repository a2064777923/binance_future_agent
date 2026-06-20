---
phase: 62
name: Guarded Position Exit Execution
verified: 2026-06-21
status: passed
---

# Phase 62 Verification

## Local Verification

- `python -m unittest tests.test_ops_position_adjustment tests.test_cli`
  - Result: passed, 70 tests.
- `python -m unittest discover -s tests`
  - Result: passed, 393 tests.
- `git diff --check`
  - Result: passed; only CRLF working-copy warnings were emitted.

## Server Verification

Server path: `/opt/binance-futures-agent/app`.

- Deployed while live/paper timers were paused and both services were inactive.
- Server focused:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest tests.test_ops_position_adjustment tests.test_cli`
  - Result: passed.
- Server full:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest discover -s tests`
  - Result: passed.
- Server health:
  `/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite --skip-network`
  - Result: passed.

## Server Runtime Evidence

Final timer/service readback after deploy:

- `binance-futures-agent-live.timer=active`
- `binance-futures-agent-live.service=inactive`
- `binance-futures-agent-paper.timer=active`
- `binance-futures-agent-paper.service=inactive`

Preview-only smoke checks:

- `phase62-position-adjustment-execute-preview.json`:
  `status=confirmation_required`, `adjustment_executed=False`,
  `confirmation_required=True`.
- `phase62-position-adjustment-execute-service-active.json`:
  `status=execution_blocked`, reason `live_service_active`.

## Requirement Checks

| Requirement | Status | Evidence |
|-------------|--------|----------|
| EXIT-01 | satisfied | Tests and server preview show execution refuses without a fresh matching token and blocks when service-active. Confirmed execution still reruns signed filter-aware plans. |
| EXIT-03 | satisfied | Tests verify partial-reduce post size, full-close flat-side checks, and cross-side algo cleanup deferral before symbol-wide cancel. |
| RISK-04 | satisfied | Execution remains reduce-only/full-close, requires current filter-aware plan, honors manual-symbol exclusion through plan rerun, and does not bypass current live/service/token guards. |

## Mutation Check

Phase 62 deployed source code and ran tests, health checks, and preview-only
execution commands without confirmation tokens or with service-active blocking.
It did not submit or cancel Binance orders.

No file under `F:\stock` was touched.
