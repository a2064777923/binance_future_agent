# Phase 62: Guarded Position Exit Execution - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD fallback; typed subagents were not spawned because
Codex requires explicit user authorization for subagent delegation.

<domain>
## Phase Boundary

Phase 62 turns Phase 61's filter-aware `close_ready`/`reduce` plans into a
safer operator-confirmed execution path. It should harden the existing
`ops position-adjustment-execute` path rather than introduce live-cycle
automation. Automatic execution remains Phase 63.

The phase may add safety checks around submitted close/reduce orders, but it
must not run a confirmed execution against Binance during development or
verification. Server smoke checks must remain preview/read-only.
</domain>

<decisions>
## Implementation Decisions

### Execution Gate
- Keep `BFA_MODE=live` required.
- Keep `--service-active` blocking behavior.
- Keep fresh confirmation token behavior based on the current rerun plan.
- Keep `now` override forbidden when a confirmation token is supplied.
- Continue requiring Binance symbol filters for confirmed execution.

### Manual Symbol Boundary
- Rely on the fresh `position-adjustment-plan` rerun, which classifies
  `BFA_MANUAL_POSITION_SYMBOLS` as `manual_hold` diagnostics and does not
  produce manual order candidates.
- Add tests proving a manual-only position cannot be executed because there are
  no adjustment candidates.

### Post-Action Checks
- For `partial_take_profit`, verify the post-order position amount is reduced
  to the planned `expected_remaining_position_amt` or lower in absolute value.
- For `full_close`, keep requiring the relevant position side to become flat
  before cleanup.
- If post-action verification fails or cannot be read, persist the execution as
  submitted but cleanup-deferred, not falsely complete.

### Protective Cleanup
- The Binance cancel-all algo endpoint is symbol-wide. Before using it after a
  full close, read open algo orders for that symbol and defer cleanup if any
  open algo order belongs to a different position side.
- Only call `cancel_all_open_algo_orders(symbol)` when the relevant position
  side is flat and no cross-side algo order is present.

### the agent's Discretion
- Keep schema additive and secret-safe.
- Add focused tests in `tests/test_ops_position_adjustment.py` and CLI coverage
  where useful.
- Deploy to the isolated server after local tests pass, then run preview-only
  smoke evidence.
</decisions>

<code_context>
## Existing Code Insights

- `src/bfa/ops/position_adjustment.py` already:
  - requires live mode;
  - blocks when service is active;
  - refuses confirmed execution with `now`;
  - reruns the signed filter-aware plan before token comparison;
  - requires confirmation token;
  - persists order intents and exchange responses;
  - cancels algo orders after `full_close` only when post amount is zero.
- The current implementation does not verify partial-reduce post size against
  `expected_remaining_position_amt`.
- The current implementation calls symbol-wide algo cancel after full close
  without checking for cross-side algo orders.
- `BinanceFuturesSignedClient.open_algo_orders(symbol)` exists and can support
  the cross-side cleanup guard.
</code_context>

<specifics>
## Specific Evidence

- Phase 61 server smoke shows `NEARUSDT` as `close_ready` with a `full_close`
  candidate and `BTWUSDT` as `manual_hold`.
- Server live/paper timers are active; services are normally inactive between
  timer runs.
- Current live caps are 30U account, 10x leverage, 8 open positions, 80U
  effective notional, 500U portfolio notional, 400U same-direction notional,
  0.4U per-trade risk, and 1U daily loss.
</specifics>

<deferred>
## Deferred Ideas

- Auto-management during live cycles remains Phase 63.
- Outcome reconciliation after exits remains Phase 64.
</deferred>
