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

### Interval-Aware Forward Paper Gate

- [x] **IFP-01**: The strategy promotion check can evaluate explicitly selected
  matrix intervals without treating a passing interval as full live-resume
  evidence.

- [x] **IFP-02**: Selected-interval checks report selected interval summaries,
  selected interval cell checks, scope, and `live_resume_allowed=false`.

- [x] **IFP-03**: The default strategy promotion behavior remains all-interval
  strict and continues to block mixed evidence where any interval fails.

- [x] **IFP-04**: The latest Phase 38 matrix can mark
  `quant_setup_selective` on `5m` as `forward_paper_allowed` while the default
  all-interval check still returns `keep_live_paused`.

### Forward-Paper Evidence Recorder

- [x] **FPE-01**: A read-only forward-paper command can record calibrated
  quant setup paper signals without creating order intents or touching signed
  Binance endpoints.

- [x] **FPE-02**: Forward-paper records use dedicated event-store categories
  for `paper_signals` and `paper_outcomes`.

- [x] **FPE-03**: Open paper signals can be settled into paper outcomes using
  later public kline bars with stop, target, time-exit, fees, and slippage.

- [x] **FPE-04**: Forward-paper commands support explicit symbol, interval,
  variant, limit, and deterministic timestamp inputs for repeatable evidence
  collection.

### Forward-Paper Scheduling

- [x] **FPS-01**: Deployment assets include a paper-only systemd service and
  timer that run `ops forward-paper-run` instead of `agent run-once`.

- [x] **FPS-02**: Paper-only systemd assets use isolated project paths and do
  not enable, start, or restart themselves during deployment.

- [x] **FPS-03**: Deployment documentation explains how to run or enable the
  paper-only timer separately from live automation.

- [x] **FPS-04**: Forward-paper scheduling uses a wider auto-hot symbol
  universe than the live pilot allowlist, without changing the live
  `BFA_MARKET_SYMBOLS` trading universe.

### Forward-Paper Performance Gate

- [x] **FPG-01**: Operators can run a read-only
  `ops forward-paper-performance-check` command against stored
  `paper_signals` and `paper_outcomes`.

- [x] **FPG-02**: The performance gate reports signal/outcome counts, open
  signal count, win/loss/flat counts, win rate, net PnL, profit factor, worst
  drawdown, exit reasons, per-symbol summaries, and latest outcomes.

- [x] **FPG-03**: Missing paper signals, too few settled outcomes, non-positive
  net PnL, low win rate, or excessive drawdown return non-promoted statuses.

- [x] **FPG-04**: Passing paper thresholds can allow only paper promotion and
  must keep `live_resume_allowed=false`.

### Forward-Paper Loss Attribution

- [x] **FLA-01**: Operators can run a read-only forward-paper loss attribution
  command against stored paper signals and outcomes.

- [x] **FLA-02**: The attribution report joins settled outcomes back to their
  originating paper signal setup payloads.

- [x] **FLA-03**: The report ranks underperforming groups by symbol, side,
  exit reason, setup reasons, setup warnings, and setup factor evidence.

- [x] **FLA-04**: The report emits concrete recalibration candidates while
  preserving `live_resume_allowed=false`.

### Forward-Paper Guarded Calibration

- [x] **FGC-01**: Setup profiles can explicitly disable selected trade sides
  without changing the existing default/live profile.

- [x] **FGC-02**: Setup profiles can exclude symbols identified by
  forward-paper attribution.

- [x] **FGC-03**: Backtest and forward-paper paths expose a built-in guarded
  quant setup variant derived from Phase 43 attribution.

- [x] **FGC-04**: Guarded calibration remains paper/backtest evidence only and
  does not restore live automation or change risk profiles.

### Live Auto-Hot Candidate Breadth

- [x] **LAC-01**: Live/dry-run agent cycles can optionally select a wider
  hot-symbol scanning universe from Binance USD-M 24h ticker data instead of
  only the fixed `BFA_MARKET_SYMBOLS` allowlist.

- [x] **LAC-02**: Live auto-hot selection is disabled by default and falls
  back to `BFA_MARKET_SYMBOLS` whenever it is disabled, empty, or unavailable.

- [x] **LAC-03**: The selected live scanning universe is reused consistently
  for market collection, narrative symbol extraction, market-heat fallback, and
  candidate allowlisting.

- [x] **LAC-04**: Wider scanning does not increase order authority by itself:
  per-cycle candidate evaluation, setup gates, AI overlay or quant fallback,
  risk caps, and one-order-per-cycle behavior remain in force.

### Live Auto-Hot Dry-Run Evidence

- [x] **LAD-01**: Operators can collect one-shot server evidence for live
  auto-hot scanning with `BFA_MODE=dry_run` and without enabling unattended live
  automation.

- [x] **LAD-02**: The evidence records the selected `scan_symbols`,
  candidate/evaluated symbol counts, and whether the run remained non-live.

- [x] **LAD-03**: The evidence confirms server env remains
  `BFA_LIVE_AUTO_HOT_SYMBOLS=false` after the one-shot dry-run command.

### Adaptive Forward-Paper Candidate Guard

- [x] **FPG-05**: Forward-paper evidence can be converted into a deterministic
  guard that no-ops when settled outcome evidence is below a configured minimum.

- [x] **FLA-05**: Loss attribution can drive symbol, side, and factor-reason
  blocks only when group outcome count, net loss, and win-rate thresholds are
  all met.

- [x] **ACG-01**: Agent candidate generation rejects symbols blocked by recent
  forward-paper evidence before AI or execution is consulted.

- [x] **ACG-02**: Deterministic setup generation can reject guarded sides or
  factor reasons through setup profile data.

- [x] **ACG-03**: Forward-paper runs skip guarded symbols before generating new
  paper signals and report guard status plus guarded symbols.

- [x] **ACG-04**: Adaptive guard configuration is exposed through safe defaults
  and deploy examples without enabling live automation or changing risk
  profiles.

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
| IFP-01 | Phase 39 | Complete locally |
| IFP-02 | Phase 39 | Complete locally |
| IFP-03 | Phase 39 | Complete locally |
| IFP-04 | Phase 39 | Complete locally |
| FPE-01 | Phase 40 | Complete locally |
| FPE-02 | Phase 40 | Complete locally |
| FPE-03 | Phase 40 | Complete locally |
| FPE-04 | Phase 40 | Complete locally |
| FPS-01 | Phase 41 | Complete and deployed |
| FPS-02 | Phase 41 | Complete and deployed |
| FPS-03 | Phase 41 | Complete and deployed |
| FPS-04 | Phase 41 | Complete and deployed |
| FPG-01 | Phase 42 | Complete and deployed |
| FPG-02 | Phase 42 | Complete and deployed |
| FPG-03 | Phase 42 | Complete and deployed |
| FPG-04 | Phase 42 | Complete and deployed |
| FLA-01 | Phase 43 | Complete and deployed |
| FLA-02 | Phase 43 | Complete and deployed |
| FLA-03 | Phase 43 | Complete and deployed |
| FLA-04 | Phase 43 | Complete and deployed |
| FGC-01 | Phase 44 | Complete and deployed |
| FGC-02 | Phase 44 | Complete and deployed |
| FGC-03 | Phase 44 | Complete and deployed |
| FGC-04 | Phase 44 | Complete and deployed |
| LAC-01 | Phase 45 | Complete locally |
| LAC-02 | Phase 45 | Complete locally |
| LAC-03 | Phase 45 | Complete locally |
| LAC-04 | Phase 45 | Complete locally |
| LAD-01 | Phase 46 | Complete and deployed |
| LAD-02 | Phase 46 | Complete and deployed |
| LAD-03 | Phase 46 | Complete and deployed |
| FPG-05 | Phase 47 | Complete locally |
| FLA-05 | Phase 47 | Complete locally |
| ACG-01 | Phase 47 | Complete locally |
| ACG-02 | Phase 47 | Complete locally |
| ACG-03 | Phase 47 | Complete locally |
| ACG-04 | Phase 47 | Complete locally |

**Coverage:**
- v1.22 requirements: 72 total
- Mapped to phases: 72
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-21 after Phase 47 adaptive paper guard*
