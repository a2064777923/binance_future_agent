---
phase: 66
name: Live Cycle Explainability And Ledger Cadence
status: complete
created: 2026-06-21
mode: inline-fallback
---

# Phase 66 Research

## Current Evidence Sources

- `position_lifecycle_decision` risk-state artifacts record active-position
  lifecycle decisions before new-entry scanning.
- Candidate, trade setup, AI decision, and order intent artifacts share symbol
  and timestamp-like ref IDs that can be grouped into decision flows.
- `ops trade-trace` is useful for submitted intents, but no-trade cycles need a
  broader event-store query because they may stop at candidate, quant setup, AI
  pass, or risk rejection.
- `ops live-outcome-ledger` already supports optional reconciliation. It should
  be reused rather than reimplemented.
- `ops pilot-learning-packet` proves composition patterns and mutation-proof
  reporting for live operator artifacts.

## Design Implications

1. Add a new ops report module rather than extending `agent.py`.
2. Treat "cycle" as a bounded time/event window around recent live artifacts.
   Start with deterministic grouping by ref IDs and timestamps; later phases can
   improve live runner cycle IDs if needed.
3. Include a `sizing_explanation` section that translates dynamic sizing result
   reasons, risk rejection reasons, and exchange filter warnings into operator
   language.
4. Keep reconciliation optional and explicit. Default report generation should
   not write fills/outcomes.
5. Make mutation proof explicit so the command is safe to run in live mode.

## Risks

- Historical no-trade cycles may lack one stable cycle ID. The first
  implementation should expose `evidence_quality` and missing-artifact notes
  instead of pretending every cycle is perfectly reconstructable.
- If live runner output does not persist every skipped candidate, Phase 66
  should report that gap; Phase 67 can improve candidate breadth persistence.
- Ledger reconciliation with `persist_closed` is intentionally a write to the
  local event store, even though it does not touch Binance orders or env files.
  The mutation proof must distinguish event-store outcome persistence from
  exchange/system/risk mutation.

## Recommended Implementation

- Add `src/bfa/ops/live_cycle_explainability.py`.
- Add CLI command `ops live-cycle-explainability`.
- Query recent artifacts from the SQLite event store with a configurable
  `--latest-cycles` limit and optional `--since`.
- Reuse `build_live_outcome_ledger_report()` for ledger cadence.
- Add tests around submitted cycle, AI-pass/no-order cycle, quant/risk-blocked
  cycle, manual-symbol visibility, sizing explanation, and non-mutation proof.
