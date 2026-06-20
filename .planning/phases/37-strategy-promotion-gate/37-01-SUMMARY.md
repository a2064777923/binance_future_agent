# Summary 37-01: Strategy Promotion Gate

## Completed

- Added `bfa.ops.strategy_promotion`, a read-only promotion gate for matrix
  backtest reports.
- Added `ops strategy-promotion-check --matrix-report ...`.
- The gate checks report schema, selected variant summary, total net PnL,
  worst drawdown, and each interval cell's verdict, trade count, PnL,
  positive-window-rate, and drawdown.
- Ran the gate against `runtime/quant_setup_matrix_phase36.json`; it returned
  `keep_live_paused` because the latest indicator-based `quant_setup` matrix
  lost money and exceeded the pilot drawdown cap.
- Updated requirements, roadmap, and state so this negative evidence is part of
  the project record.

## Evidence

- `python -m unittest tests.test_ops_strategy_promotion tests.test_cli.CliTests.test_ops_strategy_promotion_check_blocks_negative_matrix` passed.
- `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase36.json` returned exit code `1` with `promotion_allowed=false`.

## Operational Result

This phase prevents a dangerous false positive: the strategy code can now be
well-tested and still be blocked from promotion when recent market evidence is
bad. The current `quant_setup` rules should stay paused for live automation
until calibration plus fresh matrix evidence passes this gate.

No live service, timer, exchange order, position adjustment, or risk profile was
changed.
