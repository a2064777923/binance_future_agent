# Requirements: Binance Futures Agent v1.22 Portfolio Risk And Multi-Position

**Defined:** 2026-06-20
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## v1.22 Requirements

### Portfolio Risk

- [x] **PRM-01**: The live/dry-run risk gate accounts for current active
  portfolio notional and initial margin before accepting a new order intent.

- [x] **PRM-02**: Runtime config exposes total portfolio margin, margin
  fraction, total notional, and same-direction notional caps.

- [x] **PRM-03**: Multi-position mode can continue candidate collection and AI
  evaluation while an existing position is open, provided open-position count
  and portfolio caps leave capacity.

- [x] **PRM-04**: Same-symbol same-direction duplicate exposure remains blocked
  even when multi-position mode is enabled.

- [x] **PRM-05**: The live runner evaluates a top-N candidate queue so a
  retryable skip on the first hot symbol does not end the whole cycle.

### Higher-Leverage Profiles

- [x] **HLP-01**: A named `30u_10x_multi_dynamic` profile can be previewed with
  dynamic sizing, two concurrent positions, and explicit portfolio caps.

- [x] **HLP-02**: Existing risk-profile apply behavior remains
  confirmation-gated and writes only approved non-secret risk keys.

- [x] **HLP-03**: Exposure status reports portfolio cap context so operators can
  understand remaining capacity instead of only seeing position count.

- [x] **HLP-04**: Risk-profile readiness can allow carrying a protected active
  position into a target multi-position profile only when the target profile's
  portfolio caps can absorb the active exposure.

### Research Translation

- [x] **QSR-01**: Public Lana-style strategy claims are translated only into
  testable system behaviors, such as hot-coin scanning, active position review,
  staged exits, and portfolio-level risk control; unverified profit claims are
  not treated as evidence.

## Future Requirements

### Active Position Review

- [x] **APR-01**: Add a read-only active-position review command that re-scores
  open positions and recommends hold, watch, trail/reduce, or close-review
  actions before executing any change.

- [x] **APR-02**: Review output includes deterministic PnL percent,
  stop-risk R multiple, target progress, hold-time progress, protection count,
  and matching submitted-intent evidence.

- [x] **APR-03**: Review recommendations fail closed for unprotected,
  missing-plan, overdue, or near-stop positions, while near-target or >=1R
  positions are recommended for future trail/reduce handling.

- [x] **APR-04**: Add confirmation-gated active-position adjustment planning
  for live positions, including partial take-profit and full-close reduce
  orders derived from deterministic review recommendations.

- [x] **APR-05**: Active-position adjustment plans respect Binance symbol
  filters before exposing executable reduce orders, including step size,
  minimum quantity, and minimum notional checks.

### Quant Setup And Traceability

- [x] **QSE-01**: Entry, stop, target, hold-time, and notional generation come
  from a deterministic multi-factor setup layer before AI is consulted.

- [x] **QSE-02**: Setup scoring includes separate factor evidence for
  momentum, liquidity, open interest, taker flow, funding, volatility,
  narrative quality, and pilot tradability.

- [x] **QSE-03**: AI trade responses act as overlay/veto only and are rejected
  if they modify deterministic setup side, prices, notional, or hold time.

- [x] **QSE-04**: New agent cycles persist trade setup records before AI
  evaluation so future orders can be audited without reconstructing formulas
  from logs.

- [x] **QSE-05**: Operators can run read-only `ops trade-trace` to reconstruct
  candidate, setup or legacy AI, risk/order intent, and exchange evidence for a
  submitted trade.

### Quant Setup Backtesting

- [x] **QBT-01**: The deterministic setup layer used by the live runner can be
  evaluated by the backtest engine as a named `quant_setup` variant.

- [x] **QBT-02**: Setup-driven backtests support both long and short futures
  positions with fees, slippage, stop loss, take profit, and time exit.

- [x] **QBT-03**: Staged sweeps and hot-symbol matrix reports can include the
  `quant_setup` variant alongside legacy fixed hot-momentum variants.

### Indicator-Based Setup Point Logic

- [x] **QSI-01**: Live feature extraction and setup backtesting use a shared
  dependency-free indicator snapshot for ATR, VWAP, EMA spread, RSI, support,
  resistance, momentum, and volume impulse when kline data is available.

- [x] **QSI-02**: Deterministic setup scoring includes trend structure,
  RSI regime, and volume impulse factors in addition to momentum, liquidity,
  open interest, taker flow, funding, volatility, narrative quality, and
  tradability.

- [x] **QSI-03**: Setup output includes a `price_basis` breakdown explaining
  entry reference, support/resistance, ATR/volatility, stop anchor, target
  anchor, and risk/reward geometry.

- [x] **QSI-04**: AI context and read-only trade trace expose the new indicator
  features and `price_basis` while preserving AI overlay/veto semantics.

### Strategy Promotion Gates

- [x] **SPG-01**: Operators can run a read-only strategy promotion check against
  a `backtest matrix` JSON report before restoring live automation or changing
  risk profiles.

- [x] **SPG-02**: Promotion requires the selected variant to be promoted by the
  matrix summary, have positive total net PnL, and stay below the drawdown cap.

- [x] **SPG-03**: Promotion also requires every interval cell to meet minimum
  trade count, positive PnL, positive-window-rate, and drawdown checks.

- [x] **SPG-04**: Negative recent-market evidence for indicator-based
  `quant_setup` is recorded as a keep-live-paused condition, not treated as a
  deploy success.

### Quant Setup Calibration

- [x] **QSC-01**: The deterministic setup layer supports explicit setup
  profiles for offline calibration without changing the live default profile.

- [x] **QSC-02**: Backtest variants include conservative calibrated
  `quant_setup_selective` and `quant_setup_scalp` profiles for matrix
  comparison against baseline `quant_setup`.

- [x] **QSC-03**: Setup profiles can gate trades by factor edge, confidence,
  risk/reward, indicator sample size, trend alignment, RSI extremes, stop
  distance, and notional fraction.

- [x] **QSC-04**: Recent hot-symbol matrix evidence is generated for baseline,
  selective, and scalp variants, and checked through the promotion gate.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Uncapped high leverage | Small 30 USDT capital can be wiped out by fees and liquidation wicks. |
| Treating social posts as proof of profitability | Public claims are incomplete and must be validated by backtests/live logs. |
| Automatic live env switch on deploy | Profile changes remain token-confirmed and operator-gated. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PRM-01 | Phase 30 | Complete |
| PRM-02 | Phase 30 | Complete |
| PRM-03 | Phase 30 | Complete |
| PRM-04 | Phase 30 | Complete |
| PRM-05 | Phase 30 | Complete |
| HLP-01 | Phase 30 | Complete |
| HLP-02 | Phase 30 | Complete |
| HLP-03 | Phase 30 | Complete |
| HLP-04 | Phase 30 | Complete |
| QSR-01 | Phase 30 | Complete |
| APR-01 | Phase 31 | Complete locally |
| APR-02 | Phase 31 | Complete locally |
| APR-03 | Phase 31 | Complete locally |
| APR-04 | Phase 32 | Complete locally |
| APR-05 | Phase 33 | Complete and deployed |
| QSE-01 | Phase 34 | Complete and deployed |
| QSE-02 | Phase 34 | Complete and deployed |
| QSE-03 | Phase 34 | Complete and deployed |
| QSE-04 | Phase 34 | Complete and deployed |
| QSE-05 | Phase 34 | Complete and deployed |
| QBT-01 | Phase 35 | Complete locally |
| QBT-02 | Phase 35 | Complete locally |
| QBT-03 | Phase 35 | Complete locally |
| QSI-01 | Phase 36 | Complete locally |
| QSI-02 | Phase 36 | Complete locally |
| QSI-03 | Phase 36 | Complete locally |
| QSI-04 | Phase 36 | Complete locally |
| SPG-01 | Phase 37 | Complete locally |
| SPG-02 | Phase 37 | Complete locally |
| SPG-03 | Phase 37 | Complete locally |
| SPG-04 | Phase 37 | Complete locally |
| QSC-01 | Phase 38 | Complete locally |
| QSC-02 | Phase 38 | Complete locally |
| QSC-03 | Phase 38 | Complete locally |
| QSC-04 | Phase 38 | Complete locally |

**Coverage:**
- v1.22 requirements: 35 total
- Mapped to phases: 35
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after Phase 38 quant setup calibration variants*
