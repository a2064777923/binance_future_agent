# Phase 64 Research: Live Outcome Ledger And Guard Feedback

## Findings

1. Outcome reconciliation already exists.
   - `ops reconcile-outcomes --persist-closed` can persist closed fills and
     outcomes idempotently.
   - It skips already reconciled closed outcomes by default.

2. The missing layer is live-outcome attribution.
   - Existing outcomes are visible, but there is no compact report by symbol,
     side, setup reasons, factor evidence, exit reason, or holding behavior.
   - `ops trade-trace` can reconstruct one intent, but it is not an aggregate
     ledger.

3. Forward-paper attribution provides a good pattern.
   - `forward_paper_loss_attribution` already ranks weak groups and produces
     recommendation-like candidates.
   - Phase 64 should reuse the shape but adapt it to live outcomes and ensure
     recommendations are explicitly non-mutating.

4. Safety boundary is important.
   - Guard recommendations cannot edit env/config, raise risk, or enable live
     automation.
   - Any reconciliation persistence should only insert idempotent fills/outcomes
     from signed read-only Binance trade history.

## Recommended Implementation

- Add `src/bfa/ops/live_outcome_ledger.py`.
- Add CLI command `ops live-outcome-ledger`.
- Support:
  - `--reconcile` to run the sweep before reporting.
  - `--persist-closed` only with `--reconcile`.
  - `--symbol`, `--since`, `--latest-limit`, and `--min-group-outcomes`.
- Report:
  - summary totals and net PnL.
  - latest outcomes.
  - grouped performance by symbol, side, exit reason, setup reasons, factor
    names/reasons, and holding bucket.
  - recommendation-only guard feedback.
  - mutation proof.
- Test with synthetic order intents, trade setups, outcomes, and fake Binance
  trade history.
