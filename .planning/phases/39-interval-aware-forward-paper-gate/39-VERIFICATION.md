# Verification 39: Interval-Aware Forward Paper Gate

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Default all-interval promotion behavior remains strict. | VERIFIED | `tests.test_ops_strategy_promotion` covers mixed evidence blocking by default. |
| 2 | Selected-interval scope can evaluate only requested interval cells. | VERIFIED | `tests.test_ops_strategy_promotion` covers `scope="selected-intervals", intervals=["5m"]`. |
| 3 | Selected-interval success cannot be used as live-resume permission. | VERIFIED | Report returns `forward_paper_allowed` with `live_resume_allowed=false`. |
| 4 | CLI exposes selected-interval arguments. | VERIFIED | Focused CLI test and `ops strategy-promotion-check --help`. |
| 5 | Real Phase 38 matrix separates 5m forward-paper from all-interval live gate. | VERIFIED | Selected 5m exits `0`; default all-interval exits `1`. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_strategy_promotion tests.test_cli.CliTests.test_ops_strategy_promotion_check_blocks_negative_matrix tests.test_cli.CliTests.test_ops_strategy_promotion_check_accepts_selected_interval_scope` | Passed, 9 tests |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase38.json --variant quant_setup_selective --scope selected-intervals --intervals 5m` | Exit `0`, `forward_paper_allowed`, `live_resume_allowed=false` |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase38.json --variant quant_setup_selective` | Exit `1`, `keep_live_paused` |

## Residual Risk

- `5m` evidence is still from a short recent matrix and may be overfit.
- Forward-paper observation should collect fresh out-of-sample evidence before
  any live resume or leverage increase.
