---
phase: 31
status: passed
verified: 2026-06-21
---

# Verification: Phase 31

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `ops position-review` is read-only and produces recommendations for active positions. | VERIFIED | `tests.test_ops_position_review` and CLI coverage exercise the report path without execution calls. |
| 2 | Review output includes PnL percent, R multiple, target progress, hold-time progress, protection count, and matching submitted intent. | VERIFIED | Focused position-review tests cover metric fields and submitted-intent matching. |
| 3 | Unsafe or stale states fail toward `close_review`. | VERIFIED | Tests cover unprotected positions and expired hold windows producing urgent review/close recommendations. |
| 4 | Near-target or favorable positions are surfaced for future trail/reduce handling. | VERIFIED | Tests cover near-target long positions producing `trail_or_reduce`. |
| 5 | Phase does not place, cancel, or modify exchange orders. | VERIFIED | Implementation is an ops review/report path only; later execution-capable behavior is introduced in Phase 32. |

## Commands

| Command | Result |
|---------|--------|
| Focused local suite from Phase 31 summary | Passed, 42 tests |
| `python -m unittest discover -s tests` from Phase 31 summary | Passed, 282 tests |
| Fresh `python -m unittest discover -s tests` after Phase 47 | Passed, 339 tests |

## Requirements

| Requirement | Status | Evidence |
|-------------|--------|----------|
| APR-01 | SATISFIED | `ops position-review` reports hold/watch/trail/reduce/close recommendations. |
| APR-02 | SATISFIED | Review metrics include PnL percent, R multiple, target progress, hold-time progress, protection count, and submitted-intent evidence. |
| APR-03 | SATISFIED | Focused tests cover unprotected, missing/expired, and near-stop style failure toward review. |

## Residual Risk

This phase is deliberately read-only. Execution-capable staged exits and
filter-aware reduce orders are covered by later phases.
