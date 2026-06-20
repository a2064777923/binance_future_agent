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

### Margin Setup Fail-Closed

- [x] **MSF-01**: Live execution handles Binance margin/leverage setup errors
  as rejected, non-submitted order intents rather than uncaught service crashes.

- [x] **MSF-02**: Margin setup errors are persisted as exchange-response
  evidence without submitting an entry order.

- [x] **MSF-03**: Multi-Assets mode isolated-margin rejection is covered by a
  regression test.

### Configurable Margin Mode

- [x] **CMM-01**: Runtime config includes explicit `BFA_MARGIN_MODE` with only
  `isolated` and `cross` accepted values.

- [x] **CMM-02**: Execution maps `BFA_MARGIN_MODE=isolated` to Binance
  `ISOLATED` and `BFA_MARGIN_MODE=cross` to Binance `CROSSED` before leverage
  setup.

- [x] **CMM-03**: Cross margin mode keeps the same 100 USDT pilot risk caps,
  protective-order requirement, and fail-closed margin setup behavior.

- [x] **CMM-04**: Server live config can use `BFA_MARGIN_MODE=cross` to match
  the current Binance Multi-Assets account mode without changing secrets or
  other services.

### Position Mode And Entry Fail-Closed

- [x] **PME-01**: Runtime config includes explicit `BFA_POSITION_MODE` with only
  `one_way` and `hedge` accepted values.

- [x] **PME-02**: Hedge mode sends Binance `positionSide=LONG` or `SHORT` on
  entry, protective, and emergency close orders.

- [x] **PME-03**: Entry order failures are persisted as rejected,
  non-submitted execution evidence instead of uncaught service crashes.

- [x] **PME-04**: Server live config can use `BFA_POSITION_MODE=hedge` to match
  the current Binance account position-side setting without changing risk caps
  or other services.

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
| MSF-01 | Phase 14 | Complete - margin setup errors return rejected results |
| MSF-02 | Phase 14 | Complete - margin errors persist as exchange-response evidence |
| MSF-03 | Phase 14 | Complete - Multi-Assets isolated-margin rejection regression added |
| CMM-01 | Phase 15 | Complete - margin mode config added and validated |
| CMM-02 | Phase 15 | Complete - isolated/cross map to Binance margin types |
| CMM-03 | Phase 15 | Complete - risk caps and protective-order requirement unchanged |
| CMM-04 | Phase 15 | Complete - server can be explicitly configured for cross mode |
| PME-01 | Phase 16 | Complete - position mode config added and validated |
| PME-02 | Phase 16 | Complete - hedge positionSide sent on execution orders |
| PME-03 | Phase 16 | Complete - entry order errors fail closed and persist evidence |
| PME-04 | Phase 16 | Complete - server can be explicitly configured for hedge mode |

**Coverage:**

- v1.1-v1.8 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after completing v1.8 position mode entry fail-closed*
