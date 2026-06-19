---
phase: 06-openai-decision-layer
verified: 2026-06-19T18:05:00Z
status: passed
score: 10/10 must-haves verified
behavior_unverified: 0
---

# Phase 06: OpenAI Decision Layer Verification Report

**Phase Goal:** Convert candidates into validated AI trade decisions.
**Verified:** 2026-06-19T18:05:00Z
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Candidate context packets are compact and reproducible. | VERIFIED | `src/bfa/ai/schema.py`; `tests/test_ai_schema.py`. |
| 2 | The OpenAI request uses a structured JSON schema with required decision fields. | VERIFIED | `decision_json_schema()` and `tests/test_ai_client.py`. |
| 3 | The Responses API client is fakeable and dependency-free. | VERIFIED | `OpenAIResponsesClient`; fake transport tests. |
| 4 | Response text parsing handles `output_text` and nested response content. | VERIFIED | `tests/test_ai_client.py`. |
| 5 | Pass decisions and trade decisions are validated deterministically. | VERIFIED | `tests/test_ai_decision.py`. |
| 6 | Risk-inconsistent trades are rejected before execution. | VERIFIED | Tests cover bad geometry and `risk_exceeds_cap`. |
| 7 | AI request/response journals are redacted. | VERIFIED | `tests/test_ai_journal.py`; `Authorization` added to redaction keys. |
| 8 | AI decisions can persist to the Phase 4 `ai_decisions` category. | VERIFIED | `persist_ai_decision()` and journal tests. |
| 9 | CLI can run the AI decision layer with a fake client, journal, and DB persistence. | VERIFIED | `tests/test_cli.py` covers `ai decide`. |
| 10 | Phase 6 does not place Binance orders, deploy to server, or read local secret files. | VERIFIED | Boundary grep over `src/bfa` and `tests` returned no matches. |

**Score:** 10/10 truths verified.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| AI-01: User can send a compact candidate context packet to an OpenAI model. | SATISFIED | `OpenAIResponsesClient.create_decision()` sends context through fakeable Responses API transport. |
| AI-02: The model response is parsed as structured JSON with side, decision, confidence, entry, stop, target, hold time, and reasons. | SATISFIED | Schema and validator include those fields plus `notional_usdt`. |
| AI-03: Invalid, incomplete, or risk-inconsistent model responses are rejected before execution. | SATISFIED | Validator rejects missing fields, bad side/price geometry, oversized notional, and stop-risk above cap. |
| AI-04: Every model request and redacted response is journaled for later review. | SATISFIED | `AiDecisionJournal` writes JSONL; CLI supports `--journal`; event store supports `--db`. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 111 tests |
| `git diff --check` | Passed |
| `rg -n "fapi/v1/order|create_order|new_order|place.*order|systemd|scp|ssh root@|F:\\币安API密鈅|AB2064" src/bfa tests` | Passed, no matches |
| `node $HOME\.codex\gsd-core\bin\gsd-tools.cjs query validate.health` | Degraded only for future Phase 7/8 directories not yet created |

## Human Verification Required

None. Live OpenAI and live Binance behavior remain explicitly out of Phase 6
verification. Tests use fake transports and local fixtures only.

## Gaps Summary

No Phase 6 gaps found. Phase 7 can add risk-gated dry-run/live execution on top
of the validated AI decision records.

---
*Verified: 2026-06-19T18:05:00Z*
*Verifier: Codex inline verifier*
