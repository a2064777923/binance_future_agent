---
phase: 60
plan: 01
name: Server Evidence And Pilot Resume Packet
status: complete
completed: 2026-06-21
requirements_addressed:
  - LIVE-03
  - RISK-03
---

# Phase 60 Summary

## Outcome

Phase 60 deployed and verified the confirmation-gated live resume controls on
the isolated server, refreshed server-side operator evidence, and preserved the
already-running live pilot timers. The live resume apply path remains
fail-closed because the current operator packet is not eligible.

During the phase, the operator clarified that `BTWUSDT` is a manual position
and requested a modest widening of concurrent and notional caps. The active
live env and the code-level `30u_10x_multi_dynamic` profile now match:

- `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT`
- `BFA_MAX_LEVERAGE=10`
- `BFA_MAX_OPEN_POSITIONS=6`
- `BFA_MAX_POSITION_NOTIONAL_USDT=60`
- `BFA_MAX_MARGIN_PER_POSITION_USDT=6`
- `BFA_MAX_MARGIN_FRACTION=0.20`
- `BFA_MAX_EFFECTIVE_NOTIONAL_USDT=60`
- `BFA_MAX_PORTFOLIO_MARGIN_USDT=30`
- `BFA_MAX_PORTFOLIO_MARGIN_FRACTION=0.95`
- `BFA_MAX_PORTFOLIO_NOTIONAL_USDT=360`
- `BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT=300`
- `BFA_MAX_RISK_PER_TRADE_USDT=0.4`
- `BFA_MAX_DAILY_LOSS_USDT=1`

Per-trade risk and daily-loss caps were intentionally not widened.

## Server Evidence

Server artifacts were regenerated under
`/opt/binance-futures-agent/app/runtime/`:

- `phase60-operator-decision.json`: `status=resolve_exposure`,
  `eligible_for_operator_resume=false`.
- `phase60-live-resume-plan.json`: `status=resume_apply_blocked`,
  `resume_allowed=false`, `applies_changes=false`, with the new 6-position/60
  USDT/360 USDT risk boundaries.
- `phase60-exposure-status.json`:
  `status=current_profile_entry_capacity_available`, with current profile caps
  matching the widened live env.
- `phase60-position-review.json`: `NEARUSDT` is agent-managed,
  `recommendation=close_review`, reason `hold_time_expired`; `BTWUSDT` is
  `manual_hold`, reason `manual_position_ignored`.
- `phase60-position-adjustment-plan.json`: `status=adjustment_plan_ready`, no
  live adjustment order was generated or submitted.
- `phase60-time-exit-plan.json`: `status=exit_plan_blocked`,
  reason `position_exit_preconditions_failed`.
- `phase60-near-trade-trace.json`: `status=trace_ready`.
- `phase60-post-cap-state.json`: live timer active, live service inactive,
  paper timer active, paper service inactive.

No `live-resume-apply`, time-exit execution, adjustment execution, order
placement, cancelation, or Binance mutation was run.

## Files Changed

- `src/bfa/ops/risk_profile.py`
- `tests/test_ops_risk_profile.py`
- `tests/test_ops_live_resume_plan.py`
- `tests/test_ops_exposure_status.py`
- `tests/test_cli.py`
- `.planning/phases/60-server-evidence-and-pilot-resume-packet/60-CONTEXT.md`
- `.planning/phases/60-server-evidence-and-pilot-resume-packet/60-01-PLAN.md`
- `.planning/phases/60-server-evidence-and-pilot-resume-packet/60-01-SUMMARY.md`
- `.planning/phases/60-server-evidence-and-pilot-resume-packet/60-VERIFICATION.md`

## Residual Notes

The live pilot has entry capacity under the widened caps, but strategy/paper
evidence is still not strong enough to mark the resume packet eligible. The
system can continue running the operator-started live pilot while the
confirmation-gated resume workflow remains blocked for future formal resume
applications.
