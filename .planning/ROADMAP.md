# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Milestones

- ✅ **v1.0 Dry-Run Binance Futures Agent** — Phases 1-8, shipped 2026-06-19
  ([archive](milestones/v1.0-ROADMAP.md)).

- ✅ **v1.21 Live Pilot Risk Controls** — Phases 9-29, shipped 2026-06-20
  ([archive](milestones/v1.21-ROADMAP.md)).

- ✅ **v1.22 Portfolio Risk And Multi-Position** — Phases 30-47, shipped 2026-06-20
  ([archive](milestones/v1.22-ROADMAP.md)).

## Phases

<details>
<summary>✅ v1.0 Dry-Run Binance Futures Agent (Phases 1-8) — SHIPPED 2026-06-19</summary>

- [x] Phase 1: Isolated Project Foundation (4/4 plans)
- [x] Phase 2: Binance Futures Market Data Layer (5/5 plans)
- [x] Phase 3: Narrative And Hot-Coin Collection Layer (3/3 plans)
- [x] Phase 4: Event Store And Replay Foundation (3/3 plans)
- [x] Phase 5: Hot-Coin Candidate Strategy (2/2 plans)
- [x] Phase 6: OpenAI Decision Layer (3/3 plans)
- [x] Phase 7: Risk-Gated Binance Execution (4/4 plans)
- [x] Phase 8: Isolated Server Deployment (4/4 plans)

</details>

<details>
<summary>✅ v1.21 Live Pilot Risk Controls (Phases 9-29) — SHIPPED 2026-06-20</summary>

- [x] Phase 9: Live Activation Readiness (1/1 plan)
- [x] Phase 10: Small-Capital Backtest Calibration (1/1 plan)
- [x] Phase 11: AI Decision Robustness (1/1 plan)
- [x] Phase 12: Pilot Tradability Filter (1/1 plan)
- [x] Phase 13: Pilot Symbol Universe (1/1 plan)
- [x] Phase 14: Margin Setup Fail-Closed (1/1 plan)
- [x] Phase 15: Configurable Margin Mode (1/1 plan)
- [x] Phase 16: Position Mode And Entry Fail-Closed (1/1 plan)
- [x] Phase 17: Balance Preflight Gate (1/1 plan)
- [x] Phase 18: DeepSeek Provider Switch (1/1 plan)
- [x] Phase 19: 30U Higher-Leverage Trial Profile (1/1 plan)
- [x] Phase 20: Timer Resume Gate (1/1 plan)
- [x] Phase 21: Closed Trade Outcome Reconciliation (1/1 plan)
- [x] Phase 22: Risk Change Readiness Gate (1/1 plan)
- [x] Phase 23: Closed Outcome Risk Change Strictness (1/1 plan)
- [x] Phase 24: Outcome Reconciliation Sweep (1/1 plan)
- [x] Phase 25: Position Hold-Time Check (1/1 plan)
- [x] Phase 26: Time Exit Plan (1/1 plan)
- [x] Phase 27: Operator-Approved Time Exit Execution (1/1 plan)
- [x] Phase 28: Dynamic Sizing And Multi-Position Guard (1/1 plan)
- [x] Phase 29: Confirmation-Gated Risk Profile Switch (1/1 plan)

</details>

<details>
<summary>✅ v1.22 Portfolio Risk And Multi-Position (Phases 30-47) — SHIPPED 2026-06-20</summary>

- [x] Phase 30: Portfolio Risk And Multi-Position Profile (1/1 plan)
- [x] Phase 31: Active Position Review (1/1 plan)
- [x] Phase 32: Active Position Adjustment Plan (1/1 plan)
- [x] Phase 33: Filter-Aware Position Adjustments (1/1 plan)
- [x] Phase 34: Deterministic Quant Setup And Trade Trace (1/1 plan)
- [x] Phase 35: Quant Setup Backtest Calibration (1/1 plan)
- [x] Phase 36: Indicator-Based Setup Point Logic (1/1 plan)
- [x] Phase 37: Strategy Promotion Gate (1/1 plan)
- [x] Phase 38: Quant Setup Calibration Variants (1/1 plan)
- [x] Phase 39: Interval-Aware Forward Paper Gate (1/1 plan)
- [x] Phase 40: Forward-Paper Evidence Recorder (1/1 plan)
- [x] Phase 41: Forward-Paper Scheduling Assets (1/1 plan)
- [x] Phase 42: Forward-Paper Performance Gate (1/1 plan)
- [x] Phase 43: Forward-Paper Loss Attribution And Recalibration (1/1 plan)
- [x] Phase 44: Forward-Paper Guarded Setup Calibration (1/1 plan)
- [x] Phase 45: Live Auto-Hot Candidate Breadth (1/1 plan)
- [x] Phase 46: Live Auto-Hot Dry-Run Evidence (1/1 plan)
- [x] Phase 47: Forward-Paper Adaptive Candidate Guard (1/1 plan)

</details>

## Progress

| Milestone | Phases | Plans Complete | Status | Shipped |
|-----------|--------|----------------|--------|---------|
| v1.0 Dry-Run Binance Futures Agent | 1-8 | 28/28 | Complete | 2026-06-19 |
| v1.21 Live Pilot Risk Controls | 9-29 | 21/21 | Complete | 2026-06-20 |
| v1.22 Portfolio Risk And Multi-Position | 30-47 | 18/18 | Complete | 2026-06-20 |

## Requirement Coverage

- v1.0 requirements: archived at `.planning/milestones/v1.0-REQUIREMENTS.md`
- v1.1-v1.21 requirements: archived at `.planning/milestones/v1.21-REQUIREMENTS.md`
- v1.22 requirements: archived at `.planning/milestones/v1.22-REQUIREMENTS.md`

## Next Step

Start the next milestone with `$gsd-new-milestone`. Keep live automation paused
while calibrated `quant_setup` matrix evidence and forward-paper evidence remain
negative. The paper timer stays active for paper-only evidence collection, live
auto-hot remains disabled in server env, and live service/timer remain inactive.
