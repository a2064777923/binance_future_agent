---
phase: 18-deepseek-provider-switch
verified: 2026-06-20T10:44:30+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 18: DeepSeek Provider Switch Verification Report

**Phase Goal:** Switch live AI decisions to DeepSeek while preserving strict
JSON validation and all pilot risk caps.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `BFA_AI_PROVIDER` validates to either `openai` or `deepseek`. | VERIFIED LOCALLY | Config and provider tests cover valid/invalid provider values and DeepSeek key requirements. |
| 2 | DeepSeek provider uses `/chat/completions` with JSON object mode and no committed secret values. | VERIFIED LOCALLY | Client tests inspect URL, auth header shape with synthetic key, `response_format={"type":"json_object"}`, `thinking={"type":"disabled"}`, and max token mapping. |
| 3 | Fenced or prefixed JSON responses can be extracted, then still pass through deterministic schema/risk validation. | VERIFIED LOCALLY | Decision parser tests cover fenced JSON and prefixed JSON extraction before existing schema validation. |
| 4 | Server env can be updated to DeepSeek without touching Binance credentials, pilot caps, margin mode, position mode, or other services. | VERIFIED | Server env summary after update showed `BFA_AI_PROVIDER=deepseek`, 100/20/3x/1/3 pilot caps, `BFA_MARGIN_MODE=cross`, `BFA_POSITION_MODE=hedge`, and unchanged isolated paths. |
| 5 | Full tests, DeepSeek smoke test, and server health checks pass after deployment. | VERIFIED | Local full suite, local DeepSeek smoke, server focused tests, server health checks, manual service cycle, and timer cycle passed. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_ai_client tests.test_ai_decision tests.test_ai_providers tests.test_ai_journal tests.test_config tests.test_ops_health tests.test_agent_runner tests.test_cli` | Passed, 76 tests |
| `python -m unittest discover -s tests` | Passed, 209 tests |
| `git diff --check` | Passed with Windows LF-to-CRLF warnings only |
| Secret scan over changed files/docs | Passed; no real API key or password values found |
| Local DeepSeek smoke test | Passed; `decision=trade`, `accepted=true`, `error_count=0` |
| Server focused tests | Passed, 76 tests |
| Server `ops health-check --skip-network` | Passed in live mode with redacted secrets |
| Server `ops health-check --check-openai` | Passed; selected provider detail reported `deepseek AI API reachable` |
| Manual live service cycle after clearing stale backoff | Exited 0; DeepSeek returned validated `decision=pass`; `status=rejected`, `submitted=false`, `risk_reasons=ai_decision_pass` |
| Server `ops live-status` | Passed; `submitted_order_intents=0`, `openai_backoff.active=false`, `lva05_complete=false` |
| `binance-futures-agent-live.timer` | Re-enabled and active; next trigger observed at 2026-06-20 10:49:08 CST |
| Automatic timer-start cycle | Exited 0; DeepSeek returned validated `decision=pass`; `submitted=false` |

## Human Verification Required

None for Phase 18. The operator still needs to fund the USD-M futures account
before a real entry can submit.

## Gaps Summary

No Phase 18 implementation gaps found. LVA-05 remains pending until a future
submitted live entry has protective stop-loss and take-profit evidence.
