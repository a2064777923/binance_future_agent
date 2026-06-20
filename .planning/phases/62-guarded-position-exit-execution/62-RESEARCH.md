# Phase 62 Research: Guarded Position Exit Execution

**Mode:** Inline fallback research. No subagent was spawned because this Codex
session requires explicit user authorization before delegation.

## Findings

1. Existing position adjustment execution already has most entry gates.
   - `build_position_adjustment_execute_report()` requires live mode.
   - It blocks when the live service is active.
   - It forbids confirmed execution with `now`.
   - It reruns a signed plan and requires filters before token comparison.
   - It requires a matching `POSITION-ADJUST-*` token before placing an order.

2. The main execution gap is post-action verification.
   - `full_close` checks post amount becomes zero before cleanup.
   - `partial_take_profit` currently submits and persists even if the post
     amount was not reduced as intended.

3. Protective cleanup needs a hedge-mode side guard.
   - Binance's `DELETE /fapi/v1/algoOpenOrders` is symbol-wide.
   - The client already has `open_algo_orders(symbol)` to inspect open algo
     orders before using the symbol-wide cancel endpoint.
   - Full-close cleanup should be deferred if open algo orders for the same
     symbol include a different `positionSide` than the closed side.

4. Manual positions remain guarded by plan rerun.
   - Phase 61's plan rerun exposes manual positions as diagnostics only.
   - Since manual positions do not enter `plans`, execution has no token/action
     for them.

## Recommended Implementation

- Add helpers in `position_adjustment.py`:
  - `_post_adjustment_verified(order_plan, post_amount)`
  - `_opposite_side_algo_orders_present(client, order_plan)`
- For partial reduces, set cleanup-deferred if the post amount is missing or
  above the expected remaining amount in the same direction.
- For full closes, before canceling protective algo orders, inspect open algo
  orders and defer cleanup when cross-side algo orders are present.
- Add focused tests for:
  - manual-only execution blocked before order;
  - partial reduce deferred when post amount is not reduced enough;
  - partial reduce accepted when post amount reaches expected remaining;
  - full close defers symbol-wide cleanup when cross-side algo orders exist;
  - existing confirmation/service/filter gates remain intact.
