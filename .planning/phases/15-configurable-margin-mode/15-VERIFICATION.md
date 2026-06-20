---
phase: 15-configurable-margin-mode
verified: 2026-06-20T01:45:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 15: Configurable Margin Mode Verification Report

**Phase Goal:** Explicitly support isolated or cross margin setup while keeping
100 USDT pilot caps unchanged.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `BFA_MARGIN_MODE` validates to `isolated` or `cross`. | VERIFIED | `tests/test_config.py`; full suite passed. |
| 2 | Isolated maps to `ISOLATED`; cross maps to `CROSSED`. | VERIFIED | `tests/test_execution_executor.py`; server cross-mode test passed. |
| 3 | Cross mode warns but does not change risk caps. | VERIFIED | Config test and redacted server health check showed caps unchanged. |
| 4 | Server env can be updated to cross mode with redacted health check passing. | VERIFIED | `/etc/binance-futures-agent/env` updated to `BFA_MARGIN_MODE=cross`; health-check passed. |
| 5 | Live timer remains fail-closed under cross mode. | VERIFIED | Post-deploy timer cycle exited 0 with `openai_backoff` and no submission. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_config tests.test_execution_executor tests.test_agent_runner tests.test_ops_health` | Passed, 31 tests |
| `python -m unittest discover -s tests` | Passed, 191 tests |
| `git diff --check` | Passed; Windows LF-to-CRLF warnings only |
| Server `ops health-check --skip-network` | Passed in live mode with `BFA_MARGIN_MODE=cross` and redacted secrets |
| Server cross-mode execution/config unit tests | Passed, 2 tests |

## Human Verification Required

None for Phase 15. LVA-05 remains conditional on a future submitted live entry.

## Gaps Summary

No Phase 15 implementation gaps found. The next live entry will still require
protective-order evidence before LVA-05 can be marked complete.
