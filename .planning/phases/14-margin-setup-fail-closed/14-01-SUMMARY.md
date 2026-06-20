# Summary 14-01: Margin Setup Fail-Closed

## Completed

- Added `MarginFailingSignedClient` regression coverage for Binance
  Multi-Assets mode rejecting isolated-margin setup.
- Updated `ExecutionEngine.run` to catch `BinanceSignedError` from
  `_ensure_live_margin`.
- Margin setup failures now return a rejected, non-submitted execution result
  with `margin_setup_failed`.
- Margin error details are persisted as exchange-response evidence before the
  service exits successfully.
- Entry order submission remains blocked unless margin/leverage setup succeeds.

## Evidence

- The new regression test failed before the fix with uncaught
  `BinanceSignedError`.
- The same regression test passed after the fix.
- `python -m unittest tests.test_execution_executor tests.test_agent_runner tests.test_ops_live_status tests.test_execution_reconcile`
  passed 16 tests.

## Follow-Up

- Deploy Phase 14 while the live timer is stopped.
- Re-enable the timer after health checks pass.
- Observe one live cycle to confirm service exit success and rejected evidence if
  the account remains in Multi-Assets mode.
- LVA-05 remains pending because no entry order has been submitted.
