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

- [x] **LVA-05**: If a live entry order is submitted, prove protective
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

### Balance Preflight Gate

- [x] **BPG-01**: Live execution checks Binance account available balance before
  margin setup or entry order submission.

- [x] **BPG-02**: If available balance is below the order intent's estimated
  initial margin, execution rejects with `insufficient_available_balance` and
  submits no order.

- [x] **BPG-03**: Account balance API errors fail closed before entry order
  submission.

### DeepSeek AI Provider Switch

- [x] **DSP-01**: Runtime config can select `BFA_AI_PROVIDER=deepseek` without
  requiring an OpenAI API key.

- [x] **DSP-02**: DeepSeek decisions use the OpenAI-compatible Chat Completions
  API with JSON object mode and the existing deterministic decision schema.

- [x] **DSP-03**: AI response parsing tolerates fenced JSON or prefixed text but
  still rejects invalid or schema-incomplete decisions before execution.

- [x] **DSP-04**: Server live config can switch to DeepSeek without changing
  Binance credentials, risk caps, margin mode, position mode, or service
  isolation.

### 30U Higher-Leverage Trial Profile

- [x] **HLT-01**: Server live config can switch from the 100 USDT pilot profile
  to a 30 USDT trial profile without changing Binance credentials, DeepSeek
  provider settings, margin mode, position mode, protective-order requirement,
  or service isolation.

- [x] **HLT-02**: The 30 USDT trial profile caps leverage at 5x, position
  notional at 12 USDT, single-trade stop risk at 0.3 USDT, daily loss at 1 USDT,
  and concurrent positions at 1.

- [x] **HLT-03**: Server health and live-status checks pass after the profile
  switch, and live-status reports the real exchange position and protective
  algo-order state.

### Timer Resume Gate

- [x] **TRG-01**: Provide a read-only `ops resume-check` command that returns
  `resume_allowed` only when there are no active exchange positions, no open
  normal orders, no open algo orders, and no active AI backoff.

- [x] **TRG-02**: If an active position exists with confirmed protective algo
  orders, the resume gate returns `keep_paused` rather than allowing timer
  resume.

- [x] **TRG-03**: If an active position lacks confirmed protective algo orders,
  or open orders exist without a position, the resume gate returns
  `urgent_attention`.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Trading above the active configured trial capital | Requires separate evidence and explicit approval. |
| Running without a configured AI provider key | User selected model-driven decisions; fail-closed is safer than substituting another decision source. |
| Enabling timer before one-cycle validation | Periodic live trading should start only after one reviewed cycle. |
| Removing deterministic risk gates | LLM remains slow-path analyst/veto, not direct execution authority. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LVA-01 | Phase 9 | Complete |
| LVA-02 | Phase 9 | Complete - live config valid; OpenAI endpoint is intermittent |
| LVA-03 | Phase 9 | Complete - candidate-driven live cycle observed |
| LVA-04 | Phase 9 | Complete - timeout writes backoff and submits no order |
| LVA-05 | Phase 19 | Complete - first live ZECUSDT entry filled and stop-loss/take-profit algo orders are visible |
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
| BPG-01 | Phase 17 | Complete - live account balance checked before entry |
| BPG-02 | Phase 17 | Complete - insufficient balance rejects before order calls |
| BPG-03 | Phase 17 | Complete - account balance read errors fail closed |
| DSP-01 | Phase 18 | Complete - DeepSeek provider config validates without OpenAI key |
| DSP-02 | Phase 18 | Complete - DeepSeek Chat Completions JSON mode client added |
| DSP-03 | Phase 18 | Complete - JSON extraction and schema validation cover noisy AI output |
| DSP-04 | Phase 18 | Complete - server can switch AI provider without risk cap changes |
| HLT-01 | Phase 19 | Complete - server env switched while preserving credentials/provider/margin/position/service isolation |
| HLT-02 | Phase 19 | Complete - 30U/5x/12U/0.3U/1U/1-position caps verified on server |
| HLT-03 | Phase 19 | Complete - health/live-status checks passed and exchange evidence includes current position plus algo protection |
| TRG-01 | Phase 20 | Complete - `ops resume-check` allows resume only for clear exchange/backoff state |
| TRG-02 | Phase 20 | Complete - protected active ZECUSDT returns `keep_paused` |
| TRG-03 | Phase 20 | Complete - unprotected positions and orphan orders return `urgent_attention` in tests |

**Coverage:**

- v1.1-v1.12 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0

---
*Requirements defined: 2026-06-20*
*Last updated: 2026-06-20 after verifying v1.12 timer resume gate*
