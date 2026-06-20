---
phase: 49
plan: 01
name: Loss-Driven Setup Recalibration
status: complete
completed: 2026-06-21
---

# Summary: Loss-Driven Setup Recalibration

## What Changed

- Extended `TradeSetupProfile` with paper/backtest-only calibration gates:
  - `blocked_setup_reasons`
  - `blocked_factor_names`
  - `require_open_interest`
  - `min_quote_volume_usdt`
  - `min_abs_momentum_percent`
  - `min_volume_impulse_percent`
- Reordered setup reason handling so `crowding_risk` can be blocked by a
  profile instead of only emitted as a warning.
- Added `quant_setup_loss_recalibrated`, an explicit backtest/paper variant
  that keeps live defaults unchanged while tightening:
  - worst symbols from paper attribution
  - short side exposure
  - taker-flow acceleration
  - weak/neutral volume impulse
  - bearish RSI / weak momentum / weak trend structures
  - missing open-interest evidence
  - thin liquidity and weak momentum
  - stop/target geometry through stricter stop distance, risk/reward, and hold
    limits
- Added tests for the new profile gates and CLI/matrix variant recognition.

## Verification

- `python -m unittest tests.test_strategy_setup` passed: 8 tests.
- `python -m unittest tests.test_backtest_engine tests.test_backtest_matrix`
  passed: 14 tests.
- CLI focused tests for `quant_setup_selective`,
  `quant_setup_selective_guarded`, and `quant_setup_loss_recalibrated` passed:
  3 tests.

## Operational Notes

- No live default profile was changed.
- The new variant is available only when explicitly selected in backtest or
  forward-paper commands.
- This phase does not prove profitability; it creates a stricter candidate
  profile for Phase 50/51 evidence runs.
