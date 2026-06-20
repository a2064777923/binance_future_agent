# Phase 31 Context: Active Position Review

## User Direction

The operator wants the system to behave like a mature crypto futures system:
open positions should be tracked continuously, not merely opened and then left
to static stop/take-profit orders. Public Lana-style systems are treated as
architecture inspiration, especially the idea of frequent position review, but
not as verified profitability evidence.

## Scope

- Build a read-only active-position review layer.
- Reuse existing signed exchange evidence and submitted order-intent records.
- Produce deterministic recommendations before any future execution-capable
  staged exit or trailing-stop phase.
- Do not place, cancel, or modify exchange orders in this phase.

## Success Criteria

1. Active positions receive hold/watch/trail_or_reduce/close_review
   recommendations.
2. Recommendations include PnL percent, R multiple, target progress, hold-time
   progress, protection count, and matching submitted-intent evidence.
3. Dangerous states fail toward review/close-review: unprotected positions,
   missing submitted plans, expired hold windows, or losses near stop risk.
4. Near-target or >=1R positions are surfaced for future trailing or partial
   reduction.
