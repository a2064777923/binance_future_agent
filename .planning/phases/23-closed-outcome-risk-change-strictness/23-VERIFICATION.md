---
phase: 23-closed-outcome-risk-change-strictness
verified: 2026-06-20T12:24:00+08:00
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
---

# Phase 23: Closed Outcome Risk Change Strictness Verification Report

**Phase Goal:** Ensure partial/open outcome artifacts cannot unlock leverage or
risk-cap profile changes.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Risk-change readiness requires `outcome:{event_id}:closed`. | VERIFIED | `unreconciled_submitted_intents` now checks exact closed outcome refs. |
| 2 | `open_or_partial` outcomes remain blocking for profile changes. | VERIFIED | Regression test inserts `outcome:{event_id}:open_or_partial` and confirms the submitted intent remains unreconciled. |
| 3 | Trading and exchange mutation paths are unchanged. | VERIFIED | Only `src/bfa/ops/risk_change_check.py` changed; command remains read-only. |
| 4 | Server live gate still blocks 8x while BNBUSDT lacks a closed outcome. | VERIFIED | Server returned exit `1`, `status=keep_current_profile`, `risk_change_allowed=false`, and unreconciled BNBUSDT event `138150`. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_risk_change_check tests.test_cli` | Passed locally, 30 tests |
| `python -m unittest discover -s tests` | Passed locally, 229 tests |
| `git diff --check` | Passed with Windows LF-to-CRLF warnings only |
| Server `python -m unittest tests.test_ops_risk_change_check` | Passed, 6 tests |
| Server `ops risk-change-check --target-leverage 8` | Returned exit `1`, `status=keep_current_profile`, `risk_change_allowed=false` |

## Live Gate Evidence

The server gate still reports:

- `position_count=1`
- `open_algo_order_count=2`
- `open_order_count=0`
- `openai_backoff_active=false`
- `reasons=["active_position_present","position_has_algo_protection","submitted_intents_missing_outcomes"]`
- unreconciled submitted intent: BNBUSDT event `138150`

## Gaps Summary

No Phase 23 gaps found. The 8x trial remains blocked until BNBUSDT is closed and
a final `closed` outcome is persisted.
