---
phase: 58
slug: promotion-matrix-and-loss-review
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
---

# Phase 58 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python `unittest` |
| Config file | `pyproject.toml` |
| Quick run command | `python -m unittest tests.test_ops_manual_loss_review tests.test_ops_strategy_promotion tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | ~8 seconds |

## Sampling Rate

- After every task commit: run the quick command.
- After every plan wave: run the full suite.
- Before verification: full suite, server matrix/promotion checks, and `git diff --check` must be green.
- Max feedback latency: ~10 seconds locally, excluding server matrix runtime.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 58-01-01 | 01 | 1 | STRAT-01 | Run completed-candle matrix with next-candle entries, fees, slippage, and small-account caps. | CLI/server artifact | `backtest matrix ...` plus `python -m unittest tests.test_ops_strategy_promotion` | yes | green |
| 58-01-02 | 01 | 1 | STRAT-04 | Distinguish collect-more-paper, forward-paper candidate, and live-resume eligibility. | unit/CLI | `python -m unittest tests.test_ops_strategy_promotion tests.test_cli` | yes | green |
| 58-01-03 | 01 | 1 | LOSS-02 | Compare manual incidents against leverage, stop, liquidation, and paper guards. | unit/CLI | `python -m unittest tests.test_ops_manual_loss_review tests.test_cli` | yes | green |
| 58-01-04 | 01 | 1 | RISK-02 | Treat Lana/Square/X claims as design inputs only, never promotion evidence. | unit/CLI | `python -m unittest tests.test_ops_strategy_promotion tests.test_cli` | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Current-data server matrix | STRAT-01 | Uses current public market data and server runtime. | Regenerate the matrix artifact and verify promotion checks stay read-only. |

## Validation Sign-Off

- [x] All tasks have automated or command-backed verification.
- [x] Sampling continuity maintained.
- [x] Wave 0 has no missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally for automated checks.
- [x] `nyquist_compliant: true` set in frontmatter.

Approval: approved 2026-06-21.
