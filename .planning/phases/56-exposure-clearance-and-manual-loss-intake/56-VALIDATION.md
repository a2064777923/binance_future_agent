---
phase: 56
slug: exposure-clearance-and-manual-loss-intake
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
---

# Phase 56 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python `unittest` |
| Config file | `pyproject.toml` |
| Quick run command | `python -m unittest tests.test_ops_exposure_clearance tests.test_ops_manual_loss tests.test_ops_operator_resume_decision tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~8 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite.
- Before verification: full suite and `git diff --check` must be green.
- Max feedback latency: ~10 seconds locally.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 56-01-01 | 01 | 1 | EXP-01 | Classify agent, manual, stale, unknown, open-order, and orphan-algo exposure without mutation. | unit/CLI | `python -m unittest tests.test_ops_exposure_clearance tests.test_cli` | yes | green |
| 56-01-02 | 01 | 1 | EXP-02 | Report symbol-level blockers and non-mutating next actions. | unit/CLI | `python -m unittest tests.test_ops_exposure_clearance tests.test_ops_operator_resume_decision` | yes | green |
| 56-01-03 | 01 | 1 | EXP-03 | Feed clearance evidence into operator decision and keep manual/unknown exposure blocked. | unit/CLI | `python -m unittest tests.test_ops_operator_resume_decision tests.test_cli` | yes | green |
| 56-01-04 | 01 | 1 | LOSS-01 | Record manual loss incidents as append-only, secret-safe event-store artifacts. | unit/CLI | `python -m unittest tests.test_ops_manual_loss tests.test_cli` | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

All phase behaviors have automated verification.

## Validation Sign-Off

- [x] All tasks have automated verification.
- [x] Sampling continuity maintained.
- [x] Wave 0 has no missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally.
- [x] `nyquist_compliant: true` set in frontmatter.

Approval: approved 2026-06-21.
