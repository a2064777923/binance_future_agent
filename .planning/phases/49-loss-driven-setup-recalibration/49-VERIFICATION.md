---
phase: 49
status: passed
verified: 2026-06-21
---

# Verification: Phase 49

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Profiles can tighten weak symbols, side, setup-reason, factor-reason, and factor-name groups. | VERIFIED | `quant_setup_loss_recalibrated` excludes worst symbols, disables short side, blocks setup reasons, factor reasons, and negative factor names. |
| 2 | Stop/target geometry can be recalibrated using existing ATR/structure/VWAP logic and observed stop-loss attribution. | VERIFIED | Variant tightens stop distance, raises minimum risk/reward, lowers hold bars, and keeps geometry through existing ATR/support/resistance/VWAP setup code. |
| 3 | Setup scoring can penalize missing open interest, thin liquidity, weak momentum, weak volume impulse, and historically losing factor conditions. | VERIFIED | New profile gates are covered by `tests.test_strategy_setup`. |
| 4 | Recalibrated setup remains paper/backtest-first and does not change live defaults. | VERIFIED | Only `built_in_variants()` adds `quant_setup_loss_recalibrated`; live config/default setup profile is unchanged. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_strategy_setup` | Passed, 8 tests |
| `python -m unittest tests.test_backtest_engine tests.test_backtest_matrix` | Passed, 14 tests |
| `python -m unittest tests.test_cli.CliTests.test_backtest_quant_setup_selective_variant_emits_report tests.test_cli.CliTests.test_backtest_quant_setup_selective_guarded_variant_emits_report tests.test_cli.CliTests.test_backtest_quant_setup_loss_recalibrated_variant_emits_report` | Passed, 3 tests |

## Residual Risk

The recalibrated profile may be too selective. Phase 50 must test it across
multiple recent hot-symbol windows before any forward-paper promotion or live
readiness decision.
