# Summary 35-01: Quant Setup Backtest Calibration

## Completed

- Added `strategy_type` to `BacktestConfig` and a built-in `quant_setup`
  variant using the 30U/10x small-cap trial assumptions.
- Extended the backtest engine so `quant_setup` builds deterministic setup
  candidates from completed kline windows and feeds them through
  `build_trade_setup`.
- Added setup-driven trade simulation for long and short futures positions,
  including setup stop/target, setup notional, fees, slippage, and time exit.
- Preserved the legacy hot-momentum path for `strict`, `balanced`, and
  `aggressive`.
- Extended tests for quant setup long/short trades, matrix variant support, and
  CLI backtest reporting.

## Evidence

- Focused backtest suites passed: `tests.test_backtest_engine` and
  `tests.test_backtest_matrix`.
- Focused CLI backtest tests passed, including `quant_setup`.
- Full local suite passed: `303` tests.
- `git diff --check` passed.
- Manual CLI smoke passed:
  - `backtest run --variant quant_setup` produced
    `bfa_backtest_result_v1 quant_setup 5 long`.
  - `backtest sweep --variants quant_setup` produced
    `bfa_staged_backtest_sweep_v1 ['quant_setup'] 3 ['quant_setup']`.

## Operational Result

The deterministic setup layer can now be evaluated offline through the same
short-window backtest and matrix tooling used for earlier strategy variants.
This does not prove profitability, but it removes the previous blind spot where
the live setup logic and the backtest logic were different strategies.
