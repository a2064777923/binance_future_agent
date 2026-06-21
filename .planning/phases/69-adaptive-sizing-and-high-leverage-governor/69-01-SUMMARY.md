---
phase: 69-adaptive-sizing-and-high-leverage-governor
plan: 01
subsystem: execution-risk
tags: [adaptive-sizing, high-leverage, manual-margin, risk-governor, live-pilot]

requires:
  - phase: 67-adaptive-hot-symbol-breadth-and-guarded-queue
    provides: broad candidate queue and manual-symbol exclusion before ranking
  - phase: 68-multi-factor-edge-and-point-precision
    provides: deterministic factor_summary and price_basis diagnostics
provides:
  - adaptive sizing governor diagnostics attached to setup and candidate evaluations
  - pre-AI deterministic notional scaling and blocking
  - high-leverage stop/liquidation/volatility/liquidity guards
  - manual-position margin pressure accounting without bot slot ownership
  - risk-profile preview keys for governor settings
affects: [phase-70-server-canary]

tech-stack:
  added: []
  patterns:
    - deterministic risk authority before AI overlay
    - additive diagnostics under price_basis.adaptive_sizing_governor
    - manual exposure counts as collateral pressure but not bot-managed capacity

key-files:
  created:
    - .planning/phases/69-adaptive-sizing-and-high-leverage-governor/69-01-SUMMARY.md
    - .planning/phases/69-adaptive-sizing-and-high-leverage-governor/69-VERIFICATION.md
  modified:
    - .env.example
    - deploy/server-env.example
    - src/bfa/config.py
    - src/bfa/execution/models.py
    - src/bfa/execution/risk.py
    - src/bfa/execution/sizing.py
    - src/bfa/agent.py
    - src/bfa/ops/exposure_status.py
    - src/bfa/ops/risk_profile.py
    - tests/test_agent_runner.py
    - tests/test_execution_sizing.py
    - tests/test_ops_exposure_status.py
    - tests/test_ops_risk_profile.py

key-decisions:
  - "Sizing governor runs before AI; AI can echo or veto the deterministic plan but cannot increase it."
  - "Manual symbols such as BTWUSDT remain excluded from bot entry count and bot exit actions, while their margin pressure still reduces capacity."
  - "Hard caps come from configured notional caps, stop-risk caps, available balance, and remaining portfolio margin."
  - "Live server cap widening during this phase is recorded as an operator/env action, not as a local default."

patterns-established:
  - "AdaptiveSizingGovernorResult emits schema bfa_adaptive_sizing_governor_v1."
  - "RiskState separates active_exposures from manual_exposures and exposes total_initial_margin_usdt."
  - "Exposure-status reports manual_initial_margin_usdt and total_initial_margin_usdt."
  - "Risk profiles include governor knobs so future raises stay previewable and token-gated."

requirements-completed: [SIZE-01, SIZE-02, SIZE-03, SIZE-04]

duration: 36 min
completed: 2026-06-21
status: complete
---

# Phase 69 Plan 01: Adaptive Sizing And High-Leverage Governor Summary

**The live-entry path now has a deterministic adaptive sizing governor before AI review, with high-leverage safety checks and manual-margin accounting.**

## Performance

- **Duration:** 36 min
- **Started:** 2026-06-21T01:51:00Z
- **Completed:** 2026-06-21T02:28:02Z
- **Tasks:** 4/4
- **Files modified:** 15

## Accomplishments

- Added `AdaptiveSizingGovernorResult` and `apply_adaptive_sizing_governor`, which compute a final notional from signal quality, liquidity, volatility, stop/liquidation geometry, manual margin pressure, and forward-paper guard evidence.
- Wired the governor into the candidate queue before trade setup persistence and before AI, so rejected or downsized setups are visible in `candidate_evaluations` and `price_basis.adaptive_sizing_governor`.
- Added hard-cap calculations from max position notional, effective notional, stop-risk notional, account available balance, and remaining portfolio margin.
- Extended `RiskState` with manual exposures and account balances, then updated execution risk and exposure-status reports to count manual margin pressure without counting manual symbols as bot-owned positions.
- Added governor env keys to config defaults, examples, numeric validation, and approved risk-profile previews.
- Added tests for strong setup scale-up, weak/manual-pressure downsize, no weak-signal upsize, high-leverage geometry blocking, agent diagnostics, manual-margin capacity blocking, and risk-profile preview inclusion.

## Live Env Note

During Phase 69 the isolated server env was widened by operator request with `BTWUSDT` marked manual. The local code does not bake those temporary server caps into defaults. Phase 70 owns deployment and canary verification of the new code against the current server env.

## Decisions Made

- Strong deterministic setups may scale up only inside hard caps and only when the signal-quality component permits expansion.
- Weak setups may be downsized but not enlarged just because more account capacity exists.
- Manual positions remain operator-owned. They are excluded from bot-managed position count, candidate selection, and exit planning, but their initial margin can block new bot entries.
- High-leverage setups fail closed when stop distance is too tight, stop/liquidation geometry is unsafe, liquidity is insufficient, or volatility crosses configured block thresholds.

## Deviations from Plan

The server cap widening was performed as a live env adjustment responding to operator direction while local Phase 69 work continued. It did not change local defaults and does not replace Phase 70 deployment/canary proof.

**Total deviations:** 1 documented operator env action.
**Impact on plan:** Phase 70 must verify the deployed code against the current live server state and ensure `BTWUSDT` remains manual.

## Issues Encountered

- `gsd-tools phase.complete` marked top-level Phase 69 state but left plan detail counts stale. The phase docs and roadmap/state fields were corrected during closeout.

## User Setup Required

None for local Phase 69. Phase 70 will need server deployment/canary checks and should preserve the current `BTWUSDT` manual boundary.

## Next Phase Readiness

Phase 70 can deploy the completed v1.27 local changes to `/opt/binance-futures-agent`, verify timers/services, produce a current server packet, and prove manual-symbol boundaries under live conditions.

---
*Phase: 69-adaptive-sizing-and-high-leverage-governor*
*Completed: 2026-06-21*
