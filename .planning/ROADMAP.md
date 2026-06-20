# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Milestones

- ✅ **v1.0 Dry-Run Binance Futures Agent** — Phases 1-8, shipped 2026-06-19
  ([archive](milestones/v1.0-ROADMAP.md)).
- ✅ **v1.21 Live Pilot Risk Controls** — Phases 9-29, shipped 2026-06-20
  ([archive](milestones/v1.21-ROADMAP.md)).
- ◆ **v1.22 Portfolio Risk And Multi-Position** — Phases 30-38, active.

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

**Status:** Complete and deployed.

**Plans:** 1 plan

**Success Criteria:**

1. Partial take-profit quantities are rounded down to symbol step size.
2. Partial take-profit plans are blocked when min quantity or min notional would
   fail.
3. Full-close plans require exact step alignment before confirmed execution.
4. Confirmed adjustment execution requires exchange filters.
5. Full local test suite passes.

### Phase 34: Deterministic Quant Setup And Trade Trace

**Goal:** Move point selection and sizing from AI-owned output into a
deterministic multi-factor setup layer, and make submitted trade decisions
auditable end-to-end.

**Requirements:** QSE-01, QSE-02, QSE-03, QSE-04, QSE-05

**Status:** Complete and deployed.

**Plans:** 1 plan

**Success Criteria:**

1. Setup scoring includes deterministic factor evidence for momentum,
   liquidity, open interest, taker flow, funding, volatility, narrative quality,
   and pilot tradability.
2. Setup generation outputs side, entry, stop, target, notional, hold time,
   confidence, reasons, and warnings before AI is consulted.
3. AI accepted trade responses must echo the setup side, prices, notional, and
   hold time exactly, or be rejected.
4. New agent cycles persist `trade_setups` before AI evaluation.
5. `ops trade-trace` reconstructs candidate, setup/legacy AI, risk/order
   intent, and exchange evidence without mutating exchange state.
6. Full local and server test suites pass.

### Phase 35: Quant Setup Backtest Calibration

**Goal:** Make the deterministic setup layer backtestable through staged
sweeps and hot-symbol matrix reporting.

**Requirements:** QBT-01, QBT-02, QBT-03

**Status:** Complete locally.

**Plans:** 1 plan

**Success Criteria:**

1. `quant_setup` is available as a built-in backtest variant.
2. Setup-driven backtests use completed kline windows to call the same
   deterministic setup logic used by the live runner.
3. Long and short setup-driven trades simulate stop loss, take profit, time
   exit, fees, and slippage.
4. CLI `backtest run`, `backtest sweep`, and matrix reporting accept
   `quant_setup`.
5. Full local test suite passes.

### Phase 36: Indicator-Based Setup Point Logic

**Goal:** Make deterministic setup scoring and point selection more explicitly
quantitative by adding shared market indicators, market-structure price bases,
and trace-visible stop/target rationale.

**Requirements:** QSI-01, QSI-02, QSI-03, QSI-04

**Status:** Complete locally.

**Plans:** 1 plan

**Success Criteria:**

1. Live feature extraction and `quant_setup` backtests use a shared indicator
   snapshot for ATR, VWAP, EMA spread, RSI, support, resistance, momentum, and
   volume impulse where kline data is available.
2. Deterministic setup scoring includes trend structure, RSI regime, and
   volume impulse factors in addition to the existing market/narrative factors.
3. Entry, stop, and target output includes a `price_basis` object explaining
   whether stop/target distances came from ATR/volatility or market structure.
4. AI context and `ops trade-trace` expose indicator features and `price_basis`
   without giving AI authority to rewrite deterministic setup prices.
5. Focused and full local test suites pass.

### Phase 37: Strategy Promotion Gate

**Goal:** Convert recent matrix backtest evidence into a read-only gate that
prevents live resume or risk-profile promotion when the selected strategy fails
pilot profitability and drawdown checks.

**Requirements:** SPG-01, SPG-02, SPG-03, SPG-04

**Status:** Complete locally.

**Plans:** 1 plan

**Success Criteria:**

1. Operators can run `ops strategy-promotion-check --matrix-report ...` against
   a backtest matrix JSON file.
2. The gate rejects missing/invalid reports and variants that are not promoted
   by the matrix summary.
3. The gate rejects variants with non-positive total PnL or worst drawdown at
   or above the pilot drawdown cap.
4. The gate checks every interval cell for verdict, trade count, PnL,
   positive-window-rate, and drawdown.
5. The Phase 36 `quant_setup` matrix report is checked and returns
   `keep_live_paused`.
6. Full local test suite passes.

### Phase 38: Quant Setup Calibration Variants

**Goal:** Add explicit offline setup profiles and calibrated quant variants so
recent matrix testing can compare baseline, selective, and scalp versions
without changing live defaults.

**Requirements:** QSC-01, QSC-02, QSC-03, QSC-04

**Status:** Complete locally; latest matrix still fails total promotion.

**Plans:** 1 plan

**Success Criteria:**

1. `build_trade_setup` accepts an optional profile while preserving the
   standard default used by live code.
2. Profiles can gate trades by edge, confidence, risk/reward, indicator sample
   coverage, trend alignment, RSI extremes, stop distance, and notional
   fraction.
3. Built-in backtest variants include `quant_setup_selective` and
   `quant_setup_scalp`.
4. CLI and matrix commands accept the new variants.
5. Recent matrix testing compares baseline, selective, and scalp variants.
6. Promotion checks show whether any variant is ready; failed checks keep live
   paused.
7. Full local test suite passes.

## Progress

| Milestone | Phases | Plans Complete | Status | Shipped |
|-----------|--------|----------------|--------|---------|
| v1.0 Dry-Run Binance Futures Agent | 1-8 | 28/28 | Complete | 2026-06-19 |
| v1.21 Live Pilot Risk Controls | 9-29 | 21/21 | Complete | 2026-06-20 |
| v1.22 Portfolio Risk And Multi-Position | 30-38 | 9/9 | Phase 38 local | Pending |

## Requirement Coverage

- v1.0 requirements: archived at `.planning/milestones/v1.0-REQUIREMENTS.md`
- v1.1-v1.21 requirements: archived at `.planning/milestones/v1.21-REQUIREMENTS.md`
- v1.22 requirements: active at `.planning/REQUIREMENTS.md`

## Next Step

Keep live automation paused while the latest calibrated `quant_setup` matrix
still fails total `ops strategy-promotion-check`. The `quant_setup_selective`
variant is promising on `5m` but fails `15m`; next work should add
interval-aware promotion or further 15m filtering before restoring live
automation. Monitor `SOLUSDT` through filter-aware `ops position-adjustment-plan`
and use `ops trade-trace --symbol SOLUSDT` for decision-chain review. Do not
execute adjustment orders, restore the live timer, or apply
`30u_10x_multi_dynamic` without an explicit confirmation token.
