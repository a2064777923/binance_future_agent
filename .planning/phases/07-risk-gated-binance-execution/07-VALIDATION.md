---
phase: 07
slug: risk-gated-binance-execution
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-20
---

# Phase 07 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python unittest |
| Config file | none |
| Quick run command | `python -m unittest tests.test_execution_filters tests.test_execution_risk tests.test_execution_binance_client tests.test_execution_executor` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | under 1 second locally |

## Sampling Rate

- After every task commit: run focused execution tests.
- After every plan wave: run `python -m unittest discover -s tests`.
- Before phase closeout: run full suite, `git diff --check`, and boundary grep.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-T1 | 07-01 | 1 | EXE-01, EXE-03 | unit | `python -m unittest tests.test_execution_risk` | present | passed |
| 07-01-T2 | 07-01 | 1 | EXE-04 | unit | `python -m unittest tests.test_execution_filters` | present | passed |
| 07-02-T1 | 07-02 | 2 | EXE-02, EXE-04 | unit | `python -m unittest tests.test_execution_binance_client` | present | passed |
| 07-03-T1 | 07-03 | 3 | EXE-01, EXE-02, EXE-03, EXE-04 | unit/CLI | `python -m unittest tests.test_execution_executor tests.test_cli` | present | passed |
| 07-04-T1 | 07-04 | 4 | EXE-05 | unit | `python -m unittest tests.test_execution_reconcile` | present | passed |

## Manual-Only Verifications

Live Binance order submission is not manually verified in this phase run. The
phase verifies that the live branch is gated, fakeable, and explicit.

## Validation Sign-Off

- [x] All tasks have planned automated verification.
- [x] No live external calls are required for verification.
- [x] `nyquist_compliant: true` set in frontmatter.
