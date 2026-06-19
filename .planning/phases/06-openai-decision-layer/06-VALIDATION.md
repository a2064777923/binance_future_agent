---
phase: 06
slug: openai-decision-layer
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-19
---

# Phase 06 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python unittest |
| Config file | none |
| Quick run command | `python -m unittest tests.test_ai_schema tests.test_ai_decision tests.test_ai_client tests.test_ai_journal tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | under 1 second locally |

## Sampling Rate

- After every task commit: run the relevant focused unittest module.
- After every plan wave: run `python -m unittest discover -s tests`.
- Before phase closeout: run full suite, `git diff --check`, and boundary grep.
- Max feedback latency: under 1 minute.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-T1 | 06-01 | 1 | AI-01, AI-02 | unit | `python -m unittest tests.test_ai_schema` | yes | green |
| 06-01-T2 | 06-01 | 1 | AI-01 | unit | `python -m unittest tests.test_ai_schema` | yes | green |
| 06-01-T3 | 06-01 | 1 | AI-03 | unit | `python -m unittest tests.test_ai_decision` | yes | green |
| 06-02-T1 | 06-02 | 2 | AI-01, AI-02 | unit | `python -m unittest tests.test_ai_client` | yes | green |
| 06-02-T2 | 06-02 | 2 | AI-04 | unit | `python -m unittest tests.test_ai_journal` | yes | green |
| 06-03-T1 | 06-03 | 3 | AI-01, AI-02, AI-03, AI-04 | CLI unit | `python -m unittest tests.test_cli` | yes | green |
| 06-03-T2 | 06-03 | 3 | AI-04 | docs + grep | `rg -n "place orders" README.md .planning/phases/06-openai-decision-layer` | yes | green |

## Wave 0 Requirements

Existing unittest infrastructure covers all Phase 6 requirements.

## Manual-Only Verifications

All Phase 6 behaviors have automated verification. Live OpenAI smoke testing is
intentionally deferred until credentials are configured outside git.

## Validation Sign-Off

- [x] All tasks have automated verification.
- [x] Sampling continuity has no 3 consecutive tasks without automated verify.
- [x] No watch-mode flags are required.
- [x] Feedback latency is under 1 minute.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-06-19
