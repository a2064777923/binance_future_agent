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

**Coverage:**
- v1.22 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after Phase 33 filter-aware adjustment implementation*
