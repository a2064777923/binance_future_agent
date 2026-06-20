# Phase 56 Context: Exposure Clearance And Manual Loss Intake

## Phase Goal

Make the current `resolve_exposure` blocker actionable and capture manual
liquidation/failure cases as structured evidence before any live resume.

## Requirements

- EXP-01: Operator can generate a read-only exposure clearance packet that
  classifies active Binance positions, normal orders, algo orders, and local
  submitted intents as agent-managed, manual, stale-attributed, or unknown.
- EXP-02: Operator can see the exact reason each manual or unknown exposure
  blocks live resume, including symbol, side, quantity, protection status,
  matching local evidence, and suggested non-mutating next action.
- EXP-03: Resume decision logic consumes exposure clearance evidence and keeps
  returning `resolve_exposure` until manual/unknown exposure is explicitly
  cleared, classified, or excluded by operator input.
- LOSS-01: Operator can record a manual liquidation or failed trade as a
  structured, secret-safe incident with symbol, side, leverage, entry/exit or
  liquidation price, stop-loss status, trigger reason, and lessons.

## Current Evidence

- v1.24 operator packet returns `resolve_exposure`, not live eligibility.
- Manual/unattributed blocker symbols include `ETHUSDT` and `BTWUSDT` in the
  archived readiness packet.
- Existing read-only tools include `ops exposure-status`,
  `ops live-resume-readiness`, and `ops operator-resume-decision`.
- Existing event store supports append-only generic artifacts; the lowest-risk
  manual incident intake path can reuse an existing category such as
  `risk_state` with a specific event type and schema.

## Decisions

- Live resume must not run while exposure is manual, unknown, or
  stale-attributed.
- Phase 56 must not place, cancel, reduce, or modify Binance orders.
- Phase 56 must not apply `30u_10x_multi_dynamic`, edit env files, or change
  systemd timers/services.
- Manual loss incidents are learning inputs, not automatic permission to trade.
- User-provided secrets must not be printed, committed, or written into
  planning/runtime artifacts.

## Implementation Notes

- Prefer extending the existing `bfa.ops` read-only style.
- Prefer CLI JSON output with stable schema names.
- Keep the manual incident record append-only and secret-safe.
- Tests should use fake signed clients and temporary SQLite databases.
