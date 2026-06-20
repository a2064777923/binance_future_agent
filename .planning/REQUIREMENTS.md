# Requirements: Binance Futures Agent

**Defined:** 2026-06-21
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## v1.23 Requirements

### Evidence Baseline

- [x] **EVB-01**: Operator can generate a compact current evidence baseline that
  reports forward-paper signals, settled outcomes, win rate, total net PnL,
  profit factor, worst drawdown, open signals, and latest outcomes.

- [x] **EVB-02**: Evidence baseline includes loss attribution by symbol, side,
  exit reason, setup reason, factor reason, and factor name.

- [x] **EVB-03**: Evidence baseline records server automation state
  (`paper.timer`, `live.timer`, `live.service`) without mutating services.

- [x] **EVB-04**: Evidence baseline explicitly states whether live resume is
  blocked by strategy evidence, server state, exchange/manual exposure, or
  operator confirmation.

### Setup Recalibration

- [x] **SRC-01**: Strategy profiles can tighten or disable weak symbol, side,
  setup-reason, factor-reason, and factor-name groups identified by paper loss
  attribution.

- [x] **SRC-02**: Stop-loss and take-profit geometry can be recalibrated using
  ATR, support/resistance, VWAP, recent swing structure, and observed
  stop-loss/time-exit attribution.

- [x] **SRC-03**: Setup scoring can penalize missing open-interest evidence,
  thin liquidity, weak RSI/trend/momentum regimes, and historically losing
  taker-flow or volume-impulse conditions.

- [x] **SRC-04**: Recalibrated setup variants remain paper/backtest-first and
  do not change live defaults until promotion gates pass.

### Backtest And Forward Paper

- [x] **BFP-01**: Operator can run a refreshed hot-symbol matrix across multiple
  recent hot universes, at least `5m` and `15m`, and multiple setup variants.

- [x] **BFP-02**: Matrix reports compare total net PnL, win rate,
  positive-window rate, trade count, and worst drawdown for each interval and
  variant.

- [x] **BFP-03**: Forward-paper performance checks can evaluate post-change
  evidence separately from older pre-change outcomes.

- [x] **BFP-04**: Strategy promotion remains blocked unless repeated backtest
  and forward-paper evidence pass configured minimum outcomes, positive PnL,
  win-rate, profit-factor, and drawdown gates.

### Live Resume Readiness

- [x] **LRR-01**: Operator can run one read-only live-resume readiness command
  that combines strategy promotion, forward-paper performance, server timer
  state, exchange state, risk-profile state, and confirmation requirements.

- [x] **LRR-02**: Readiness report distinguishes agent-managed exposure from
  manual exchange exposure so manual positions do not get silently treated as
  agent-approved strategy evidence.

- [x] **LRR-03**: Live auto-hot remains disabled by default and can be previewed
  only through dry-run/read-only checks before any live timer restore.

- [x] **LRR-04**: `30u_10x_multi_dynamic` or any higher-risk profile remains
  preview/confirmation-gated and cannot be applied by readiness reporting.

## Future Requirements

### Additional Data Sources

- **ADS-01**: Add a replaceable Binance Square browser/export collector when a
  stable allowed source is available.

- **ADS-02**: Add additional social/news/on-chain feeds after strategy evidence
  shows which signals improve forward-paper outcomes.

### Automation

- **AUT-01**: Consider automatic profile switching only after repeated live
  pilots prove positive risk-adjusted results.

- **AUT-02**: Consider automatic position exits only after operator-approved
  exit plans have repeated successful evidence.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Restoring unattended live timer immediately | Current paper evidence is negative and live resume must be evidence-gated. |
| Treating manual exchange positions as agent strategy wins/losses | Manual trades are outside the agent's decision chain. |
| Applying `30u_10x_multi_dynamic` automatically | Higher-risk profile changes remain explicit, previewed, and confirmation-gated. |
| Copying private Lana strategy claims as truth | Public claims are inspiration only; promotion requires local evidence. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EVB-01 | Phase 48 | Complete |
| EVB-02 | Phase 48 | Complete |
| EVB-03 | Phase 48 | Complete |
| EVB-04 | Phase 48 | Complete |
| SRC-01 | Phase 49 | Complete |
| SRC-02 | Phase 49 | Complete |
| SRC-03 | Phase 49 | Complete |
| SRC-04 | Phase 49 | Complete |
| BFP-01 | Phase 50 | Complete |
| BFP-02 | Phase 50 | Complete |
| BFP-03 | Phase 51 | Complete |
| BFP-04 | Phase 51 | Complete |
| LRR-01 | Phase 52 | Complete |
| LRR-02 | Phase 52 | Complete |
| LRR-03 | Phase 52 | Complete |
| LRR-04 | Phase 52 | Complete |

**Coverage:**

- v1.23 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 after Phase 52 live-resume readiness report.*
