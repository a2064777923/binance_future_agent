# Verification 43: Forward-Paper Loss Attribution And Recalibration

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | CLI exposes a read-only forward-paper loss attribution command. | VERIFIED LOCALLY | Focused CLI test passed. |
| 2 | The command joins outcomes back to originating paper signal setup payloads. | VERIFIED LOCALLY | Unit test checks setup warnings and factor evidence from joined signal payloads. |
| 3 | The report ranks losing groups by symbol, side, exit reason, setup reasons, warnings, and factors. | VERIFIED LOCALLY | Unit test verifies negative symbol, side, exit reason, and setup-warning groups. |
| 4 | The report emits recalibration candidates while keeping `live_resume_allowed=false`. | VERIFIED LOCALLY | Unit test checks candidates and false live resume flag. |
| 5 | The command does not use signed exchange mutation or write order intents. | VERIFIED LOCALLY | Implementation only reads SQLite paper tables and builds a report. |
| 6 | Server deployment keeps live automation inactive while paper scheduling remains isolated. | PENDING | Awaiting server verification. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_forward_paper_loss_attribution tests.test_cli.CliTests.test_ops_forward_paper_loss_attribution_reports_negative_groups` | Passed, 3 tests |
| `python -m unittest discover -s tests` | Passed, 330 tests |
| `git diff --check` | Passed |
| Secret-pattern scan over `git diff` | Passed; no matches |
| Server focused tests | Pending |
| Server full suite | Pending |
| Server `ops health-check --skip-network` | Pending |
| Server `ops forward-paper-loss-attribution --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite` | Pending |

## Residual Risk

- Attribution identifies associations, not causal proof.
- Any recalibration candidate must still be verified by backtest and forward
  paper evidence before live resume.
