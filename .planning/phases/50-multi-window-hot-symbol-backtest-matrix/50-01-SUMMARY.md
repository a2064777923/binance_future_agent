---
phase: 50
plan: 01
name: Multi-Window Hot-Symbol Backtest Matrix
status: complete
completed: 2026-06-21
---

# Summary: Multi-Window Hot-Symbol Backtest Matrix

## What Changed

- Added `BacktestMatrixSuiteConfig` and `run_hot_backtest_matrix_suite`.
- Added reusable hot-universe presets:
  - `broad`: top 40, >= 10M quote volume, >= 0.5% absolute 24h move.
  - `momentum`: top 24, >= 10M quote volume, >= 3% absolute 24h move.
  - `liquid`: top 30, >= 50M quote volume, >= 0.5% absolute 24h move.
- Added CLI command:
  `python -m bfa.cli backtest matrix-suite`.
- The suite runs the existing staged matrix once per universe preset and
  aggregates variant promotion evidence across presets.
- Added tests for preset resolution, suite payloads, and CLI output.

## Phase 50 Evidence

Report path: `runtime/quant_setup_matrix_phase50.json` (runtime evidence, not
committed).

Command:

```powershell
python -m bfa.cli backtest matrix-suite --intervals 5m,15m --limit 144 --window-bars 72 --step-bars 36 --variants quant_setup_selective,quant_setup_selective_guarded,quant_setup_loss_recalibrated --universe-presets broad,momentum,liquid --output runtime/quant_setup_matrix_phase50.json
```

Overall suite verdict: `mixed_candidate_collect_more_data`.

| Variant | Matrix Count | Candidate Matrices | Total Net PnL | Worst Drawdown | Verdict |
|---------|--------------|--------------------|---------------|----------------|---------|
| `quant_setup_selective` | 3 | 0 | `0.0908186` | `1.30123772` | `not_promoted` |
| `quant_setup_selective_guarded` | 3 | 2 | `7.1058786` | `0.92783188` | `mixed_candidate_collect_more_data` |
| `quant_setup_loss_recalibrated` | 3 | 0 | `0.0` | `0.0` | `not_promoted` |

Universe details:

| Preset | Symbols | Overall | Best Variant |
|--------|---------|---------|--------------|
| `broad` | 40 | `mixed_candidate_collect_more_data` | `quant_setup_selective_guarded` |
| `momentum` | 24 | `candidate_for_forward_paper` | `quant_setup_selective_guarded` |
| `liquid` | 30 | `candidate_for_forward_paper` | `quant_setup_selective_guarded` |

## Verification

- `python -m unittest tests.test_backtest_matrix` passed: 8 tests.
- `python -m unittest tests.test_cli.CliTests.test_backtest_matrix_suite_emits_multi_universe_report tests.test_cli.CliTests.test_backtest_matrix_auto_selects_hot_symbols_and_writes_report`
  passed: 2 tests.
- Public Binance matrix-suite smoke completed and wrote the runtime report.

## Operational Notes

- No signed Binance endpoints were used.
- No live service, timer, risk profile, env file, position, or order state was
  changed.
- `quant_setup_selective_guarded` is the only Phase 50 candidate to carry into
  Phase 51 forward-paper gates.
- `quant_setup_loss_recalibrated` is currently too strict and generated no
  trades in this matrix, so it is not promoted.
