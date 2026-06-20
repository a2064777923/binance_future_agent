---
phase: 57
slug: adaptive-forward-paper-observation
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
---

# Phase 57 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python `unittest` |
| Config file | `pyproject.toml` |
| Quick run command | `python -m unittest tests.test_ops_forward_paper tests.test_cli tests.test_event_store_repository tests.test_event_store_migrations` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~8 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite.
- Before verification: full suite, smoke evidence, and `git diff --check` must be green.
- Max feedback latency: ~10 seconds locally, excluding optional public-market smoke.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 57-01-01 | 01 | 1 | STRAT-02 | Persist paper observations for generated and rejected candidates with reason/factor evidence. | unit/CLI | `python -m unittest tests.test_ops_forward_paper tests.test_event_store_repository` | yes | green |
| 57-01-02 | 01 | 1 | STRAT-03 | Keep paper exploration from creating live order intents or signed Binance mutations. | unit/smoke | `python -m unittest tests.test_ops_forward_paper tests.test_cli` | yes | green |
| 57-01-03 | 01 | 1 | DATA-01 | Observe a broad auto-hot universe while live allowlist remains separate. | unit/smoke | `python -m unittest tests.test_ops_forward_paper tests.test_cli` | yes | green |
| 57-01-04 | 01 | 1 | DATA-02 | Report source health for explicit, auto-hot, fallback, and narrative coverage. | unit/CLI | `python -m unittest tests.test_ops_forward_paper tests.test_cli` | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Public Binance 40-symbol smoke | DATA-01 | Depends on live public ticker state. | Run `ops forward-paper-run --auto-hot-symbols --top-n 40 ...` and verify 40 observations with `order_intents=0`. |

## Validation Sign-Off

- [x] All tasks have automated or command-backed verification.
- [x] Sampling continuity maintained.
- [x] Wave 0 has no missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally for automated checks.
- [x] `nyquist_compliant: true` set in frontmatter.

Approval: approved 2026-06-21.
