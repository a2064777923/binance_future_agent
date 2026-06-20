# Verification 44: Forward-Paper Guarded Setup Calibration

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Setup profiles can disable selected sides. | VERIFIED LOCALLY | `tests.test_strategy_setup` covers `disabled_sides=["short"]`. |
| 2 | Setup profiles can exclude selected symbols. | VERIFIED LOCALLY | `tests.test_strategy_setup` covers `excluded_symbols=["BTCUSDT"]`. |
| 3 | A guarded quant setup variant is available to backtest and forward-paper paths. | VERIFIED LOCALLY | Matrix and CLI tests cover `quant_setup_selective_guarded`. |
| 4 | Default/live setup behavior remains unchanged unless guards are configured. | VERIFIED LOCALLY | Default short setup still trades in focused setup test before guarded profile rejects it. |
| 5 | Server deployment keeps live automation inactive while paper scheduling remains isolated. | PENDING | Awaiting server verification. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_strategy_setup tests.test_backtest_matrix tests.test_cli.CliTests.test_backtest_quant_setup_selective_guarded_variant_emits_report` | Passed, 13 tests |
| `python -m unittest discover -s tests` | Passed, 333 tests |
| `git diff --check` | Passed |
| Secret-pattern scan over `git diff` | Passed; no matches |
| `python -m bfa.cli backtest matrix --intervals 5m --limit 144 --window-bars 72 --step-bars 36 --variants quant_setup_selective,quant_setup_selective_guarded --top-n 8 --output runtime\quant_setup_guarded_matrix_phase44.json` | Completed; guarded improved PnL and drawdown but remained `not_promoted` |
| Server focused tests | Pending |
| Server full suite | Pending |
| Server `ops health-check --skip-network` | Pending |

## Residual Risk

- Guarded variant improved a local 5m matrix but remained negative; it should
  be used for paper observation only, not live resume.
- Guarded variants may reduce trade count too far; forward-paper evidence still
  needs enough settled outcomes.
- Paper/backtest guard success is not live-resume permission.
