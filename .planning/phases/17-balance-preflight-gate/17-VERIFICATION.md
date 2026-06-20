---
phase: 17-balance-preflight-gate
verified: 2026-06-20T00:00:00+08:00
status: pending
score: 0/5 must-haves verified
behavior_unverified: 1
---

# Phase 17: Balance Preflight Gate Verification Report

**Phase Goal:** Avoid repeated live order attempts when Binance futures
available balance is below the order intent's estimated initial margin.
**Verified:** Pending final local and server checks.
**Status:** pending

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Live execution reads account available balance before margin setup or entry order placement. | PENDING | Awaiting full verification run. |
| 2 | Insufficient available balance rejects with `insufficient_available_balance`. | PENDING | Awaiting full verification run. |
| 3 | Account-balance read errors reject before entry order placement. | PENDING | Awaiting full verification run. |
| 4 | No order is submitted when futures account available balance is insufficient. | PENDING | Awaiting full verification run and server observation. |
| 5 | Full tests and server health checks pass after deployment. | PENDING | Awaiting full verification run and deployment. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Pending |
| `git diff --check` | Pending |
| Secret scan over changed files | Pending |
| Server health check | Pending |
| Live timer observation | Pending |

## Human Verification Required

None for Phase 17. Funding the Binance USD-M futures account is an operator
action required before a real entry can submit, but it is not required to verify
that the balance preflight rejects safely.

## Gaps Summary

Pending final verification.
