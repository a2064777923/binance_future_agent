# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Milestones

- ✅ **v1.0 Dry-Run Binance Futures Agent** — Phases 1-8, shipped 2026-06-19
  ([archive](milestones/v1.0-ROADMAP.md)).
- ✅ **v1.21 Live Pilot Risk Controls** — Phases 9-29, shipped 2026-06-20
  ([archive](milestones/v1.21-ROADMAP.md)).
- ◆ **v1.22 Portfolio Risk And Multi-Position** — Phases 30-33, active.

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

### Phase 30: Portfolio Risk And Multi-Position Profile

**Goal:** Allow the agent to keep scanning and accept controlled additional
positions while another position is open, with higher-leverage profiles bounded
by portfolio-level risk budgets.

**Requirements:** PRM-01, PRM-02, PRM-03, PRM-04, PRM-05, HLP-01, HLP-02,
HLP-03, HLP-04, QSR-01

**Status:** Complete locally. Server deployment and live env switching remain
separate operator-gated actions.

**Plans:** 1 plan

**Success Criteria:**

1. Existing active positions do not force the live runner to early-stop when
   multi-position mode is enabled and capacity remains.
2. The live runner can continue from a retryable first-candidate skip to the
   next top-N hot symbol while still submitting at most one order per cycle.
3. New order intents are rejected when portfolio margin, portfolio margin
   fraction, portfolio notional, same-direction notional, max-position count,
   or duplicate symbol-direction caps would be exceeded.
4. A `30u_10x_multi_dynamic` profile can be previewed with confirmation token
   and portfolio caps.
5. Risk-profile readiness can carry protected active exposure into the target
   profile only when active exposure fits target caps.
6. `ops exposure-status` reports portfolio budget context.
7. Full local test suite passes.

### Phase 31: Active Position Review

**Goal:** Add a read-only active-position review layer that turns exchange
positions and submitted trade plans into deterministic hold/watch/trail/close
recommendations.

**Requirements:** APR-01, APR-02, APR-03

**Status:** Complete locally and deployed; read-only server preview verified.

**Plans:** 1 plan

**Success Criteria:**

1. `ops position-review` produces read-only recommendations for active
   positions without placing or modifying orders.
2. Review output includes PnL percent, R-multiple, target progress, hold-time
   progress, protection count, and matching submitted intent.
3. Unprotected, missing-plan, overdue, or near-stop positions produce
   `close_review`; near-target or >=1R positions produce `trail_or_reduce`.
4. Full local test suite passes.

### Phase 32: Active Position Adjustment Plan

**Goal:** Convert active-position review recommendations into deterministic
partial take-profit or full-close plans, and expose confirmation-gated execution
for live reduce orders.

**Requirements:** APR-04

**Status:** Complete and deployed.

**Plans:** 1 plan

**Success Criteria:**

1. `ops position-adjustment-plan` is read-only and maps `trail_or_reduce` to a
   partial take-profit plan.
2. `ops position-adjustment-plan` maps overdue or unsafe `close_review`
   positions to a full-close plan.
3. `ops position-adjustment-execute` refuses live mutation without the exact
   confirmation token and an inactive live service.
4. The automated live runner includes active-position review and adjustment
   plan summaries in each live cycle result before scanning new entries.
5. Full local test suite passes.

### Phase 33: Filter-Aware Position Adjustments

**Goal:** Ensure active-position adjustment plans only expose executable reduce
orders whose quantities satisfy Binance step-size, minimum-quantity, and
minimum-notional constraints.

**Requirements:** APR-05

**Status:** Local verification passed; server deployment pending.

**Plans:** 1 plan

**Success Criteria:**

1. Partial take-profit quantities are rounded down to symbol step size.
2. Partial take-profit plans are blocked when min quantity or min notional would
   fail.
3. Full-close plans require exact step alignment before confirmed execution.
4. Confirmed adjustment execution requires exchange filters.
5. Full local test suite passes.

## Progress

| Milestone | Phases | Plans Complete | Status | Shipped |
|-----------|--------|----------------|--------|---------|
| v1.0 Dry-Run Binance Futures Agent | 1-8 | 28/28 | Complete | 2026-06-19 |
| v1.21 Live Pilot Risk Controls | 9-29 | 21/21 | Complete | 2026-06-20 |
| v1.22 Portfolio Risk And Multi-Position | 30-33 | 4/4 | Phase 33 server deploy pending | Pending |

## Requirement Coverage

- v1.0 requirements: archived at `.planning/milestones/v1.0-REQUIREMENTS.md`
- v1.1-v1.21 requirements: archived at `.planning/milestones/v1.21-REQUIREMENTS.md`
- v1.22 requirements: active at `.planning/REQUIREMENTS.md`

## Next Step

Deploy Phase 33 to the isolated server and preview filter-aware
`ops position-adjustment-plan`. Do not execute adjustment orders or apply
`30u_10x_multi_dynamic` without an explicit confirmation token.
