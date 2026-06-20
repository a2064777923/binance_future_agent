# Summary 38-01: Quant Setup Calibration Variants

## Completed

- Added `TradeSetupProfile` and optional `profile` support to
  `build_trade_setup`.
- Added profile gates for edge, confidence, risk/reward, indicator sample
  coverage, trend alignment, RSI extremes, stop distance cap, and notional
  fraction.
- Preserved the standard setup profile as the default for live code.
- Added built-in backtest variants:
  - `quant_setup_selective`
  - `quant_setup_scalp`
- Updated CLI/backtest support so the new variants are selectable.
- Ran recent matrix comparison into `runtime/quant_setup_matrix_phase38.json`.

## Matrix Result

- `quant_setup`: total net PnL `-7.50008697` USDT, promotion blocked.
- `quant_setup_selective`: total net PnL `0.2231175` USDT, 5m cell promoted,
  15m cell failed with `-1.40156817` USDT and worst drawdown `2.39698293` USDT.
- `quant_setup_scalp`: 5m cell promoted, total net PnL `-0.69422935` USDT,
  promotion blocked.

## Operational Result

The selective profile is materially better on 5m, but total strategy promotion
still fails because 15m remains negative and exceeds the drawdown cap. Live
automation should stay paused until either interval-aware promotion is added for
5m-only forward-paper testing or the 15m behavior is recalibrated/disabled.

No live service, timer, exchange order, position adjustment, or risk profile was
changed.
