# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Milestones

- ✅ **v1.0 Dry-Run Binance Futures Agent** — Phases 1-8, shipped 2026-06-19
  ([archive](milestones/v1.0-ROADMAP.md)).

- ✅ **v1.1 Live Activation** — Phase 9, live timer active under pilot caps;
  LVA-05 remains a future-entry evidence gate.
- ✅ **v1.2 Backtest Calibration** — Phase 10, completed 2026-06-20.
- 🚧 **v1.3 Decision Robustness** — Phase 11, in progress.

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

**Status:** Complete for activation readiness. Live timer is enabled/active;
market-heat fallback now produces candidates without Square/RSS input; a
candidate-driven live cycle reached OpenAI and resulted in pass/no submission.
OpenAI timeouts enter backoff. LVA-05 is conditional on a future submitted entry.

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

## Requirement Coverage

- v1.1-v1.3 requirements: 13
- Mapped: 13
- Unmapped: 0

## Next Step

Decision robustness is complete. Keep 100 USDT pilot caps unchanged and observe
live timer cycles; after the first submitted live entry, verify protective-order
evidence with `ops live-status`.
