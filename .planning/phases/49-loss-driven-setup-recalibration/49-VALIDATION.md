---
phase: 49
slug: loss-driven-setup-recalibration
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
validated: 2026-06-21
---

# Phase 49 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python unittest |
| Config file | pyproject.toml |
| Quick run command | `python -m unittest tests.test_strategy_setup tests.test_backtest_engine tests.test_backtest_matrix` |
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
| 49-01-01 | 01 | 1 | SRC-01 | N/A | Weak setup/factor gates block only selected variants | unit | `python -m unittest tests.test_strategy_setup` | yes | green |
| 49-01-02 | 01 | 1 | SRC-02 | N/A | Stop/target geometry stays deterministic and profile-scoped | unit | `python -m unittest tests.test_strategy_setup tests.test_backtest_engine` | yes | green |
| 49-01-01 | 01 | 1 | SRC-03 | N/A | Missing OI, liquidity, momentum, and volume impulse gates are testable | unit | `python -m unittest tests.test_strategy_setup` | yes | green |
| 49-01-02 | 01 | 1 | SRC-04 | N/A | Live defaults remain unchanged unless explicit variant selected | cli/unit | `python -m unittest tests.test_cli.CliTests.test_backtest_quant_setup_loss_recalibrated_variant_emits_report tests.test_backtest_matrix` | yes | green |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

All phase behaviors have automated verification.

## Validation Audit 2026-06-21

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification.
- [x] Sampling continuity has no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under 10 seconds locally.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-06-21
