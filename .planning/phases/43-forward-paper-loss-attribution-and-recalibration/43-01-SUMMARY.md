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

## Not Changed

- Live timer is not restored by this phase.
- Risk profile is not changed.
- No exchange order, close, or position adjustment is executed.
- No Binance signed endpoint is required by the attribution command.

## Next

Deploy the attribution report, run it against the server paper DB, and use the
result to plan targeted setup recalibration.
