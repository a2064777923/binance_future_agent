# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Milestones

- ✅ **v1.0 Dry-Run Binance Futures Agent** — Phases 1-8, shipped 2026-06-19
  ([archive](milestones/v1.0-ROADMAP.md)).

- ✅ **v1.1 Live Activation** — Phase 9, live timer activation verified; LVA-05
  was later satisfied by the first protected ZECUSDT live entry.
- ✅ **v1.2 Backtest Calibration** — Phase 10, completed 2026-06-20.
- ✅ **v1.3 Decision Robustness** — Phase 11, completed 2026-06-20.
- ✅ **v1.4 Pilot Tradability Filter** — Phase 12, completed 2026-06-20.
- ✅ **v1.5 Pilot Symbol Universe** — Phase 13, completed 2026-06-20.
- ✅ **v1.6 Margin Setup Fail-Closed** — Phase 14, completed 2026-06-20.
- ✅ **v1.7 Configurable Margin Mode** — Phase 15, completed 2026-06-20.
- ✅ **v1.8 Position Mode Entry Fail-Closed** — Phase 16, completed 2026-06-20.
- ✅ **v1.9 Balance Preflight Gate** — Phase 17, completed 2026-06-20.
- ✅ **v1.10 DeepSeek Provider Switch** — Phase 18, completed 2026-06-20.
- ✅ **v1.11 30U Higher-Leverage Trial Profile** — Phase 19, completed 2026-06-20
  with live timer paused for open-position review.
- ✅ **v1.12 Timer Resume Gate** — Phase 20, completed 2026-06-20.
- ✅ **v1.13 Closed Trade Outcome Reconciliation** — Phase 21, completed 2026-06-20.
- ✅ **v1.14 Risk Change Readiness Gate** — Phase 22, completed 2026-06-20.
- ✅ **v1.15 Closed Outcome Risk Change Strictness** — Phase 23, completed 2026-06-20.

## Phases

<details>
<summary>✅ v1.0 Dry-Run Binance Futures Agent (Phases 1-8) — SHIPPED 2026-06-19</summary>

- [x] Phase 1: Isolated Project Foundation (4/4 plans)
- [x] Phase 2: Binance Futures Market Data Layer (5/5 plans)
- [x] Phase 3: Narrative And Hot-Coin Collection Layer (3/3 plans)
- [x] Phase 4: Event Store And Replay Foundation (3/3 plans)
- [x] Phase 5: Hot-Coin Candidate Strategy (2/2 plans)
- [x] Phase 6: OpenAI Decision Layer (3/3 plans)
- [x] Phase 7: Risk-Gated Binance Execution (4/4 plans)
- [x] Phase 8: Isolated Server Deployment (4/4 plans)

Full details are archived in `.planning/milestones/v1.0-ROADMAP.md`.

</details>

### Phase 9: Live Activation Readiness

**Goal:** Turn the deployed dry-run/live-capable system into a controlled
small-capital live automated trading pilot without losing the kill-switch,
protective-order, or isolation guarantees.

**Requirements:** LVA-01, LVA-02, LVA-03, LVA-04, LVA-05, LVA-06

**Status:** Complete for activation readiness. Live timer is currently paused
for open-position review;
market-heat fallback now produces candidates without Square/RSS input; a
candidate-driven live cycle reached OpenAI and resulted in pass/no submission.
OpenAI timeouts enter backoff. LVA-05 is now satisfied by the first ZECUSDT
submitted entry and its protective algo orders.

**Success Criteria:**

1. Server env contains Binance and OpenAI credentials with mode set to `live`,
   `BFA_OPENAI_ENABLED=true`, `BFA_REQUIRE_PROTECTIVE_ORDERS=true`,
   provider `OPENAI_BASE_URL`, `OPENAI_TIMEOUT_SECONDS=5`,
   `OPENAI_MAX_OUTPUT_TOKENS=400`, `OPENAI_RETRY_AFTER_SECONDS=300`, and no
   secret leakage to git or logs.

2. Server health checks pass for config, Binance, OpenAI, database, runtime
   paths, risk state, and kill switch.

3. One operator-approved live cycle runs through
   `binance-futures-agent-live.service` with at most one risk-gated order
   attempt and deterministic fail-closed/backoff behavior on AI timeout/error.

4. If an entry order is submitted, stop-loss and take-profit protective algo
   orders are submitted in the same execution path, or kill switch plus
   emergency reduce-only close behavior is observed.

5. The live timer is enabled only after the one-cycle result is reviewed, and it
   can be disabled with `systemctl disable --now binance-futures-agent-live.timer`
   plus the kill-switch file.

6. The first live activation evidence is captured in GSD verification notes
   without printing or committing secret values.

### Phase 10: Small-Capital Backtest Calibration

**Goal:** Add repeatable short-window backtests before raising live risk limits
in a volatile crypto futures market.

**Requirements:** BT-01, BT-02, BT-03

**Status:** Complete. Local backtest harness, staged sweeps, hot matrix
reporting, documentation, tests, and public-kline smoke runs are captured.

**Success Criteria:**

1. Historical Binance USD-M kline datasets can be fetched without secrets.
2. The hot-momentum baseline backtest uses completed candles only and enters on
   the next candle open.

3. Fees, slippage, notional, risk-per-trade, daily-loss, and open-position caps
   are included in reported metrics.

4. Staged sweeps compare strict, balanced, and aggressive variants across small
   windows.

5. Results are written to gitignored data/results paths and documented before
   any live cap increase.

### Phase 11: AI Decision Robustness

**Goal:** Improve live AI decision quality so executable trades include complete
reference-price-based entry, stop, and target data, while incomplete trade
outputs fail closed.

**Requirements:** AIR-01, AIR-02, AIR-03, AIR-04

**Status:** Complete.

**Success Criteria:**

1. Candidate features and compact AI context include `reference_price` when
   recent kline close data is available.
2. AI instructions explicitly require complete executable trade geometry or a
   `pass`.
3. Local validation rejects trades whose entry price is too far from the
   candidate reference price.
4. Existing fail-closed behavior remains intact: incomplete AI trade outputs do
   not create submitted order intents.
5. Full test suite and server health checks pass after deployment.

### Phase 12: Pilot Tradability Filter

**Goal:** Stop the 100 USDT pilot from selecting hot symbols whose Binance
minimum executable notional cannot fit the configured max position notional cap.

**Requirements:** PTF-01, PTF-02, PTF-03, PTF-04

**Status:** Complete.

**Success Criteria:**

1. Candidate features include Binance `minQty`, `stepSize`, `minNotional`, and
   computed `min_executable_notional` when exchange filters and reference price
   are available.
2. Candidate generation rejects symbols whose `min_executable_notional` exceeds
   `BFA_MAX_POSITION_NOTIONAL_USDT`.
3. AI context includes `min_executable_notional`, and local AI validation
   rejects trade notional below that value.
4. The live runner skips AI for cap-incompatible candidates rather than
   spending model calls on impossible trades.
5. Full tests and server health checks pass after deployment.

### Phase 13: Pilot Symbol Universe

**Goal:** Replace the BTC/ETH-heavy default symbol list with a controlled
10-symbol universe that currently fits the 20 USDT pilot notional cap.

**Requirements:** PSU-01, PSU-02, PSU-03

**Status:** Complete.

**Success Criteria:**

1. Default `BFA_MARKET_SYMBOLS` contains at most 10 symbols so the existing
   collector cap remains valid.
2. Each default symbol was selected from current Binance USD-M public filters as
   cap-compatible under the 20 USDT max-position-notional setting.
3. `.env.example` and `deploy/server-env.example` match the new default list.
4. CLI/config tests explicitly override fixture-specific BTC/ETH allowlists.
5. Full tests and server health checks pass after deployment.

### Phase 14: Margin Setup Fail-Closed

**Goal:** Ensure Binance margin/leverage setup failures reject the order intent
without crashing the live service or submitting an entry order.

**Requirements:** MSF-01, MSF-02, MSF-03

**Status:** Complete.

**Success Criteria:**

1. `_ensure_live_margin` Binance errors are caught before entry order
   submission.
2. The execution result is `status=rejected`, `submitted=false`, and includes
   `margin_setup_failed`.
3. Margin setup error details are persisted as exchange-response evidence.
4. Regression coverage reproduces Multi-Assets mode isolated-margin rejection.
5. Full tests and server health checks pass after deployment.

### Phase 15: Configurable Margin Mode

**Goal:** Allow the live pilot to use explicit cross margin setup for a Binance
Multi-Assets account while preserving existing pilot caps and fail-closed gates.

**Requirements:** CMM-01, CMM-02, CMM-03, CMM-04

**Status:** Complete.

**Success Criteria:**

1. `BFA_MARGIN_MODE` validates to either `isolated` or `cross`.
2. `isolated` maps to Binance `ISOLATED`; `cross` maps to Binance `CROSSED`.
3. Live cross mode produces a config warning but does not change notional,
   leverage, per-trade risk, daily loss, max positions, kill switch, or
   protective-order requirements.
4. Server env can be updated to `BFA_MARGIN_MODE=cross` without touching
   credentials or other services.
5. Full tests and server health checks pass after deployment.

### Phase 16: Position Mode And Entry Fail-Closed

**Goal:** Allow the live pilot to match Binance hedge/position-side account
settings and fail closed if entry order placement is rejected.

**Requirements:** PME-01, PME-02, PME-03, PME-04

**Status:** Complete.

**Success Criteria:**

1. `BFA_POSITION_MODE` validates to either `one_way` or `hedge`.
2. Hedge mode sends `positionSide=LONG` for long entries and `SHORT` for short
   entries on entry and protective orders.
3. Entry order errors produce `status=rejected`, `submitted=false`, and
   `entry_order_failed` evidence instead of a service crash.
4. Server env can be updated to `BFA_POSITION_MODE=hedge` without touching
   credentials, risk caps, or other services.
5. Full tests and server health checks pass after deployment.

### Phase 17: Balance Preflight Gate

**Goal:** Avoid repeated live order attempts when Binance futures available
balance is below the order intent's estimated initial margin.

**Requirements:** BPG-01, BPG-02, BPG-03

**Status:** Complete.

**Success Criteria:**

1. Live execution reads account available balance before margin setup or entry
   order placement.
2. Insufficient available balance rejects with `insufficient_available_balance`.
3. Account-balance read errors reject before entry order placement.
4. No order is submitted when futures account available balance is insufficient.
5. Full tests and server health checks pass after deployment.

### Phase 18: DeepSeek Provider Switch

**Goal:** Switch the live AI decision provider from the intermittent
OpenAI-compatible endpoint to DeepSeek while preserving strict JSON validation
and all live risk caps.

**Requirements:** DSP-01, DSP-02, DSP-03, DSP-04

**Status:** Complete.

**Success Criteria:**

1. `BFA_AI_PROVIDER` validates to either `openai` or `deepseek`.
2. DeepSeek provider uses `/chat/completions` with JSON object mode and no
   committed secret values.
3. Fenced or prefixed JSON responses can be extracted, then still pass through
   the existing deterministic schema and risk validation.
4. Server env can be updated to DeepSeek without touching Binance credentials,
   pilot caps, margin mode, position mode, or other services.
5. Full tests, DeepSeek smoke test, and server health checks pass after
   deployment.

### Phase 19: 30U Higher-Leverage Trial Profile

**Goal:** Reconfigure the live pilot for a 30 USDT funded trial with a modest
5x leverage ceiling while keeping absolute downside caps tighter than the
previous 100 USDT profile.

**Requirements:** HLT-01, HLT-02, HLT-03

**Status:** Complete; timer intentionally paused while a pre-switch ZECUSDT
position remains open.

**Success Criteria:**

1. Server env changes only the active trial risk profile values:
   `BFA_ACCOUNT_CAPITAL_USDT=30`, `BFA_MAX_LEVERAGE=5`,
   `BFA_MAX_POSITION_NOTIONAL_USDT=12`,
   `BFA_MAX_RISK_PER_TRADE_USDT=0.3`,
   `BFA_MAX_DAILY_LOSS_USDT=1`, and `BFA_MAX_OPEN_POSITIONS=1`.
2. DeepSeek provider, Binance credentials, `BFA_MARGIN_MODE=cross`,
   `BFA_POSITION_MODE=hedge`, `BFA_REQUIRE_PROTECTIVE_ORDERS=true`, and
   isolated systemd paths remain unchanged.
3. Server health check and focused tests pass after the profile switch.
4. Server live-status shows the current exchange state, including the existing
   ZECUSDT position, zero normal open orders, two open algo protective orders,
   and no active AI backoff.
5. The live timer remains paused until the existing live position is closed or
   the operator explicitly approves resuming cycles under the 1-position cap.

### Phase 20: Timer Resume Gate

**Goal:** Make the decision to resume `binance-futures-agent-live.timer`
auditable and scriptable with a read-only gate.

**Requirements:** TRG-01, TRG-02, TRG-03

**Status:** Complete.

**Success Criteria:**

1. `ops resume-check` returns `resume_allowed` only when exchange positions,
   normal open orders, algo open orders, and AI backoff are all clear.
2. A protected active position returns `keep_paused` and a non-zero exit code.
3. An unprotected active position or orphan open orders return
   `urgent_attention` and a non-zero exit code.
4. Unit and CLI tests cover the resume gate states.
5. Server read-only resume check reports protected ZECUSDT as `keep_paused`
   while open, then `resume_allowed` after positions and orders clear; resumed
   timer cycles submit no order unless risk and AI gates allow one.

### Phase 21: Closed Trade Outcome Reconciliation

**Goal:** Turn the first completed live trade into a replayable fill/outcome
record with net PnL after commission.

**Requirements:** CTOR-01, CTOR-02, CTOR-03

**Status:** Complete. The closed ZECUSDT trade has been reconstructed from
Binance fills, persisted net of commission, and verified as idempotent on
repeat reconciliation.

**Success Criteria:**

1. Signed Binance client can read account trades with `/fapi/v1/userTrades`.
2. `ops trade-outcome` loads the latest submitted intent, fetches fills, and
   summarizes gross realized PnL, commission, net realized PnL, net quantity,
   trade count, and first/last fill times.
3. Closed round trips report `status=closed`; partial/open round trips report
   `status=open_or_partial`.
4. `--persist` writes fills and outcome artifacts to the existing event store.
5. Server read-only verification reconstructs the closed ZECUSDT trade outcome
   without modifying exchange state.
6. Repeated reconciliation does not duplicate fills or outcomes in the event
   store.

### Phase 22: Risk Change Readiness Gate

**Goal:** Make leverage or risk-cap changes auditable and fail-closed before
the server profile is modified.

**Requirements:** RCG-01, RCG-02, RCG-03

**Status:** Complete. The live BNBUSDT position correctly blocks an 8x target
with `keep_current_profile` until the position closes and outcome evidence is
persisted.

**Success Criteria:**

1. `ops risk-change-check` returns `risk_change_allowed` only when exchange
   evidence is present, there are no active positions, no normal open orders,
   no open algo orders, no active AI backoff, and every submitted order intent
   has a persisted outcome.
2. Active protected positions return `keep_current_profile` and a non-zero exit
   code rather than allowing leverage/risk changes.
3. Unprotected active positions or orphan orders return `urgent_attention` and
   a non-zero exit code.
4. Submitted order intents missing outcome artifacts return
   `keep_current_profile`.
5. Server read-only verification under the current BNBUSDT live position blocks
   the proposed 8x change without modifying exchange or env state.

### Phase 23: Closed Outcome Risk Change Strictness

**Goal:** Ensure partial/open outcome artifacts cannot unlock leverage or
risk-cap profile changes.

**Requirements:** RCG-04

**Status:** Complete. Partial/open outcome artifacts remain blocking for
leverage or risk-cap changes; only final `closed` outcomes clear submitted
intents.

**Success Criteria:**

1. Risk-change readiness considers a submitted intent reconciled only when
   `outcome:{event_id}:closed` exists.
2. `outcome:{event_id}:open_or_partial` remains blocking for leverage/risk-cap
   changes.
3. Regression tests cover the partial outcome case.
4. Server read-only verification still blocks the 8x target while BNBUSDT lacks
   a closed outcome.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1 | v1.0 | 4/4 | Complete | 2026-06-19 |
| 2 | v1.0 | 5/5 | Complete | 2026-06-19 |
| 3 | v1.0 | 3/3 | Complete | 2026-06-19 |
| 4 | v1.0 | 3/3 | Complete | 2026-06-19 |
| 5 | v1.0 | 2/2 | Complete | 2026-06-19 |
| 6 | v1.0 | 3/3 | Complete | 2026-06-19 |
| 7 | v1.0 | 4/4 | Complete | 2026-06-19 |
| 8 | v1.0 | 4/4 | Complete | 2026-06-19 |
| 9 | v1.1 | 1/1 | Complete    | 2026-06-20 |
| 10 | v1.2 | 1/1 | Complete    | 2026-06-20 |
| 11 | v1.3 | 1/1 | Complete | 2026-06-20 |
| 12 | v1.4 | 1/1 | Complete | 2026-06-20 |
| 13 | v1.5 | 1/1 | Complete | 2026-06-20 |
| 14 | v1.6 | 1/1 | Complete | 2026-06-20 |
| 15 | v1.7 | 1/1 | Complete | 2026-06-20 |
| 16 | v1.8 | 1/1 | Complete | 2026-06-20 |
| 17 | v1.9 | 1/1 | Complete | 2026-06-20 |
| 18 | v1.10 | 1/1 | Complete | 2026-06-20 |
| 19 | v1.11 | 1/1 | Complete, timer paused for open-position review | 2026-06-20 |
| 20 | v1.12 | 1/1 | Complete | 2026-06-20 |
| 21 | v1.13 | 1/1 | Complete | 2026-06-20 |
| 22 | v1.14 | 1/1 | Complete | 2026-06-20 |
| 23 | v1.15 | 1/1 | Complete | 2026-06-20 |

## Requirement Coverage

- v1.1-v1.15 requirements: 51
- Mapped: 51
- Unmapped: 0

## Next Step

Observe the current BNBUSDT live position. After it closes, run
`ops trade-outcome --symbol BNBUSDT --persist`, then rerun
`ops risk-change-check --target-leverage 8`; only if it returns
`risk_change_allowed=true` should the server profile be changed.
