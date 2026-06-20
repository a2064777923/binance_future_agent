# Summary 16-01: Position Mode And Entry Fail-Closed

## Completed

- Added `BFA_POSITION_MODE` defaulting to `one_way`.
- Added validation for `one_way` and `hedge` only.
- Added live warning for `BFA_POSITION_MODE=hedge`.
- Added signed-client support for `positionSide` on entry and test orders.
- Added signed-client support for `positionSide` and `triggerPrice` on
  conditional algo orders.
- Updated execution to send hedge `positionSide` values on entry, protective,
  and emergency close orders.
- Updated execution to catch entry order errors as rejected, non-submitted
  evidence with `entry_order_failed`.

## Evidence

- `python -m unittest tests.test_config tests.test_execution_binance_client tests.test_execution_executor tests.test_agent_runner tests.test_ops_live_status`
  passed 40 tests.

## Follow-Up

- Run the full test suite.
- Deploy to server.
- Update `/etc/binance-futures-agent/env` to `BFA_POSITION_MODE=hedge` without
  changing secrets or risk caps.
- Observe a live timer cycle.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
