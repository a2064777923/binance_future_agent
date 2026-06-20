---
phase: 55
plan: 01
name: Operator Resume Decision Packet
status: complete
completed: 2026-06-21
requirements_completed:
  - RDM-01
  - RDM-02
  - RDM-03
---

# Summary: Operator Resume Decision Packet

## What Changed

- Added read-only `src/bfa/ops/operator_resume_decision.py`.
- Added CLI command `ops operator-resume-decision`.
- Added `--readiness-report` support so an existing
  `ops live-resume-readiness` artifact can be converted into the operator
  packet without re-querying Binance or systemd.
- When no readiness artifact is supplied, the command can build a fresh
  read-only readiness report and synthesize the packet in one run.
- Added unit and CLI coverage for status priority, grouped blockers, and
  mutation-safe output.
- Documented the server command in `docs/deployment.md`.

## Decision Logic

The packet emits schema `bfa_operator_resume_decision_v1` and exactly one
status:

- `resolve_exposure` when exchange/manual exposure or risk-profile blockers are
  present.
- `collect_more_paper` when matrix or forward-paper evidence is the main
  non-confirmation blocker.
- `keep_live_paused` when server or AI/provider health blockers remain.
- `eligible_for_operator_resume` only when all non-confirmation blockers are
  clear. Even then, the packet requires a separate explicit confirmation flow
  and performs no resume action.

Blockers are grouped as:

- `strategy`
- `paper`
- `server`
- `exchange_manual_exposure`
- `risk_profile`
- `ai_provider_health`
- `confirmation`

## Phase 54 Artifact Smoke

Running the new command against
`runtime/server-live-resume-readiness-phase54-20260620T181837Z.json` returned:

- `status=resolve_exposure`
- `eligible_for_operator_resume=false`
- Manual/unattributed symbols: `ETHUSDT`, `BTWUSDT`
- Blockers: strategy suite not promoted, paper signals missing,
  manual/unattributed exposure present, active-position/risk-profile blockers,
  and operator confirmation required.
- Read-only mutation flags all false.

## Verification

- `python -m unittest tests.test_ops_operator_resume_decision tests.test_cli`
  passed: 51 tests.
- `python -m bfa.cli ops operator-resume-decision --help` passed.
- `python -m bfa.cli ops operator-resume-decision --readiness-report runtime/server-live-resume-readiness-phase54-20260620T181837Z.json`
  returned expected fail-closed exit code `1` with `status=resolve_exposure`.
- `python -m unittest discover -s tests` passed: 358 tests.
- `git diff --check` passed.

## Operational Notes

- Phase 55 does not restore live automation.
- Phase 55 does not apply `30u_10x_multi_dynamic`.
- Phase 55 does not place, cancel, or modify Binance orders.
- The current decision is not "ready for live"; it is
  `resolve_exposure`, with paper evidence still insufficient.
