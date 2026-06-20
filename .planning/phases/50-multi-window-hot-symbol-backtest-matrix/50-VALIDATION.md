---
phase: 50
slug: multi-window-hot-symbol-backtest-matrix
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
validated: 2026-06-21
---

# Phase 50 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python unittest |
| Config file | pyproject.toml |
| Quick run command | `python -m unittest tests.test_backtest_matrix tests.test_cli.CliTests.test_backtest_matrix_suite_emits_multi_universe_report tests.test_cli.CliTests.test_backtest_matrix_auto_selects_hot_symbols_and_writes_report` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~7 seconds |

## Sampling Rate

- After task commit: run the quick command.
- After plan wave: run the full suite.
- Before milestone audit: full suite must be green.
- Max feedback latency: ~10 seconds locally.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 50-01-01 | 01 | 1 | BFP-01 | N/A | Matrix-suite covers multiple hot universes and intervals using public data | unit/cli | `python -m unittest tests.test_backtest_matrix tests.test_cli.CliTests.test_backtest_matrix_suite_emits_multi_universe_report` | yes | green |
| 50-01-02 | 01 | 1 | BFP-02 | N/A | Promotion cells keep fail-closed matrix metrics in JSON output | unit/cli | `python -m unittest tests.test_backtest_matrix tests.test_cli.CliTests.test_backtest_matrix_auto_selects_hot_symbols_and_writes_report` | yes | green |
| 50-01-03 | 01 | 1 | BFP-01 | N/A | Public matrix smoke writes runtime report without signed exchange mutation | manual artifact | `runtime/quant_setup_matrix_phase50.json` exists from Phase 50 smoke | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Fresh public Binance matrix evidence | BFP-01 | Depends on live public market data and is intentionally stored under ignored `runtime/` | Re-run the Phase 50 matrix-suite command before making promotion decisions. |

## Validation Audit 2026-06-21

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or documented manual runtime evidence.
- [x] Sampling continuity has no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally for non-network tests.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-06-21
