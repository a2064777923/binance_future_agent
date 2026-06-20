# Verification 37: Strategy Promotion Gate

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Matrix report gate exists. | VERIFIED | `bfa.ops.strategy_promotion.build_strategy_promotion_check_report` added and unit tested. |
| 2 | Missing/invalid reports fail closed. | VERIFIED | `tests.test_ops_strategy_promotion` covers missing report. |
| 3 | Negative matrix evidence blocks promotion. | VERIFIED | Unit and CLI tests cover negative matrix behavior. |
| 4 | Passing matrix evidence can allow promotion. | VERIFIED | Unit test covers promoted matrix behavior. |
| 5 | Phase 36 live-readiness evidence is blocked. | VERIFIED | Manual CLI check on `runtime/quant_setup_matrix_phase36.json` returned `keep_live_paused`. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_strategy_promotion tests.test_cli.CliTests.test_ops_strategy_promotion_check_blocks_negative_matrix` | Passed, 4 tests |
| `python -m bfa.cli ops strategy-promotion-check --matrix-report runtime/quant_setup_matrix_phase36.json` | Exit `1`, `promotion_allowed=false`, `status=keep_live_paused` |

## Residual Risk

- The gate consumes matrix report evidence; it does not itself generate better
  strategy parameters.
- The next phase should calibrate `quant_setup` thresholds and rerun the matrix
  before any live resume discussion.
