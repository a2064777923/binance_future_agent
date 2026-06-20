# Phase 64: Live Outcome Ledger And Guard Feedback - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD fallback.

<domain>
## Phase Boundary

Phase 64 turns live execution evidence into a compact operator-facing ledger.
The project already has idempotent Binance fill/outcome reconciliation and
trade trace reconstruction, but the operator still lacks a single view that
summarizes live outcomes by symbol, side, setup profile, factors, exit reason,
and holding behavior.

This phase must stay recommendation-only for guard feedback. It may persist
closed outcomes when the operator passes an explicit reconcile/persist flag, but
it must not raise risk caps, edit env files, restore timers, place orders, or
change strategy defaults by itself.
</domain>

<decisions>
## Implementation Decisions

### Ledger Command
- Add a read-only `ops live-outcome-ledger` command.
- It should load existing `outcomes` and related `order_intents`,
  `trade_setups`, `ai_decisions`, and `exchange_responses`.
- It should optionally run the existing submitted-intent reconciliation sweep
  with `--persist-closed`, reusing current idempotent fill/outcome persistence.

### Attribution Dimensions
- Report by symbol, side, setup profile/reasons, factor names/reasons, exit
  reason, and holding-time bucket where available.
- Include latest closed outcomes and enough trace IDs to let the operator drill
  into `ops trade-trace`.

### Guard Feedback
- Generate recommendation-only guard feedback for weak groups:
  quarantine/reduce symbol, tighten side, inspect exit geometry, tighten setup
  reasons, or reweight factors.
- Every recommendation must include `applies_changes=false` and
  `raises_risk=false`.
</decisions>

<code_context>
## Existing Code Insights

- `execution.outcome.reconcile_submitted_trade_outcomes()` can fetch and
  persist closed outcomes idempotently.
- `ops trade-trace` reconstructs candidate -> setup -> AI -> risk -> exchange
  flow for a submitted intent.
- Forward-paper performance/loss-attribution modules already contain useful
  grouping and recommendation patterns, but they are paper-specific.
- Outcome payloads store the submitted `intent_event_id`, which can join back
  to `order_intents` and setup records by symbol/decided time.
</code_context>

<deferred>
## Deferred Ideas

- Automatically applying guard changes remains out of scope.
- Risk-cap increases remain out of scope until repeated positive closed live
  outcomes pass future promotion gates.
</deferred>
