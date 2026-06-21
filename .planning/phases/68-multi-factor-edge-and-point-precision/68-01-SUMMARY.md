---
phase: 68-multi-factor-edge-and-point-precision
plan: 01
subsystem: strategy-explainability
tags: [multi-factor, setup-geometry, ai-context, live-trace, guard-feedback]

requires:
  - phase: 66-live-cycle-explainability-and-ledger-cadence
    provides: live-cycle and trade-trace explainability surfaces
  - phase: 67-adaptive-hot-symbol-breadth-and-guarded-queue
    provides: broad candidate queue and candidate_evaluations diagnostics
provides:
  - grouped deterministic factor summaries before AI review
  - open-interest change feature extraction and compact AI context exposure
  - structure-based entry, stop, target, sizing, min-notional, and liquidation diagnostics
  - candidate/live-cycle/trade-trace setup diagnostics
  - recommendation-only recency and decay metadata for live and paper guard feedback
affects: [phase-69-sizing, phase-70-server-canary]

tech-stack:
  added: []
  patterns:
    - setup payload enrichment through TradeSetup.to_dict()
    - compact downstream trace forwarding
    - recommendation-only guard recency scoring

key-files:
  created:
    - .planning/phases/68-multi-factor-edge-and-point-precision/68-01-SUMMARY.md
    - .planning/phases/68-multi-factor-edge-and-point-precision/68-VERIFICATION.md
  modified:
    - src/bfa/strategy/setup.py
    - src/bfa/strategy/features.py
    - src/bfa/ai/schema.py
    - src/bfa/agent.py
    - src/bfa/ops/live_cycle_explainability.py
    - src/bfa/ops/trade_trace.py
    - src/bfa/ops/live_outcome_ledger.py
    - src/bfa/strategy/paper_guard.py
    - tests/test_strategy_setup.py
    - tests/test_strategy_features.py
    - tests/test_ai_schema.py
    - tests/test_agent_runner.py
    - tests/test_ops_live_cycle_explainability.py
    - tests/test_ops_live_outcome_ledger.py
    - tests/test_strategy_paper_guard.py
    - tests/test_cli.py

key-decisions:
  - "TradeSetup remains the deterministic authority; AI receives richer compact evidence but no bypass path."
  - "Point diagnostics are attached to existing price_basis instead of creating a parallel trace system."
  - "Live and paper guard recency/decay fields are recommendation-only and do not raise risk."
  - "No server deploy, live env mutation, leverage increase, position-cap increase, or manual-symbol management was performed."

patterns-established:
  - "FactorScore.to_dict() now carries group and polarity while preserving existing names/scores."
  - "TradeSetup.to_dict() carries factor_summary and price_basis.sizing_diagnostics for candidate, AI, and ops consumers."
  - "Outcome guard groups include latest/recent/decay fields with applies_changes=false and raises_risk=false."

requirements-completed: [EDGE-01, EDGE-02, EDGE-03, EDGE-04]

duration: 28 min
completed: 2026-06-21
status: complete
---

# Phase 68 Plan 01: Multi-Factor Edge And Point Precision Summary

**The deterministic setup path now emits an auditable multi-factor and point-geometry proposal before AI review, without changing live caps or server state.**

## Performance

- **Duration:** 28 min
- **Started:** 2026-06-21T01:21:00Z
- **Completed:** 2026-06-21T01:49:13Z
- **Tasks:** 8/8
- **Files modified:** 18

## Accomplishments

- Added factor grouping, directional polarity, threshold checks, coverage ratio, missing-input lists, and top-factor summaries to deterministic setup payloads.
- Added open-interest change extraction and exposed it in candidate features and compact AI context.
- Expanded `price_basis` with raw/profile/capped stop and target distances, risk/reward, sizing diagnostics, exchange filters, min-notional pressure, stop-risk, and conservative liquidation-distance diagnostics.
- Forwarded compact setup diagnostics through `candidate_evaluations`, AI context, live-cycle explainability, and trade-trace decision flow.
- Added recency/decay fields to live outcome ledger feedback and forward-paper guard block stats while preserving `applies_changes=false` and `raises_risk=false`.

## Task Commits

1. **Tasks 1-7: Factor summaries, point diagnostics, OI change, trace forwarding, guard recency/decay, and tests** - `ee47cab` (`feat`)

**Plan metadata:** created by `6c4465c`.

## Files Created/Modified

- `src/bfa/strategy/setup.py` - Adds factor summaries, group/polarity fields, OI-change scoring, raw/capped geometry diagnostics, sizing diagnostics, and conservative liquidation-distance diagnostics.
- `src/bfa/strategy/features.py` - Tracks `open_interest_change_percent` from consecutive OI snapshots.
- `src/bfa/ai/schema.py` - Adds OI change and factor summary to compact AI context.
- `src/bfa/agent.py` - Includes factor and price diagnostics in candidate evaluation setup payloads.
- `src/bfa/ops/live_cycle_explainability.py` - Includes compact setup factor summary in live-cycle reports.
- `src/bfa/ops/trade_trace.py` - Includes factor summary in quant setup decision flow.
- `src/bfa/ops/live_outcome_ledger.py` - Adds latest/recent/decay/sample-sufficiency guard feedback fields.
- `src/bfa/strategy/paper_guard.py` - Adds decay metadata to paper guard summaries and block stats.
- Tests listed in frontmatter - Cover new payload shape, OI change, AI context, candidate diagnostics, live-cycle/trade-trace summaries, and guard recency/decay.

## Decisions Made

- `factor_scores` stayed backward-compatible; new `group` and `polarity` fields are additive.
- `price_basis` remains the single setup-geometry diagnostics block for AI, persistence, and ops reports.
- Liquidation diagnostics use a conservative inverse-leverage approximation and do not attempt high-leverage optimization in this phase.
- Outcome feedback remains advisory or risk-reducing only. It does not promote size, leverage, concurrency, or risk caps.

## Deviations from Plan

None. Phase 68 stayed local and did not deploy to the server, edit `/etc/binance-futures-agent/env`, place orders, change systemd state, or manage `BTWUSDT`.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope creep; Phase 69 still owns adaptive sizing and high-leverage governor behavior.

## Issues Encountered

- One new small-notional test initially used a risk cap so low that min executable notional correctly exceeded risk-sized notional. The fixture was adjusted to target the intended "raised to min executable" branch.

## User Setup Required

None.

## Next Phase Readiness

Phase 69 can now use the richer deterministic `factor_summary` and `price_basis.sizing_diagnostics` to build adaptive sizing and high-leverage controls. Phase 70 still owns server canary deployment and manual-boundary proof.

---
*Phase: 68-multi-factor-edge-and-point-precision*
*Completed: 2026-06-21*
