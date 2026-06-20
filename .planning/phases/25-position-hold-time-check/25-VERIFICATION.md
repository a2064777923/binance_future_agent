---
phase: 25-position-hold-time-check
verified: 2026-06-20T12:54:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 25: Position Hold-Time Check Verification Report

**Phase Goal:** Report whether active positions have exceeded AI
`hold_time_minutes` guidance without mutating exchange state.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ops position-hold-check` exists and is read-only. | VERIFIED | CLI route added; implementation only reads live-status exchange evidence and local event-store rows. |
| 2 | Active positions are matched to unclosed submitted intents. | VERIFIED | Unit and server evidence matched BNBUSDT to submitted event `138150`. |
| 3 | Hold-time expiry is detected and reported. | VERIFIED | Server reported BNBUSDT `elapsed_minutes=69.82`, `hold_time_minutes=60`, `overdue=true`. |
| 4 | Protective-order state remains visible. | VERIFIED | Server report included `algo_protection_count=2`, so the state is review-required, not unprotected urgent attention. |
| 5 | Existing live-status fake-client injection works for tests. | VERIFIED | CLI regression test proves `ops live-status --check-binance` can use an injected signed client. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ops_position_hold_check tests.test_cli.CliTests.test_ops_position_hold_check_reports_expired_live_hold_window tests.test_cli.CliTests.test_ops_live_status_uses_injected_signed_client_for_binance_evidence` | Passed locally, 6 tests |
| `python -m unittest tests.test_ops_position_hold_check tests.test_ops_resume_check tests.test_ops_risk_change_check tests.test_cli` | Passed locally, 43 tests |
| `python -m unittest discover -s tests` | Passed locally, 238 tests |
| Server focused position-hold/live-status injection tests | Passed, 6 tests |
| Server `python -m unittest discover -s tests` | Passed, 238 tests |
| Server `ops position-hold-check` | Returned exit `1`, `status=review_required`, `reasons=["hold_time_expired"]` |

## Live Evidence

The server check reported:

- `position_count=1`
- `open_order_count=0`
- `open_algo_order_count=2`
- `openai_backoff_active=false`
- BNBUSDT LONG amount `0.01`
- entry `581.47`
- mark about `581.1`
- unrealized PnL about `-0.0037` USDT
- hold window `60` minutes
- elapsed about `69.82` minutes
- `overdue=true`

## Gaps Summary

No Phase 25 gaps found. Automatic time-based exits remain out of scope; this
phase only adds a verified review signal.
