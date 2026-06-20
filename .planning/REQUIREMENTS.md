# Requirements: Binance Futures Agent

**Defined:** 2026-06-21
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## v1.24 Requirements

### Server Readiness

- [x] **SRV-01**: Operator can run `ops live-resume-readiness` on the isolated
  server deployment without restoring live timers, starting live services,
  applying risk profiles, editing env files, or placing/canceling Binance
  orders.

- [x] **SRV-02**: Server readiness output records current paper timer, live
  timer, live service, risk profile, exchange exposure, and confirmation
  blockers in a secret-safe evidence artifact.

- [x] **SRV-03**: Manual ETH/ETHUSDT or other operator-opened exposure can be
  marked as manual in the server readiness command and is never counted as
  agent-managed strategy evidence.

### Paper Evidence Promotion

- [x] **PEV-01**: Operator can rerun the current-data hot-symbol matrix suite on
  the server or locally for `quant_setup_selective_guarded` and compare the
  result against the archived Phase 50 candidate evidence.

- [x] **PEV-02**: Server paper collection can run or preview the selected
  guarded variant without creating live order intents, restoring live
  automation, or changing exchange state.

- [x] **PEV-03**: Post-change forward-paper performance can be evaluated from a
  clear variant/timestamp boundary with minimum outcomes, positive PnL,
  minimum win rate, minimum profit factor, and drawdown caps.

### Resume Decision

- [x] **RDM-01**: Operator receives one resume decision packet with status
  `keep_live_paused`, `collect_more_paper`, `resolve_exposure`, or
  `eligible_for_operator_resume`.

- [x] **RDM-02**: Resume decision explains whether blockers are strategy
  evidence, paper evidence, server state, exchange/manual exposure, risk
  profile, AI/provider health, or missing operator confirmation.

- [x] **RDM-03**: Any live timer restore or higher-risk profile apply remains
  outside this milestone unless a separate explicit operator confirmation flow
  is planned and approved.

## Future Requirements

### Live Resume Execution

- **LRE-01**: Add a confirmation-gated live timer restore command only after
  v1.24 readiness and paper evidence prove eligibility.

- **LRE-02**: Add a confirmation-gated switch to a higher-risk dynamic profile
  only after exchange state, reconciled outcomes, and readiness evidence all
  pass.

### Data Sources

- **ADS-03**: Add more social/news/on-chain feeds after guarded paper evidence
  shows which features improve forward performance.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Restoring unattended live timer as part of v1.24 | This milestone proves server readiness and paper promotion first. |
| Applying `30u_10x_multi_dynamic` automatically | Higher-risk profile changes remain explicit and confirmation-gated. |
| Treating manual ETH/ETHUSDT as bot evidence | Manual exposure is outside the agent decision chain. |
| Claiming Lana-style profitability | Public claims remain inspiration; local evidence decides promotion. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SRV-01 | Phase 53 | Complete |
| SRV-02 | Phase 53 | Complete |
| SRV-03 | Phase 53 | Complete |
| PEV-01 | Phase 54 | Complete |
| PEV-02 | Phase 54 | Complete |
| PEV-03 | Phase 54 | Complete |
| RDM-01 | Phase 55 | Complete |
| RDM-02 | Phase 55 | Complete |
| RDM-03 | Phase 55 | Complete |

**Coverage:**

- v1.24 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 after Phase 55 operator decision packet.*
