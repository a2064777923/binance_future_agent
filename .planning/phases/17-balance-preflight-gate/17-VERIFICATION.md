---
phase: 17-balance-preflight-gate
verified: 2026-06-20T10:10:45+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 17: Balance Preflight Gate Verification Report

**Phase Goal:** Avoid repeated live order attempts when Binance futures
available balance is below the order intent's estimated initial margin.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Live execution reads account available balance before margin setup or entry order placement. | VERIFIED | Executor live path calls `account()` before `_ensure_live_margin`; server safe preflight calls list was only `account`. |
| 2 | Insufficient available balance rejects with `insufficient_available_balance`. | VERIFIED | Local regression and server safe preflight both returned `status=rejected`, `submitted=false`, and `risk_reasons=insufficient_available_balance`. |
| 3 | Account-balance read errors reject before entry order placement. | VERIFIED | Local regression covers Binance account API error `-1021` and call list remains only `account`. |
| 4 | No order is submitted when futures account available balance is insufficient. | VERIFIED | Server safe preflight used the real Binance account payload with fake order methods; it rejected with calls=`account` and no margin, leverage, entry, or algo-order call. |
| 5 | Full tests and server health checks pass after deployment. | VERIFIED | Local full suite, server focused tests, server health check, and timer re-enable passed. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_execution_executor` | Passed, 10 tests |
| `python -m unittest discover -s tests` | Passed, 197 tests |
| `git diff --check` | Passed; Windows LF-to-CRLF warnings only |
| Secret scan over changed files | Reported only synthetic test fixture key names; no real secret values found |
| Server focused tests | Passed, 21 tests |
| Server `ops health-check --skip-network` | Passed in live mode with `BFA_MARGIN_MODE=cross`, `BFA_POSITION_MODE=hedge`, and redacted secrets |
| Server read-only futures account balance | Passed; `availableBalance=0.00000000`, `totalWalletBalance=0.00000000`, `totalMarginBalance=0.00000000` |
| Server safe preflight with real account payload and fake order methods | Passed; `status=rejected`, `submitted=false`, `risk_reasons=insufficient_available_balance`, `calls=account` |
| Manual live service cycle after deployment | Exited 0 with `openai_backoff`, no submission |
| Automatic live timer cycle after deployment | Exited 0 with `ai_rejected` invalid JSON from OpenAI endpoint, no submission |
| `binance-futures-agent-live.timer` | Re-enabled and active |

## Human Verification Required

None for Phase 17. Funding the Binance USD-M futures account is an operator
action required before a real entry can submit, but it is not required to verify
that the balance preflight rejects safely.

## Gaps Summary

No Phase 17 implementation gaps found. LVA-05 remains pending until an actual
live entry is submitted and protective-order evidence is present.
