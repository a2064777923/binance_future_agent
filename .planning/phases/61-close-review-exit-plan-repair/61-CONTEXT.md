# Phase 61: Close-Review Exit Plan Repair - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD fallback; typed subagents were not spawned because
Codex requires explicit user authorization for subagent delegation.

<domain>
## Phase Boundary

Phase 61 explains and repairs the gap between active-position review and an
operator-readable close/reduce plan. The immediate production symptom is that an
agent-managed `NEARUSDT` long reached `close_review` for expired hold time while
the older `time-exit-plan` path could still appear blocked or under-explained.
The operator's `BTWUSDT` position is manual and must remain excluded from agent
management.

This phase is diagnostic and planning-surface work. It must not submit Binance
orders, cancel orders, or change live timers as part of the feature itself.
</domain>

<decisions>
## Implementation Decisions

### Companion Diagnostic
- Use `ops position-adjustment-plan` as the companion diagnostic for Phase 61
  rather than expanding the older `ops time-exit-plan` model.
- Keep `time-exit-plan` as a legacy hold-time close preview, but make the
  filter-aware active-position lifecycle visible through
  `position-adjustment-plan`.
- Add per-position diagnostics to the adjustment plan report without changing
  the confirmation-gated execution flow.

### Manual Symbol Boundary
- Treat `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT` as a hard exclusion.
- Manual positions must remain visible as `manual_hold` in diagnostics, but they
  must not create close/reduce order candidates and must not block an
  agent-managed position that is otherwise close-ready.

### Close-Review Readiness
- For agent-managed `close_review` positions, diagnostics should state whether
  the lifecycle decision is `close_ready` or `blocked`.
- A `close_ready` decision must include the filter-aware full-close order plan
  generated from exchange symbol filters when available.
- A `blocked` decision must preserve exact failed preconditions such as missing
  symbol filters, quantity step mismatch, missing matching intent, missing algo
  protection, open normal orders, or missing exchange evidence.

### Urgency Ordering
- Preserve the existing review urgency semantics:
  unprotected positions are `urgent`, missing trade plan / expired hold time /
  loss near stop are `high`, and normal watch/trail conditions remain `normal`.
- Do not let manual positions contribute to actionable urgency.

### the agent's Discretion
- Add focused unit/CLI tests for diagnostics rather than broad refactors.
- Keep JSON schema additive so existing callers that read `plans` still work.
- Deploy to `/opt/binance-futures-agent` only after local tests pass, preserving
  live/paper timers.
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bfa/ops/position_review.py` already maps hold-check evidence to
  `hold`, `watch`, `trail_or_reduce`, `close_review`, and `manual_hold`.
- `src/bfa/ops/position_adjustment.py` already builds filter-aware
  `partial_take_profit` and `full_close` plans and has confirmation-gated
  execution.
- `src/bfa/ops/position_hold_check.py` still owns `time-exit-plan`; it checks
  hold-time, matching intent, and algo protection but does not use Binance
  quantity filters.
- `src/bfa/cli.py` exposes `ops position-review`,
  `ops position-adjustment-plan`, `ops position-adjustment-execute`, and
  `ops time-exit-plan`.

### Current Gap
- `position-adjustment-plan` returns actionable `plans`, but it does not expose
  a compact per-position diagnostic list that explains every active position's
  lifecycle decision.
- Manual positions are visible in `position_review`, but not in the
  `position-adjustment-plan` candidate list, which can make operator summaries
  look incomplete.
- Existing live-runner summaries can misread the report if they look for
  `actions` instead of the existing `plans` field.

### Integration Points
- Add additive diagnostics to `PositionAdjustmentPlanReport.to_dict()`.
- Reuse existing plan items to populate diagnostic lifecycle decisions.
- Keep `build_position_adjustment_execute_report()` gated by the same plan
  readiness and confirmation-token behavior.
</code_context>

<specifics>
## Specific Evidence

- Server live env currently excludes `BTWUSDT` through
  `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT`.
- Live pilot caps are 10x, 8 open positions, 80 USDT effective position
  notional, 500 USDT portfolio notional, and 400 USDT same-direction notional.
- Latest live logs show `NEARUSDT` as agent-managed `close_review` with
  `hold_time_expired`, while `BTWUSDT` is `manual_hold` with
  `manual_position_ignored`.
</specifics>

<deferred>
## Deferred Ideas

- Automatic close/reduce execution belongs to Phase 62.
- Live-cycle lifecycle decision persistence before new-entry scanning belongs
  to Phase 63.
- Outcome learning and post-exit attribution belong to Phase 64.
</deferred>
