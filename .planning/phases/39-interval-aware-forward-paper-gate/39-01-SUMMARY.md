# Summary 39-01: Interval-Aware Forward Paper Gate

## Completed

- Added `--scope all-intervals|selected-intervals` to
  `ops strategy-promotion-check`.
- Added `--intervals` for selected-interval checks.
- Preserved strict all-interval behavior as the default.
- Added report fields:
  - `scope`
  - `intervals`
  - `selected_summary`
  - `live_resume_allowed`
- Selected-interval success now returns `status=forward_paper_allowed` and
  `reasons=["selected_intervals_promoted"]`.
- Full-variant success remains the only path that can set
  `live_resume_allowed=true`.

## Evidence

- `quant_setup_selective` on `5m` from
  `runtime/quant_setup_matrix_phase38.json` returned
  `forward_paper_allowed` with `live_resume_allowed=false`.
- The same `quant_setup_selective` report with default all-interval scope still
  returned `keep_live_paused` because the `15m` cell failed PnL,
  positive-window-rate, and drawdown checks.

## Operational Result

The system can now separate "worth observing in forward-paper on 5m" from
"safe to resume live automation." Live automation remains paused until strict
all-interval evidence passes or the failed intervals are explicitly removed and
revalidated.

No live service, timer, exchange order, position adjustment, or risk profile was
changed.
