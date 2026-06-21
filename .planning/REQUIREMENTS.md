# Requirements: Binance Futures Agent v1.27

**Defined:** 2026-06-21
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## v1.27 Requirements

### Live Cycle Explainability

- [x] **OPS-03**: Operator can inspect the latest live cycles and see every
  evaluated symbol, skip reason, factor score, AI decision, risk decision,
  sizing cap, and whether an order was submitted.

- [ ] **OPS-04**: Server can produce a compact current-status packet that
  includes live/paper timer state, open positions, open algo orders, manual
  symbols, cap utilization, latest outcomes, and latest trade/no-trade traces.

- [x] **LEARN-04**: Closed live outcome reconciliation and live ledger reporting
  can run on a scheduled or single-command path without placing orders,
  changing env files, or applying guard/risk changes.

### Adaptive Hot-Symbol Breadth

- [x] **SCAN-01**: Live hot-symbol selection can evaluate at least 80 current
  Binance USD-M USDT symbols while excluding manual symbols and symbols that
  fail exchange tradability or configured liquidity floors.

- [x] **SCAN-02**: Candidate selection records source health and factor inputs
  from Binance ticker, klines, open interest, funding, taker flow, and any
  available narrative/manual/social-export sources.

- [x] **SCAN-03**: Candidate queues avoid repeatedly spending cycles on symbols,
  sides, or factor patterns with recent weak live/paper evidence unless the
  operator explicitly resets or overrides the guard.

- [x] **SCAN-04**: A live cycle can continue evaluating later candidates after
  AI pass, setup pass, duplicate-exposure, or other retryable symbol-level
  skips while still respecting the configured one-order-per-cycle limit.

### Multi-Factor Edge And Point Precision

- [x] **EDGE-01**: Deterministic setup scoring combines trend/momentum, volume
  impulse, taker flow, open-interest change, funding, volatility/range, and
  liquidity/tradability factors before any AI overlay is requested.

- [x] **EDGE-02**: Entry, stop, and target points are derived from market
  structure and exchange filters, with explicit risk/reward, stop-distance,
  liquidation-distance, and min-notional diagnostics.

- [x] **EDGE-03**: Trade/no-trade traces explain the factor thresholds and point
  geometry that produced the final action, including why the position size was
  small when sizing caps or stop risk constrained it.

- [x] **EDGE-04**: Live/paper outcomes update recommendation-only factor guards
  with minimum-sample, recency, and decay rules so weak evidence can reduce
  exposure without silently promoting risk.

### Adaptive Sizing And Leverage Governor

- [ ] **SIZE-01**: Dynamic sizing can raise or lower per-trade notional within
  configured absolute caps using signal quality, stop distance, liquidity,
  volatility, available balance, and recent outcome health.

- [ ] **SIZE-02**: High-leverage entries are blocked or downsized when stop
  distance, liquidation distance, spread/slippage, or volatility makes the
  setup unsafe for the active small-capital pilot.

- [ ] **SIZE-03**: Portfolio risk checks include account-level available
  balance and manual-position margin pressure while continuing to exclude
  manual symbols from bot-managed position count and bot exit actions.

- [ ] **SIZE-04**: Any risk-cap or sizing-rule increase has a preview artifact,
  rollback path, and evidence gate; guard feedback can decrease risk but cannot
  increase risk without explicit operator approval.

### Server Canary And Manual Boundary

- [ ] **OPS-05**: Deployment and server verification for v1.27 remain isolated
  under `/opt/binance-futures-agent` and `/etc/binance-futures-agent`, restore
  live/paper timers after any deployment pause, and scan artifacts for
  sensitive fields.

- [ ] **RISK-05**: `BTWUSDT` and any configured manual symbols remain visible in
  packets and diagnostics but are excluded from bot entry capacity,
  auto-management, close/reduce execution, and candidate selection.

## v1.28+ Requirements

### Future Strategy Expansion

- **STRAT-06**: Add stable external social/news adapters only when collection
  access is allowed, measurable, and observable in source-health reports.

- **MODEL-02**: Add multi-regime strategy routing across breakout, trend,
  reversal, and no-trade modes after v1.27 traces prove factor quality.

- **SCALE-02**: Consider additional capital or higher leverage only after
  repeated positive live outcomes pass net-PnL, drawdown, profit-factor, and
  operator-review gates.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automatically managing `BTWUSDT` or other manual positions | Manual exposure remains operator-owned unless explicitly handed to the bot. |
| Increasing risk solely because capacity was widened | More slots and notional are capacity, not profitability evidence. |
| Letting AI bypass deterministic setup, sizing, or risk gates | AI remains overlay/veto; deterministic code keeps final authority. |
| Claiming Lana/Square/X-style profitability | Public claims remain inspiration only; local live/paper/backtest evidence decides promotion. |
| Unbounded multi-order live cycles | The pilot still needs a controlled one-order-per-cycle default until live evidence improves. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| OPS-03 | Phase 66 | Complete |
| OPS-04 | Phase 70 | Pending |
| LEARN-04 | Phase 66 | Complete |
| SCAN-01 | Phase 67 | Complete |
| SCAN-02 | Phase 67 | Complete |
| SCAN-03 | Phase 67 | Complete |
| SCAN-04 | Phase 67 | Complete |
| EDGE-01 | Phase 68 | Complete |
| EDGE-02 | Phase 68 | Complete |
| EDGE-03 | Phase 68 | Complete |
| EDGE-04 | Phase 68 | Complete |
| SIZE-01 | Phase 69 | Pending |
| SIZE-02 | Phase 69 | Pending |
| SIZE-03 | Phase 69 | Pending |
| SIZE-04 | Phase 69 | Pending |
| OPS-05 | Phase 70 | Pending |
| RISK-05 | Phase 70 | Pending |

**Coverage:**

- v1.27 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 after Phase 67 verification*
