---
phase: 48
plan: 01
name: Strategy Evidence Baseline
status: complete
completed: 2026-06-21
---

# Summary: Strategy Evidence Baseline

## What Changed

- Added `bfa.ops.strategy_evidence_baseline`, a compact read-only report that
  combines:
  - forward-paper performance metrics
  - latest settled outcomes
  - loss attribution by symbol, side, exit reason, setup reason/warning, factor
    reason, and negative factor name
  - adaptive forward-paper guard output
  - server automation state for `paper.timer`, `live.timer`, and `live.service`
  - exchange/manual exposure state when supplied
  - operator confirmation requirements
- Added CLI entrypoint:
  `python -m bfa.cli ops strategy-evidence-baseline`.
- Added read-only Linux `systemctl is-active` checks for the three project
  units. Local/non-systemd runs return `unknown` unless explicit override
  arguments are supplied.
- Added grouped live-resume blockers under `strategy_evidence`,
  `server_state`, `exchange_state`, and `confirmation`.
- Added read-only guarantees in the JSON output: the command does not place
  orders, apply risk profiles, write env files, mutate exchange state, change
  systemd state, or create `order_intents`.

## Verification

- `python -m unittest tests.test_ops_strategy_evidence_baseline` passed: 2
  tests.
- `python -m unittest tests.test_cli.CliTests.test_ops_strategy_evidence_baseline_reports_live_resume_blockers`
  passed: 1 test.
- `python -m unittest discover -s tests` passed: 342 tests.
- `git diff --check` passed with only existing CRLF normalization warnings.
- Secret scan over changed files found no raw API keys, provider keys,
  password, or risk-profile tokens.

## Operational Notes

- Live resume remains blocked by default because operator confirmation is still
  required and current strategy evidence can be negative.
- Manual exposure can be reported separately through
  `--exchange-state manual_exposure --manual-exposure-symbols ...`; it is not
  treated as agent strategy evidence.
- No server deployment or live automation restore was performed in this phase.
