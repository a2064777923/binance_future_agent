# Verification 36: Indicator-Based Setup Point Logic

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Shared indicator helper exists. | VERIFIED | `tests.test_strategy_indicators` covers ATR, VWAP, RSI, EMA spread, support/resistance, and momentum output. |
| 2 | Live feature extraction exposes indicator fields. | VERIFIED | `tests.test_strategy_features` checks support, resistance, ATR, and sample size. |
| 3 | Setup scoring includes additional quantitative factors. | VERIFIED | `tests.test_strategy_setup` checks `trend_structure` and `rsi_regime` factors plus expanded factor count. |
| 4 | Setup point logic outputs `price_basis`. | VERIFIED | `tests.test_strategy_setup` checks model, stop anchor, and target basis. |
| 5 | AI context and trace expose new setup fields. | VERIFIED | `tests.test_ai_schema` and focused `test_ops_trade_trace_reconstructs_decision_flow` passed. |
| 6 | Backtest path remains compatible. | VERIFIED | `tests.test_backtest_engine` and quant setup CLI smoke test passed in focused run. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_strategy_indicators tests.test_strategy_features tests.test_strategy_setup tests.test_ai_schema tests.test_backtest_engine tests.test_cli.CliTests.test_ops_trade_trace_reconstructs_decision_flow tests.test_cli.CliTests.test_backtest_quant_setup_variant_emits_report` | Passed, 19 tests |
| `python -m unittest tests.test_agent_runner` | Passed, 8 tests |
| `git diff --check` | Passed with CRLF warnings only |

## Residual Risk

- Indicator fields depend on available kline history; sparse live snapshots
  still produce lower coverage and missing-field warnings.
- Profitability is unproven until recent-market matrix sweeps and forward
  observation are reviewed.
