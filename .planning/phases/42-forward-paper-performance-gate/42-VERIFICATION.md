# Verification 42: Forward-Paper Performance Gate

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | CLI exposes a read-only forward-paper performance command. | VERIFIED LOCALLY | `tests.test_cli.CliTests.test_ops_forward_paper_performance_check_reports_insufficient_evidence` and CLI smoke. |
| 2 | The command evaluates paper signals and outcomes by variant and interval. | VERIFIED LOCALLY | `tests.test_ops_forward_paper_performance` covers variant/interval paper evidence. |
| 3 | Missing or insufficient paper evidence blocks promotion. | VERIFIED LOCALLY | Empty DB smoke returned `no_paper_evidence`; focused tests cover insufficient outcomes. |
| 4 | Enough but losing or drawdown-heavy paper evidence blocks promotion. | VERIFIED LOCALLY | `test_enough_bad_outcomes_keep_live_paused_with_metrics`. |
| 5 | Promising paper evidence can pass the paper gate but never allows live resume. | VERIFIED LOCALLY | `test_promising_paper_evidence_passes_paper_gate_not_live_resume`. |
| 6 | The command does not use signed exchange mutation or write order intents. | VERIFIED LOCALLY | Implementation reads SQLite paper tables only; no signed client path is constructed for this CLI branch. |
| 7 | Server deployment keeps live automation inactive while paper scheduling remains isolated. | PENDING | Awaiting server verification. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_forward_paper_performance tests.test_cli.CliTests.test_ops_forward_paper_performance_check_reports_insufficient_evidence` | Passed, 5 tests |
| `python -m bfa.cli ops forward-paper-performance-check --db data\nonexistent_perf.sqlite --min-outcomes 1` | Exit 1 as expected; `status=no_paper_evidence`, `live_resume_allowed=false` |
| `python -m unittest discover -s tests` | Passed, 327 tests |
| `git diff --check` | Passed |
| Secret-pattern scan over `git diff` | Passed; no matches |
| Server focused tests | Pending |
| Server full suite | Pending |
| Server `ops health-check --skip-network` | Pending |
| Server `ops forward-paper-performance-check --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite --min-outcomes 20` | Pending |

## Residual Risk

- Paper outcomes can be sparse when market windows have not yet settled.
- A passing paper gate is still only forward-paper evidence; live resume remains
  blocked until stronger strategy promotion evidence passes.
