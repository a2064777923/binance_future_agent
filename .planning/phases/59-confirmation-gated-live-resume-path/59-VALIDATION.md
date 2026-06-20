---
phase: 59
slug: confirmation-gated-live-resume-path
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
---

# Phase 59 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python `unittest` |
| Config file | `pyproject.toml` |
| Quick run command | `python -m unittest tests.test_ops_live_resume_plan tests.test_ops_risk_profile tests.test_ops_exposure_status tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~8 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite.
- Before verification: full suite, blocked apply smoke, and `git diff --check` must be green.
- Max feedback latency: ~10 seconds locally.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 59-01-01 | 01 | 1 | LIVE-01 | Preview target profile, timers/services, readiness artifact, token, and non-mutation proof. | unit/CLI | `python -m unittest tests.test_ops_live_resume_plan tests.test_cli` | yes | green |
| 59-01-02 | 01 | 1 | LIVE-02 | Refuse mutation unless operator packet is eligible and token matches. | unit/CLI | `python -m unittest tests.test_ops_live_resume_plan tests.test_cli` | yes | green |
| 59-01-03 | 01 | 1 | RISK-01 | Keep target profile bounded by capital, margin, notional, concentration, risk, and daily-loss caps. | unit/CLI | `python -m unittest tests.test_ops_risk_profile tests.test_ops_live_resume_plan tests.test_ops_exposure_status` | yes | green |

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
