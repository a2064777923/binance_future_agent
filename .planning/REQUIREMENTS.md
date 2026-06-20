# Requirements: Binance Futures Agent v1.26

**Defined:** 2026-06-21
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## v1.26 Requirements

### Position Lifecycle Stewardship

- [ ] **POS-01**: Operator can see exactly why any agent-managed
  `close_review` position is or is not eligible for a close/reduce plan,
  including failed preconditions, exchange filter constraints, protection
  state, matching intent evidence, and manual-symbol exclusions.
- [ ] **POS-02**: System can produce a Binance-filter-aware close/reduce plan
  for each agent-managed `close_review` position in hedge/cross mode while
  ignoring positions listed in `BFA_MANUAL_POSITION_SYMBOLS`.
- [ ] **POS-03**: Every live cycle evaluates active agent-managed positions
  before scanning new entries and records a lifecycle decision of `hold`,
  `watch`, `reduce`, `close_review`, `close_ready`, `blocked`, or `manual_hold`.
- [ ] **POS-04**: Unprotected or deteriorating agent-managed positions are
  surfaced with higher urgency than normal hold-time expiry, without managing
  manual positions.

### Guarded Exit Execution

- [ ] **EXIT-01**: Operator can execute a close/reduce action for an
  agent-managed position only when a fresh plan token matches, the live service
  state is safe, and Binance quantity/notional filters pass.
- [ ] **EXIT-02**: The live runner can optionally perform deterministic
  auto-management for agent-managed positions under explicit env flags,
  small-account caps, daily-loss limits, and manual-symbol exclusions.
- [ ] **EXIT-03**: After any close/reduce execution, the system verifies the
  post-action position size and cancels symbol protective algo orders only
  when the relevant position side is flat or reduced as intended.

### Outcome Learning

- [ ] **LEARN-01**: Closed live outcomes are reconciled automatically or by a
  single scheduled command soon after exits, with net PnL, commission, fills,
  and matching order-intent IDs persisted idempotently.
- [ ] **LEARN-02**: Operator can review live performance by symbol, side,
  setup profile, setup reasons, factor evidence, exit reason, and holding
  behavior across the small-capital pilot.
- [ ] **LEARN-03**: Live loss and weak-performance groups can produce
  recommendation-only guard updates before any future live risk increase or
  strategy promotion.

### Server Evidence And Isolation

- [ ] **OPS-01**: Server live-cycle artifacts include position lifecycle
  decisions, manual-position exclusions, cap usage, exit-plan status, and trace
  IDs for submitted entry or exit actions.
- [ ] **OPS-02**: v1.26 deployment remains isolated to
  `/opt/binance-futures-agent` and `/etc/binance-futures-agent`, keeps the live
  timer running unless a deployment pause is necessary, and restores timers
  after verification.
- [ ] **RISK-04**: Automatic or operator-confirmed position-management actions
  remain bounded by current 30U/10x/8-position caps, per-trade and daily-loss
  limits, duplicate-exposure rules, and manual-symbol exclusion.

## v1.27+ Requirements

### Future Scaling And Strategy Breadth

- **SCALE-01**: Propose higher capital, leverage, or notional caps only after
  repeated positive closed live outcomes pass net-PnL, drawdown, and
  profit-factor gates.
- **STRAT-05**: Add richer external social/news adapters only when access is
  stable, allowed, and measurable.
- **MODEL-01**: Add multi-regime strategy selection across trend, breakout,
  reversal, and no-trade setup families after live outcome attribution is
  stable.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automatically managing `BTWUSDT` or other manual positions | Manual exposure must remain isolated unless the operator explicitly hands it to the agent. |
| Raising account capital or leverage above the active 30U/10x profile | Needs separate approval and stronger live outcome evidence. |
| Treating public Lana/Square/X posts as proof of profitability | Public claims remain design inputs only. |
| Fully autonomous code or strategy self-modification | Guard changes can be recommended, but code/config promotion must remain explicit. |
| Cross-exchange trading | Binance-only behavior is not proven enough yet. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| POS-01 | Phase 61 | Satisfied |
| POS-02 | Phase 61 | Satisfied |
| POS-03 | Phase 63 | Pending |
| POS-04 | Phase 61 | Satisfied |
| EXIT-01 | Phase 62 | Pending |
| EXIT-02 | Phase 63 | Pending |
| EXIT-03 | Phase 62 | Pending |
| LEARN-01 | Phase 64 | Pending |
| LEARN-02 | Phase 64 | Pending |
| LEARN-03 | Phase 64 | Pending |
| OPS-01 | Phase 65 | Pending |
| OPS-02 | Phase 65 | Pending |
| RISK-04 | Phase 62 | Pending |

**Coverage:**
- v1.26 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 after v1.26 roadmap creation*
