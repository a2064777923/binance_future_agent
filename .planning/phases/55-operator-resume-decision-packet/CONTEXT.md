---
phase: 55
name: Operator Resume Decision Packet
status: ready_to_plan
created: 2026-06-21
requirements:
  - RDM-01
  - RDM-02
  - RDM-03
---

# Context: Operator Resume Decision Packet

## Goal

Produce one operator-facing packet that converts the read-only live-resume
readiness report into an explicit operational decision:

- `keep_live_paused`
- `collect_more_paper`
- `resolve_exposure`
- `eligible_for_operator_resume`

## Current Evidence

- Phase 53 proved `ops live-resume-readiness` runs on the isolated server as a
  read-only command.
- Phase 54 collected guarded evidence for `quant_setup_selective_guarded`.
- Phase 54 matrix evidence weakened versus Phase 50:
  `candidate_matrix_count=0`, total net PnL `1.33136338` USDT, worst drawdown
  `1.3130757` USDT.
- Phase 54 server guarded paper generated `0` post-change signals and the paper
  performance gate returned `no_paper_evidence`.
- Phase 54 readiness stayed `keep_live_paused`.
- The operator-opened `ETHUSDT` exposure is manual and must not be counted as
  agent-managed evidence.
- Server readiness also saw `BTWUSDT` as manual/unattributed exposure. Treat it
  as a blocker until the operator resolves or classifies it.

## Decisions

- The packet must be read-only and must not restore live timers, start services,
  apply risk profiles, edit env files, place/cancel orders, or create live
  order intents.
- Existing readiness output remains the source of truth for the underlying
  gates. Phase 55 should add a decision synthesis layer, not another trading
  strategy.
- If exchange/manual exposure or risk-profile blockers exist, the status should
  prioritize `resolve_exposure` while still listing paper/strategy blockers.
- If matrix or paper evidence is the main blocker, the status should be
  `collect_more_paper`.
- If only operator confirmation remains, the status should be
  `eligible_for_operator_resume`, and the packet should point to a separate
  explicit confirmation flow rather than performing resume.

## Scope

In scope:

- A new read-only ops command for the decision packet.
- Unit tests for status priority and read-only fields.
- CLI smoke coverage.
- Deployment docs showing how to run the packet from the server after readiness
  evidence.

Out of scope:

- Restoring live automation.
- Applying `30u_10x_multi_dynamic`.
- Closing or modifying manual positions.
- Claiming Lana-style profitability or treating social screenshots as proof.
