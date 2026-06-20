# Verification 43: Forward-Paper Loss Attribution And Recalibration

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | CLI exposes a read-only forward-paper loss attribution command. | VERIFIED | Local and server focused CLI tests passed. |
| 2 | The command joins outcomes back to originating paper signal setup payloads. | VERIFIED | Unit test checks setup evidence; server report matched `49` outcomes to signals. |
| 3 | The report ranks losing groups by symbol, side, exit reason, setup reasons, warnings, and factors. | VERIFIED | Local tests and server attribution report include all configured groupings. |
| 4 | The report emits recalibration candidates while keeping `live_resume_allowed=false`. | VERIFIED | Server report emitted symbol/side/exit/setup/factor candidates and false live resume flag. |
| 5 | The command does not use signed exchange mutation or write order intents. | VERIFIED | Implementation only reads SQLite paper tables; live service/timer remained inactive. |
| 6 | Server deployment keeps live automation inactive while paper scheduling remains isolated. | VERIFIED | Paper timer restored active; live service/timer inactive. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_forward_paper_loss_attribution tests.test_cli.CliTests.test_ops_forward_paper_loss_attribution_reports_negative_groups` | Passed, 3 tests |
| `python -m unittest discover -s tests` | Passed, 330 tests |
| `git diff --check` | Passed |
| Secret-pattern scan over `git diff` | Passed; no matches |
| Server focused tests | Passed, 3 tests |
| Server full suite | Passed, 330 tests |
| Server `ops health-check --skip-network` | Passed, `ok=true` |
| Server `ops forward-paper-loss-attribution --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite --min-group-outcomes 1 --worst-limit 5` | `loss_attribution_ready`; `signal_count=74`, `outcome_count=49`, `total_net_pnl_usdt=-0.93131071`, `win_rate=0.36734694`, `live_resume_allowed=false` |
| Server service state after deploy | Paper timer active; live service/timer inactive |

## Residual Risk

- Attribution identifies associations, not causal proof.
- The strongest current candidates are to tighten or temporarily quarantine
  short-side setups, stop-loss-heavy entries, and worst symbols such as
  `BICOUSDT`, `BEATUSDT`, and `SLXUSDT`.
- Any recalibration candidate must still be verified by backtest and forward
  paper evidence before live resume.
