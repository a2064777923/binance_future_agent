# Summary 15-01: Configurable Margin Mode

## Completed

- Added `BFA_MARGIN_MODE` defaulting to `isolated`.
- Added validation for `isolated` and `cross` only.
- Added live warning for `BFA_MARGIN_MODE=cross`.
- Mapped execution margin setup:
  - `isolated` -> `ISOLATED`;
  - `cross` -> `CROSSED`.
- Updated `.env.example` and `deploy/server-env.example`.
- Added tests for config validation, cross-mode warning, and cross-mode
  execution setup.

## Evidence

- `python -m unittest tests.test_config tests.test_execution_executor tests.test_agent_runner tests.test_ops_health`
  passed 31 tests.

## Follow-Up

- Run the full test suite.
- Deploy to server.
- Update `/etc/binance-futures-agent/env` to `BFA_MARGIN_MODE=cross` without
  changing secrets or other caps.
- Observe a live timer cycle.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
