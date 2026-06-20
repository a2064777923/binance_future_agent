# Verification 41: Forward-Paper Scheduling Assets

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Paper service asset exists. | VERIFIED | `deploy/systemd/binance-futures-agent-paper.service` added. |
| 2 | Paper timer asset exists. | VERIFIED | `deploy/systemd/binance-futures-agent-paper.timer` added. |
| 3 | Paper service runs forward-paper collection, not live agent execution. | VERIFIED | `tests.test_deploy_assets` checks `ops forward-paper-run` and absence of `agent run-once`. |
| 4 | Bootstrap installs paper assets without enabling or starting timers. | VERIFIED | `remote-bootstrap.sh` only installs units and reloads systemd; tests check expected paths. |
| 5 | Deployment docs explain paper-only operation. | VERIFIED | `docs/deployment.md` includes forward-paper recorder commands and notes this does not enable live timer. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 319 tests |

## Residual Risk

- A paper timer only collects observation data. It does not prove the strategy
  is ready for live trading.
- Live resume remains blocked while the default all-interval strategy
  promotion check returns `keep_live_paused`.
