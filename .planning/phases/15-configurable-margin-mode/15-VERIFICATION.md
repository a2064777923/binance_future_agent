---
phase: 15-configurable-margin-mode
verified: 2026-06-20T01:45:00+08:00
status: pending
score: 0/5 pending full verification
behavior_unverified: 2
---

# Phase 15: Configurable Margin Mode Verification Report

**Phase Goal:** Explicitly support isolated or cross margin setup while keeping
100 USDT pilot caps unchanged.
**Verified:** pending final checks
**Status:** pending

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `BFA_MARGIN_MODE` validates to `isolated` or `cross`. | PENDING | Requires full test suite. |
| 2 | Isolated maps to `ISOLATED`; cross maps to `CROSSED`. | PENDING | Requires full test suite. |
| 3 | Cross mode warns but does not change risk caps. | PENDING | Requires full test suite and config review. |
| 4 | Server env can be updated to cross mode with redacted health check passing. | PENDING | Requires deployment. |
| 5 | Live timer remains fail-closed under cross mode. | PENDING | Requires post-deploy observation. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_config tests.test_execution_executor tests.test_agent_runner tests.test_ops_health` | Passed, 31 tests |

## Human Verification Required

Post-deploy observation is required before marking this phase passed.

## Gaps Summary

Full suite, server deploy, and live timer observation remain pending.
