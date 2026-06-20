---
phase: 66
name: Live Cycle Explainability And Ledger Cadence
status: context
created: 2026-06-21
requirements:
  - OPS-03
  - LEARN-04
---

# Phase 66 Context

## Goal

Make recent live cycles inspectable enough that the operator can see why the
bot did or did not trade, why position size was small, and whether closed
outcomes have been reconciled into the live ledger.

## User Intent

The operator wants live trading to keep running while the system iterates
quickly. They are concerned that previous live decisions looked too thin and
that small positions were hard to understand. They also clarified that
`BTWUSDT` is manual and must remain outside bot management.

## Requirements

- OPS-03: Operator can inspect the latest live cycles and see every evaluated
  symbol, skip reason, factor score, AI decision, risk decision, sizing cap, and
  whether an order was submitted.
- LEARN-04: Closed live outcome reconciliation and live ledger reporting can run
  on a scheduled or single-command path without placing orders, changing env
  files, or applying guard/risk changes.

## Existing Building Blocks

- `src/bfa/agent.py` persists `position_lifecycle_decision` risk-state artifacts
  before candidate scanning.
- `src/bfa/ops/trade_trace.py` reconstructs submitted-entry flow for an
  `order_intent`, but it does not summarize no-trade cycles.
- `src/bfa/ops/live_outcome_ledger.py` already provides DB-only ledger reads
  and optional reconciliation through existing idempotent outcome persistence.
- `src/bfa/ops/pilot_learning_packet.py` composes current capacity, lifecycle,
  exit, ledger, and trace evidence into a server packet.
- Event-store tables already contain candidates, trade setups, AI decisions,
  order intents, exchange responses, risk-state artifacts, and outcomes.

## Scope

Build a read-only operator report that groups recent live artifacts into cycle
or decision summaries, explains trade/no-trade outcomes, and optionally runs
the live ledger reconciliation path. The report should prefer existing report
builders and event-store queries over duplicating exchange or order logic.

## Non-Goals

- Do not change live entry logic.
- Do not widen risk caps.
- Do not deploy to the server in this phase; server canary verification is
  Phase 70.
- Do not manage, close, resize, or count `BTWUSDT` as bot exposure.
- Do not apply guard recommendations automatically.

## Decisions

- D-01: Phase 66 is local/reporting first. Server deployment waits for Phase 70.
- D-02: Reconciliation may persist closed fills/outcomes only when explicitly
  requested through the existing `--reconcile --persist-closed` pattern.
- D-03: Default explainability mode must be non-mutating and safe in live mode.
- D-04: Sizing explanations should name the limiting cap or risk reason instead
  of only showing the final notional.
