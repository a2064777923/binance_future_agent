# Summary 43-01: Forward-Paper Loss Attribution And Recalibration

## Completed

- Added `src/bfa/ops/forward_paper_loss_attribution.py`.
- Added CLI command `ops forward-paper-loss-attribution`.
- The report reads `paper_signals` and `paper_outcomes` for a selected
  variant, interval, and optional start time.
- Settled outcomes are joined back to their originating paper signal setup
  payload.
- The report ranks worst groups by:
  - symbol;
  - side;
  - exit reason;
  - setup reasons;
  - setup warnings;
  - factor reasons;
  - negative factor names.
- The report emits recalibration candidates such as symbol quarantine, side
  tightening, exit-geometry inspection, warning penalties, and factor
  reweighting.
- `live_resume_allowed` remains `false`.
- Added focused unit and CLI tests.

## Operational Result

The project can now explain the negative paper-performance gate in a more
actionable way. Instead of only seeing total PnL and win rate, operators can
see which symbols, sides, exits, and setup evidence are associated with losses.

## Server Result

- Deployed to `/opt/binance-futures-agent/app`.
- Server focused tests passed with `3` tests.
- Server full suite passed with `330` tests.
- Secret-safe health-check passed with network checks skipped.
- `binance-futures-agent-live.service` and
  `binance-futures-agent-live.timer` remained `inactive`.
- `binance-futures-agent-paper.timer` was paused during deployment and restored
  afterwards.
- Latest server attribution report over `quant_setup_selective` `5m` returned
  `loss_attribution_ready` with `74` paper signals, `49` matched settled
  outcomes, total net PnL `-0.93131071` USDT, and win rate `0.36734694`.
- Worst symbol groups were `BICOUSDT` (`3` outcomes, `-0.89590149` USDT,
  `0.0` win rate), `BEATUSDT` (`2`, `-0.47163963`), and `SLXUSDT` (`2`,
  `-0.46805458`).
- Worst side group was `short`: `34` outcomes, total net PnL `-1.1316274`
  USDT, win rate `0.32352941`; `long` was slightly positive at `0.20031669`
  USDT.
- Worst exit group was `stop_loss`: `11` outcomes, total net PnL
  `-2.99528982` USDT, win rate `0.0`.
- Worst setup/factor associations included `rsi_bearish_momentum`,
  `taker_flow_acceleration`, `quant_short_setup`, `volume_neutral`,
  `ema_trend_down`, and `close_near_range_low`.

## Not Changed

- Live timer is not restored by this phase.
- Risk profile is not changed.
- No exchange order, close, or position adjustment is executed.
- No Binance signed endpoint is required by the attribution command.

## Next

Plan targeted recalibration around short-side filtering, stop-loss geometry,
and symbol quarantine for the worst paper symbols before any live resume.
