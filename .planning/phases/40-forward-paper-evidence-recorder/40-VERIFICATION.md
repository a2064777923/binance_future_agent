# Verification 40: Forward-Paper Evidence Recorder

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Event store supports paper signal/outcome categories. | VERIFIED | `tests.test_event_store_migrations` and repository tests include new categories. |
| 2 | Forward-paper run can record a paper signal. | VERIFIED | `tests.test_ops_forward_paper` records `paper_signals` and no `order_intents`. |
| 3 | Forward-paper run can settle an open signal. | VERIFIED | `tests.test_ops_forward_paper` persists `paper_outcomes` from later bars. |
| 4 | CLI exposes the command. | VERIFIED | Focused CLI test and `ops forward-paper-run --help`. |
| 5 | Command does not use signed exchange mutation. | VERIFIED | Implementation requires only public kline client and event store. |
| 6 | Server deployment does not restart live automation. | VERIFIED | Server `live_service=inactive`, `live_timer=inactive` after deploy and smoke run. |

## Commands

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_forward_paper tests.test_event_store_migrations tests.test_event_store_repository tests.test_cli.CliTests.test_ops_forward_paper_run_records_paper_signal_only` | Passed, 10 tests |
| `python -m bfa.cli ops forward-paper-run --help` | Printed CLI help |
| Server focused tests | Passed, 10 tests |
| Server full suite | Passed, 319 tests |
| Server `ops health-check --skip-network` | Passed |
| Server `ops forward-paper-run --symbols ... --interval 5m --variant quant_setup_selective --limit 36` | Exit `0`; `generated_signals=0`, `skipped_signals=10`, no order intents created |

## Residual Risk

- The recorder is deployed but not yet scheduled for repeated collection.
- Paper evidence needs multiple fresh market windows before promotion claims can
  be trusted.
