# Verification 45: Live Auto-Hot Candidate Breadth

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Config exposes live auto-hot symbol selection and keeps it disabled by default. | VERIFIED LOCALLY | `tests.test_config` checks default `BFA_LIVE_AUTO_HOT_SYMBOLS=false` and positive top-N validation. |
| 2 | Runner can derive a wider hot-symbol universe from Binance 24h ticker data. | VERIFIED LOCALLY | `test_run_once_can_scan_auto_hot_symbols_beyond_fixed_live_allowlist` selects `HOTUSDT,ALTUSDT` while `BFA_MARKET_SYMBOLS=BTCUSDT`. |
| 3 | Runner falls back to `BFA_MARKET_SYMBOLS` when auto-hot returns empty. | VERIFIED LOCALLY | `test_run_once_auto_hot_falls_back_to_market_symbols_when_empty`. |
| 4 | The selected universe drives collection, narrative matching, market heat, replay packet, and candidate allowlist. | VERIFIED LOCALLY | Agent runner test asserts `scan_symbols`, selected symbol, and candidate count from auto-hot symbols outside fixed allowlist. |
| 5 | Wider scanning does not widen order authority by itself. | VERIFIED LOCALLY | `top_n=1` auto-hot test scans two symbols but evaluates one candidate; existing queue/risk tests still pass. |
| 6 | Env examples document the new variables without enabling live auto-hot. | VERIFIED LOCALLY | `tests.test_deploy_assets` checks `BFA_LIVE_AUTO_HOT_SYMBOLS=false`. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_config tests.test_deploy_assets tests.test_agent_runner.AgentRunnerTests.test_run_once_can_scan_auto_hot_symbols_beyond_fixed_live_allowlist tests.test_agent_runner.AgentRunnerTests.test_live_run_once_tries_next_candidate_after_duplicate_exposure_reject` | Passed, 31 tests |
| `python -m unittest tests.test_agent_runner` | Passed, 10 tests |
| `python -m unittest tests.test_cli.CliTests.test_agent_run_once_executes_dry_run_chain_with_injected_fakes tests.test_cli.CliTests.test_config_check_dry_run_example_exits_zero` | Passed, 2 tests |
| `python -m unittest discover -s tests` | Passed, 335 tests |
| `git diff --check` | Passed |
| Secret-pattern scan over `git diff` | Passed; no matches |

## Residual Risk

- Live auto-hot selection is broader and will add public API work when enabled;
  it should be deployed disabled first and observed through dry-run/manual runs.
- This phase improves candidate breadth, not strategy profitability. Promotion
  and live-resume gates still depend on backtest/paper/live evidence.
- Server verification is still pending for this phase.
