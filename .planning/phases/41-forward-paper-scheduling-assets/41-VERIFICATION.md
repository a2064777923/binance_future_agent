# Verification 41: Forward-Paper Scheduling Assets

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Paper service asset exists. | VERIFIED | `deploy/systemd/binance-futures-agent-paper.service` added. |
| 2 | Paper timer asset exists. | VERIFIED | `deploy/systemd/binance-futures-agent-paper.timer` added. |
| 3 | Paper service runs forward-paper collection, not live agent execution. | VERIFIED | `tests.test_deploy_assets` checks `ops forward-paper-run` and absence of `agent run-once`. |
| 4 | Bootstrap installs paper assets without enabling or starting timers. | VERIFIED | `remote-bootstrap.sh` only installs units and reloads systemd; tests check expected paths. |
| 5 | Deployment docs explain paper-only operation. | VERIFIED | `docs/deployment.md` includes forward-paper recorder commands and notes this does not enable live timer. |
| 6 | Server deployment keeps live inactive and enables only paper scheduling. | VERIFIED | Server systemd status showed live service/timer inactive, paper timer active, and paper service logs returned `paper_run_complete`. |
| 7 | Paper observation can scan wider auto-hot symbols without changing live allowlist. | VERIFIED LOCALLY | CLI/config/deploy tests cover `BFA_FORWARD_PAPER_*`, `--auto-hot-symbols`, and top-40 paper service args. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 319 tests |
| Server `python -m unittest tests.test_deploy_assets` | Passed, 6 tests |
| Server `python -m unittest discover -s tests` | Passed, 319 tests |
| Server `ops health-check --skip-network` | Passed, `ok=true` |
| Server `systemctl enable --now binance-futures-agent-paper.timer` | Paper timer active; live timer remained inactive |
| Server `journalctl -u binance-futures-agent-paper.service -n 120 --no-pager` | `paper_run_complete`, `generated_signals=0`, `skipped_signals=10` |
| `python -m unittest tests.test_config tests.test_deploy_assets tests.test_cli.CliTests.test_ops_forward_paper_run_records_paper_signal_only tests.test_cli.CliTests.test_ops_forward_paper_run_auto_selects_hot_symbols` | Passed, 31 tests |

## Residual Risk

- A paper timer only collects observation data. It does not prove the strategy
  is ready for live trading.
- Live resume remains blocked while the default all-interval strategy
  promotion check returns `keep_live_paused`.
