---
phase: 18-deepseek-provider-switch
verified: 2026-06-20T11:00:00+08:00
status: gaps_found
score: 4/5 must-haves verified
behavior_unverified: 1
---

# Phase 18: DeepSeek Provider Switch Verification Report

**Phase Goal:** Switch live AI decisions to DeepSeek while preserving strict
JSON validation and all pilot risk caps.
**Verified:** 2026-06-20
**Status:** gaps_found

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `BFA_AI_PROVIDER` validates to either `openai` or `deepseek`. | VERIFIED LOCALLY | Config and provider tests cover valid/invalid provider values and DeepSeek key requirements. |
| 2 | DeepSeek provider uses `/chat/completions` with JSON object mode and no committed secret values. | VERIFIED LOCALLY | Client tests inspect URL, auth header shape with synthetic key, `response_format={"type":"json_object"}`, `thinking={"type":"disabled"}`, and max token mapping. |
| 3 | Fenced or prefixed JSON responses can be extracted, then still pass through deterministic schema/risk validation. | VERIFIED LOCALLY | Decision parser tests cover fenced JSON and prefixed JSON extraction before existing schema validation. |
| 4 | Server env can be updated to DeepSeek without touching Binance credentials, pilot caps, margin mode, position mode, or other services. | PENDING | Requires deployment to `/opt/binance-futures-agent` and narrow update of `/etc/binance-futures-agent/env`. |
| 5 | Full tests, DeepSeek smoke test, and server health checks pass after deployment. | PARTIAL | Full local suite and local DeepSeek smoke passed; server evidence still needs final run. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ai_client tests.test_ai_decision tests.test_ai_providers tests.test_ai_journal tests.test_config tests.test_ops_health tests.test_agent_runner tests.test_cli` | Passed, 76 tests |
| `python -m unittest discover -s tests` | Passed, 209 tests |
| `git diff --check` | Passed with Windows LF-to-CRLF warnings only |
| Secret scan over changed files/docs | Passed; no real API key or password values found |
| Local DeepSeek smoke test | Passed; `decision=trade`, `accepted=true`, `error_count=0` |

## Human Verification Required

None for the provider switch itself after server deployment verification. The
operator still needs to fund the USD-M futures account before a real entry can
submit.

## Gaps Summary

- Server deployment verification is pending.
- LVA-05 remains pending until a future submitted live entry has protective
  stop-loss and take-profit evidence.
