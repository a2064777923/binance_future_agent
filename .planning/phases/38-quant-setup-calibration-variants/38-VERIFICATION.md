# Verification 38: Quant Setup Calibration Variants

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Setup profiles exist and default live behavior is preserved. | VERIFIED | `TradeSetupProfile` defaults to `standard`; `build_trade_setup` profile is optional. |
| 2 | Profiles can reject trades by calibration gates. | VERIFIED | `tests.test_strategy_setup` covers profile rejections. |
| 3 | New built-in variants exist. | VERIFIED | CLI `backtest run --help` lists `quant_setup_selective` and `quant_setup_scalp`. |
| 4 | Matrix accepts calibrated variants. | VERIFIED | `tests.test_backtest_matrix` covers baseline plus selective variant; matrix smoke ran all three quant variants. |
| 5 | Recent evidence is checked through promotion gate. | VERIFIED | Promotion checks for baseline, selective, and scalp all returned `keep_live_paused`. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_strategy_setup tests.test_backtest_engine tests.test_backtest_matrix tests.test_cli.CliTests.test_backtest_quant_setup_selective_variant_emits_report` | Passed, 19 tests |
| `python -m bfa.cli backtest matrix --intervals 5m,15m --limit 144 --window-bars 72 --step-bars 36 --variants quant_setup,quant_setup_selective,quant_setup_scalp --top-n 8 --output runtime/quant_setup_matrix_phase38.json` | Completed |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase38.json --variant quant_setup_selective` | Exit `1`, `keep_live_paused`; 5m passed, 15m failed |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase38.json --variant quant_setup_scalp` | Exit `1`, `keep_live_paused`; 5m passed, total PnL negative |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase38.json --variant quant_setup` | Exit `1`, `keep_live_paused` |

## Residual Risk

- The 5m selective profile may be overfit to a short recent window. It needs
  more windows/days and forward-paper evidence before live use.
- 15m behavior is still not acceptable.
