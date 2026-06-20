---
phase: 51
plan: 01
name: Post-Change Forward-Paper Gate
status: complete
completed: 2026-06-21
---

# Summary: Post-Change Forward-Paper Gate

## What Changed

- Extended `build_forward_paper_performance_report` with `min_profit_factor`.
- Added `paper_profit_factor_below_min` as an explicit gate reason.
- Preserved existing `since` filtering so post-change evidence can be evaluated
  separately from older losing samples.
- Added `--min-profit-factor` to:
  - `ops forward-paper-performance-check`
  - `ops strategy-evidence-baseline`
- Kept `live_resume_allowed=false` even when paper promotion thresholds pass.
- Added tests for low profit-factor blocking and paper-promotion/live-resume
  separation.

## Verification

- `python -m unittest tests.test_ops_forward_paper_performance` passed: 5
  tests.
- `python -m unittest tests.test_cli.CliTests.test_ops_forward_paper_performance_check_reports_insufficient_evidence tests.test_cli.CliTests.test_ops_strategy_evidence_baseline_reports_live_resume_blockers`
  passed: 2 tests.
- `python -m unittest tests.test_ops_strategy_evidence_baseline` passed: 2
  tests.

## Operational Notes

- Phase 51 does not change the paper timer variant or live defaults.
- The intended next evidence slice is `quant_setup_selective_guarded` after the
  Phase 50 matrix result.
- Live resume remains blocked until Phase 52 readiness combines matrix,
  post-change paper, server state, exchange/manual exposure, profile state, and
  operator confirmation.
