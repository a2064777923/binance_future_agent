---
phase: 60
name: Server Evidence And Pilot Resume Packet
verified: 2026-06-21
status: passed
---

# Phase 60 Verification

## Local Verification

- `python -m unittest tests.test_ops_risk_profile tests.test_ops_live_resume_plan tests.test_ops_exposure_status tests.test_cli`
  - Result: passed, 68 tests.
- `python -m unittest discover -s tests`
  - Result: passed, 386 tests.

## Server Verification

Server path: `/opt/binance-futures-agent/app`.

- Deployed updated risk profile and matching tests while live/paper timers were
  paused and both services were inactive.
- Server focused:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest tests.test_ops_risk_profile tests.test_ops_live_resume_plan tests.test_ops_exposure_status tests.test_cli`
  - Result: passed, 68 tests.
- Server full:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest discover -s tests`
  - Result: passed, 386 tests.

## Server Runtime Evidence

Current server readback after cap widening:

- `binance-futures-agent-live.timer=active`
- `binance-futures-agent-live.service=inactive`
- `binance-futures-agent-paper.timer=active`
- `binance-futures-agent-paper.service=inactive`

Current non-secret live cap readback:

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

## Generated Artifacts

- `runtime/phase60-operator-decision.json`
  - `schema=bfa_operator_resume_decision_v1`
  - `status=resolve_exposure`
  - `eligible_for_operator_resume=false`
- `runtime/phase60-live-resume-plan.json`
  - `schema=bfa_live_resume_plan_v1`
  - `status=resume_apply_blocked`
  - `resume_allowed=false`
  - `applies_changes=false`
  - risk boundaries include 6 max positions, 60 USDT per-position notional,
    360 USDT portfolio notional, and 300 USDT same-direction notional.
- `runtime/phase60-exposure-status.json`
  - `status=current_profile_entry_capacity_available`
- `runtime/phase60-position-review.json`
  - `status=review_required`
  - `NEARUSDT`: `close_review`, `hold_time_expired`
  - `BTWUSDT`: `manual_hold`, `manual_position_ignored`
- `runtime/phase60-position-adjustment-plan.json`
  - `status=adjustment_plan_ready`
- `runtime/phase60-time-exit-plan.json`
  - `status=exit_plan_blocked`
  - `position_exit_preconditions_failed`
- `runtime/phase60-near-trade-trace.json`
  - `status=trace_ready`
- `runtime/phase60-post-cap-state.json`
  - Captures final systemd state and non-secret env caps.

## Mutation Check

The phase did write server env risk caps after operator instruction and synced
repository files into `/opt/binance-futures-agent/app`. It did not run
`live-resume-apply`, `position-adjustment-execute`, `time-exit-execute`, or any
command that places/cancels Binance orders.

No file under `F:\stock` was touched.
