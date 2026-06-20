# Summary 44-01: Forward-Paper Guarded Setup Calibration

## Completed

- Extended `TradeSetupProfile` with `disabled_sides` and `excluded_symbols`.
- Added setup rejection reasons `side_disabled_by_profile` and
  `symbol_excluded_by_profile`.
- Preserved default/live setup behavior when no guards are configured.
- Added built-in backtest/forward-paper variant
  `quant_setup_selective_guarded`.
- The guarded variant is derived from Phase 43 attribution:
  - disables `short` setups;
  - excludes `BICOUSDT`, `BEATUSDT`, and `SLXUSDT`;
  - slightly tightens confidence, risk/reward, stop distance, notional
    fraction, and daily risk caps.
- Added strategy setup, matrix, and CLI tests for the guarded profile.

## Operational Result

The project now has a paper/backtest-only guarded variant to test whether
short-side suppression and worst-symbol quarantine improve the negative paper
evidence. A local hot matrix still kept the strategy unpromoted, but showed
loss and drawdown improvement versus `quant_setup_selective`.

## Local Evidence

- Focused tests passed with `13` tests.
- Full local suite passed with `333` tests.
- `git diff --check` passed.
- Secret-pattern scan over `git diff` found no matches.
- Local guarded matrix:
  - `quant_setup_selective`: total net PnL `-1.33280252` USDT, worst drawdown
    `1.34415856` USDT, `54` trades.
  - `quant_setup_selective_guarded`: total net PnL `-0.2336375` USDT, worst
    drawdown `0.80730079` USDT, `39` trades.
  - Both variants remained `not_promoted`.

## Not Changed

- Live timer is not restored by this phase.
- Risk profile is not changed.
- No exchange order, close, or position adjustment is executed.

## Next

Deploy guarded calibration, verify on the server, then decide whether to switch
only the paper timer to `quant_setup_selective_guarded` for fresh
out-of-sample collection.
