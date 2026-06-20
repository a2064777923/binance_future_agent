---
phase: 28-dynamic-sizing-and-multi-position-guard
verified: 2026-06-20T13:55:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 28: Dynamic Sizing And Multi-Position Guard Verification Report

**Phase Goal:** Add dynamic position sizing and bounded multi-position support
without changing the active live risk profile.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Dynamic sizing config exists and defaults off. | VERIFIED | `BFA_DYNAMIC_POSITION_SIZING_ENABLED=false`; sizing test covers fixed fallback. |
| 2 | Dynamic cap uses capital, balance, leverage, margin caps, risk caps, and min executable notional warnings. | VERIFIED | `tests.test_execution_sizing`. |
| 3 | AI context and final execution risk receive computed caps. | VERIFIED | Agent wiring and AI schema tests. |
| 4 | Multi-position remains disabled by default and duplicate same-direction exposure is blocked. | VERIFIED | Execution risk tests. |
| 5 | Server has the code but live env remains unchanged. | VERIFIED | Server tests passed; config readback shows dynamic/multi disabled and 5x/12U/one-position profile unchanged. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_execution_sizing tests.test_execution_risk tests.test_ai_schema tests.test_agent_runner` | Passed locally, 21 tests |
| `python -m unittest discover -s tests` | Passed locally, 257 tests |
| Server focused dynamic sizing tests | Passed, 21 tests |
| Server `python -m unittest discover -s tests` | Passed, 257 tests |

## Live Safety

No server env values were changed in this phase. The live profile remains
5x max leverage, 12U max notional, and one open position until a separate
operator-approved profile switch after clear exchange state.
