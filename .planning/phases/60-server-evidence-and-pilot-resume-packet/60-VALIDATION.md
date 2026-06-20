---
phase: 60
slug: server-evidence-and-pilot-resume-packet
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
---

# Phase 60 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python `unittest` |
| Config file | `pyproject.toml` |
| Quick run command | `python -m unittest tests.test_ops_risk_profile tests.test_ops_live_resume_plan tests.test_ops_exposure_status tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~8 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite locally and on server when deployed code changes.
- Before verification: local full suite, server full suite, artifact refresh, and `git diff --check` must be green.
- Max feedback latency: ~10 seconds locally, excluding server SSH/test latency.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 60-01-01 | 01 | 1 | LIVE-03 | Live cycles expose position review, adjustment plan, entry capacity, and trade trace evidence. | server artifact/CLI | server `ops position-review`, `ops position-adjustment-plan`, `ops exposure-status`, `ops trade-trace` | yes | green |
| 60-01-02 | 01 | 1 | RISK-03 | Deployment and evidence writes stay scoped to `/opt/binance-futures-agent` and `/etc/binance-futures-agent`; no `F:\stock` writes. | local/server command | local/server full suites, server artifact readback, `git status`, `git diff --check` | yes | green |
| 60-01-03 | 01 | 1 | RISK-01 | Widened 30U/10x profile remains bounded by margin, notional, risk, and daily loss. | unit/server artifact | `python -m unittest tests.test_ops_risk_profile tests.test_ops_live_resume_plan tests.test_ops_exposure_status tests.test_cli` | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Server isolation readback | RISK-03 | Requires checking the live deployment target. | Verify artifacts under `/opt/binance-futures-agent/app/runtime/` and env under `/etc/binance-futures-agent/env`; confirm no `F:\stock` changes. |
| Live timer/service state | LIVE-03 | Requires systemd state on the server. | Verify live timer active, live service inactive, paper timer active, paper service inactive after deployment. |

## Validation Sign-Off

- [x] All tasks have automated or command-backed verification.
- [x] Sampling continuity maintained.
- [x] Wave 0 has no missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally for automated checks.
- [x] `nyquist_compliant: true` set in frontmatter.

Approval: approved 2026-06-21.
