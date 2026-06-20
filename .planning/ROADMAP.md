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

- ◆ **v1.23 Strategy Evidence And Live Resume Readiness** — Phases 48-52,
  active.

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

### Phase 48: Strategy Evidence Baseline

**Goal:** Produce one compact read-only baseline that shows why live resume is
currently blocked and what evidence must improve.

**Requirements:** EVB-01, EVB-02, EVB-03, EVB-04

**Status:** Not started.

**Plans:** 1 plan

**Success Criteria:**

1. Operator can generate a compact evidence report covering forward-paper
   performance, latest outcomes, loss attribution, adaptive guard output, and
   server timer state.
2. Report includes clear `live_resume_allowed=false` reasons grouped by
   strategy evidence, server state, exchange/manual exposure, and missing
   confirmation.
3. Report is read-only and does not mutate services, env, exchange state, or
   event-store trading artifacts.
4. Focused and full local tests pass.

### Phase 49: Loss-Driven Setup Recalibration

**Goal:** Convert current paper loss attribution into stricter deterministic
setup profiles and point geometry without changing live defaults.

**Requirements:** SRC-01, SRC-02, SRC-03, SRC-04

**Depends on:** Phase 48

**Status:** Not started.

**Plans:** 1 plan

**Success Criteria:**

1. New paper/backtest setup variant can penalize or block worst symbols, sides,
   setup reasons, factor reasons, and factor names from attribution.
2. Stop/target geometry can tighten using ATR, market structure, VWAP, and
   observed stop-loss/time-exit loss patterns.
3. Missing open-interest, thin liquidity, weak RSI/trend/momentum, and losing
   taker-flow/volume-impulse regimes are represented in setup scoring.
4. Live default profile remains unchanged until promotion gates pass.

### Phase 50: Multi-Window Hot-Symbol Backtest Matrix

**Goal:** Re-run hot-symbol strategy evidence across multiple recent windows,
intervals, and setup variants to avoid overfitting to one selected interval.

**Requirements:** BFP-01, BFP-02

**Depends on:** Phase 49

**Status:** Not started.

**Plans:** 1 plan

**Success Criteria:**

1. Matrix command/report covers at least `5m` and `15m`, multiple recent
   hot-symbol universes, and baseline plus recalibrated setup variants.
2. Each variant/interval cell reports trade count, total net PnL, win rate,
   positive-window rate, profit factor, and worst drawdown.
3. Promotion verdicts remain fail-closed when evidence is missing, thin, or
   negative.
4. Full local tests and a reproducible matrix smoke pass.

### Phase 51: Post-Change Forward-Paper Gate

**Goal:** Evaluate new forward-paper evidence separately from older losing
samples so live readiness is based on the current calibrated strategy.

**Requirements:** BFP-03, BFP-04

**Depends on:** Phase 50

**Status:** Not started.

**Plans:** 1 plan

**Success Criteria:**

1. Forward-paper performance check can evaluate only outcomes opened after a
   selected calibration timestamp or variant switch.
2. Gate requires minimum outcomes, positive net PnL, minimum win rate, minimum
   profit factor, and max drawdown before any paper promotion.
3. Gate keeps `live_resume_allowed=false` until both matrix and post-change
   forward-paper evidence pass.
4. Server paper timer can keep collecting evidence without creating order
   intents or restoring live automation.

### Phase 52: Live Resume Readiness Report

**Goal:** Build a single read-only live-resume report that combines strategy
evidence, paper evidence, server state, exchange state, profile state, and
operator confirmation requirements.

**Requirements:** LRR-01, LRR-02, LRR-03, LRR-04

**Depends on:** Phase 51

**Status:** Not started.

**Plans:** 1 plan

**Success Criteria:**

1. Operator can run one command to see whether live resume is blocked by
   strategy, paper evidence, server timers, exchange state, manual exposure,
   risk profile, or missing confirmation.
2. Manual exchange positions are reported separately from agent-managed
   submitted intents and never counted as strategy success.
3. Live auto-hot can be previewed through dry-run/read-only evidence while
   remaining disabled by default in server env.
4. Report cannot apply risk profiles, restore timers, submit orders, or modify
   exchange state.

## Progress

| Milestone | Phases | Plans Complete | Status | Shipped |
|-----------|--------|----------------|--------|---------|
| v1.0 Dry-Run Binance Futures Agent | 1-8 | 28/28 | Complete | 2026-06-19 |
| v1.21 Live Pilot Risk Controls | 9-29 | 21/21 | Complete | 2026-06-20 |
| v1.22 Portfolio Risk And Multi-Position | 30-47 | 18/18 | Complete | 2026-06-20 |
| v1.23 Strategy Evidence And Live Resume Readiness | 48-52 | 0/5 | Planning | - |

## Requirement Coverage

- v1.0 requirements: archived at `.planning/milestones/v1.0-REQUIREMENTS.md`
- v1.1-v1.21 requirements: archived at `.planning/milestones/v1.21-REQUIREMENTS.md`
- v1.22 requirements: archived at `.planning/milestones/v1.22-REQUIREMENTS.md`
- v1.23 requirements: active at `.planning/REQUIREMENTS.md`

## Next Step

Start Phase 48 with `$gsd-plan-phase 48`. Keep live automation paused while
strategy matrix evidence and forward-paper evidence remain negative. The paper
timer stays active for paper-only evidence collection; live auto-hot and live
service/timer remain disabled until explicit readiness gates pass.
