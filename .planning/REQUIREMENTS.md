# Requirements: Binance Futures Agent v1.1 Live Activation

**Defined:** 2026-06-20
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

v1.0 requirements are archived at
`.planning/milestones/v1.0-REQUIREMENTS.md`.

## v1.1 Requirements

### Live Credential Activation

- [x] **LVA-01**: Configure `OPENAI_API_KEY` on
  `/etc/binance-futures-agent/env` out of band without writing it to git,
  planning docs, shell history, or command output.

- [x] **LVA-02**: Validate server live config with Binance credentials,
  `OPENAI_API_KEY`, `BFA_MODE=live`, `BFA_OPENAI_ENABLED=true`,
  `BFA_REQUIRE_PROTECTIVE_ORDERS=true`, `OPENAI_BASE_URL`,
  `OPENAI_TIMEOUT_SECONDS=5`, `OPENAI_MAX_OUTPUT_TOKENS=400`, and
  `OPENAI_RETRY_AFTER_SECONDS=300`.

### One-Cycle Live Pilot

- [x] **LVA-03**: Run one operator-approved live cycle through
  `binance-futures-agent-live.service` before enabling the timer.

- [x] **LVA-04**: Prove fail-closed behavior for AI timeout/error and prove that
  no order intent is created when OpenAI is unavailable; API failures enter
  backoff and are retried after the configured recovery interval.

- [ ] **LVA-05**: If a live entry order is submitted, prove protective
  stop-loss and take-profit algo orders are submitted in the same execution
  path, or prove kill-switch plus emergency reduce-only close behavior.

### Timer And Evidence

- [x] **LVA-06**: Enable `binance-futures-agent-live.timer` only after manual
  review, and capture first live activation evidence without secrets.

### Backtest And Calibration Follow-Up

- [x] **BT-01**: Provide a local small-capital backtest harness that uses
  completed Binance USD-M candles, enters at the next candle open, and includes
  fees, slippage, notional caps, per-trade risk caps, daily loss caps, and
  concurrent-position caps.

- [x] **BT-02**: Provide staged short-window sweep reporting across conservative
  parameter variants so results can be judged by stability across small market
  regimes, not only one full-period result.

- [x] **BT-03**: Document the backtest commands, limitations, and promotion
  rules before any live risk-limit increase.

### Decision Robustness

- [x] **AIR-01**: AI decision context includes a latest market reference price
  for the candidate symbol when kline data is available.

- [x] **AIR-02**: AI instructions require complete executable price geometry for
  `trade` decisions and require `pass` when entry, stop, or target cannot be
  provided.

- [x] **AIR-03**: Local validation rejects trades whose entry is implausibly far
  from the market reference price, in addition to existing risk and geometry
  gates.

- [x] **AIR-04**: Live runner evidence distinguishes fail-closed incomplete AI
  trade outputs from submitted or protective-order evidence.

### Pilot Tradability

- [x] **PTF-01**: Candidate feature extraction includes Binance execution
  filter facts needed to estimate the minimum executable notional under current
  symbol quantity and notional rules.

- [x] **PTF-02**: Candidate generation rejects symbols whose minimum executable
  notional exceeds the configured 100 USDT pilot position cap.

- [x] **PTF-03**: AI decision context and validation include the candidate's
  minimum executable notional so trade decisions below Binance minimums fail
  closed before order intent submission.

- [x] **PTF-04**: Live pilot keeps existing 100 USDT caps unchanged while
  avoiding AI calls for cap-incompatible hot symbols.

### Pilot Symbol Universe

- [x] **PSU-01**: Default market symbols are a capped 10-symbol Binance USD-M
  universe whose current minimum executable notionals fit the 20 USDT pilot
  position cap.

- [x] **PSU-02**: Local and server env examples match the pilot-tradable default
  symbol universe and keep risk caps unchanged.

- [x] **PSU-03**: CLI and config tests remain explicit about fixture-specific
  symbol allowlists so test fixtures do not depend on live defaults.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Trading above 100 USDT pilot capital | Requires separate evidence and explicit approval. |
| Running without OpenAI key | User selected OpenAI model; fail-closed is safer than substituting another decision source. |
| Enabling timer before one-cycle validation | Periodic live trading should start only after one reviewed cycle. |
| Removing deterministic risk gates | LLM remains slow-path analyst/veto, not direct execution authority. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LVA-01 | Phase 9 | Complete |
| LVA-02 | Phase 9 | Complete - live config valid; OpenAI endpoint is intermittent |
| LVA-03 | Phase 9 | Complete - candidate-driven live cycle observed |
| LVA-04 | Phase 9 | Complete - timeout writes backoff and submits no order |
| LVA-05 | Phase 9 | Not triggered - no live entry has been submitted yet |
| LVA-06 | Phase 9 | Complete - timer enabled and active |
| BT-01 | Phase 10 | Complete - local harness added |
| BT-02 | Phase 10 | Complete - staged sweep added |
| BT-03 | Phase 10 | Complete - runbook added |
| AIR-01 | Phase 11 | Complete - reference price included in AI context |
| AIR-02 | Phase 11 | Complete - prompt requires full trade geometry or pass |
| AIR-03 | Phase 11 | Complete - entry/reference validation added |
| AIR-04 | Phase 11 | Complete - incomplete model trades remain fail-closed |
| PTF-01 | Phase 12 | Complete - min executable notional features added |
| PTF-02 | Phase 12 | Complete - cap-incompatible candidates rejected |
| PTF-03 | Phase 12 | Complete - AI context and validation include min executable notional |
| PTF-04 | Phase 12 | Complete - pilot caps unchanged; AI skipped for impossible candidates |
| PSU-01 | Phase 13 | Complete - 10 pilot-tradable high-liquidity symbols selected |
| PSU-02 | Phase 13 | Complete - defaults and env examples updated |
| PSU-03 | Phase 13 | Complete - tests override fixture allowlists explicitly |

**Coverage:**

- v1.1-v1.5 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after completing v1.5 pilot symbol universe*
