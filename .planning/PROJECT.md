# Binance Futures Agent

## What This Is

Binance Futures Agent is an isolated crypto futures trading system for Binance
USD-M contracts. It watches hot coins from Binance Square and other narrative
sources, confirms them with futures-market anomalies, asks a configured AI
provider for structured trade decisions, and can run a tightly capped small-USDT
live pilot on a dedicated server.

This project is separate from the existing HK/US stock repository. It may borrow
ideas such as config-driven runtime, JSONL event records, replay, and explicit
execution modes, but it must not import, mutate, or deploy the stock codebase.

## Core Value

Turn hot-coin narrative momentum into auditable, risk-capped Binance futures
signals and small live trades without contaminating existing projects or losing
control of downside.

## Business Context

- **Customer**: The user running a personal trading experiment.
- **Revenue model**: Personal trading performance, not a SaaS product.
- **Success metric**: Positive risk-adjusted pilot results with bounded maximum
  drawdown, measured from recorded decisions and fills.
- **Strategy notes**: Inspired by the Lana / "棍哥" public claims around
  Binance Square hot coins, AI-agent iteration, and small-capital futures
  compounding, but implemented as a testable system rather than copied as lore.

## Requirements

### Validated

- Phase 1 validated the isolated repository at `F:\binance_futures_agent`.
- Phase 1 validated git hygiene for env files, credentials, runtime data, logs,
  local databases, and raw exports.
- Phase 1 validated the dry-run/testnet/live config contract, secret redaction,
  and `python -m bfa.cli config-check` diagnostics.
- Phase 1 documented future server isolation under `/opt/binance-futures-agent`,
  `/etc/binance-futures-agent/env`, and `binance-futures-agent.service`.
- Phase 2 validated official Binance USD-M futures public market metadata,
  REST metrics, WebSocket message parsing, normalized market snapshots, JSONL
  output, selected-symbol collection, and market-data CLI smoke commands.
- Phase 3 validated manual/export Binance Square-style narrative ingestion,
  RSS/Atom fallback ingestion, normalized narrative records, conservative symbol
  extraction, deterministic deduplication, JSONL output, and narrative CLI
  smoke commands.
- Phase 4 validated the SQLite event-store schema, append-only replay events,
  typed narrative and market snapshot persistence, generic future artifact
  persistence, deterministic replay packets, review metrics, and event-store
  CLI smoke commands.
- Phase 5 validated deterministic hot-coin candidate generation from replay
  packets, narrative/market feature extraction, conservative rejection gates,
  reason codes, data-quality notes, candidate persistence, and CLI smoke
  commands.
- Phase 6 validated compact AI decision context packets, strict structured
  JSON decision parsing, deterministic local risk validation, redacted
  request/response journaling, `ai_decisions` persistence, and AI CLI smoke
  commands with fake transports.
- Phase 7 validated dry-run order intents, Binance symbol-filter quantization,
  deterministic risk gates, signed Binance USD-M Futures order helpers,
  explicit live execution gating, event-store execution artifacts, CLI
  execution smoke commands, and read-only exchange reconciliation.
- Phase 9 validated live timer activation under 100 USDT pilot caps, market-heat
  fallback candidates, OpenAI timeout/backoff, and secret-safe live-status
  evidence.
- Phase 10 validated a local short-window backtest harness and hot matrix
  reporting before any live risk-limit increase.
- Phase 11 validated reference-price AI context, complete trade-geometry
  prompting, and deterministic rejection of entry prices too far from market.
- Phase 12 validated pilot tradability filtering: Binance execution filters are
  converted into `min_executable_notional`, cap-incompatible hot symbols are
  rejected before AI calls, and AI notional below executable minimum fails
  closed.
- Phase 13 validated a controlled 10-symbol pilot universe whose current Binance
  minimum executable notionals fit the 20 USDT max-position-notional cap.
- Phase 14 validated fail-closed handling for Binance margin setup errors, after
  live evidence showed Multi-Assets mode rejects isolated-margin changes.
- Phase 15 added explicit configurable margin mode so the server can use cross
  margin with the current Multi-Assets account while preserving pilot caps.
- Phase 16 added explicit position mode and entry-order fail-closed handling
  after live evidence showed the account expects Binance `positionSide`.
- Phase 17 added a live account-balance preflight so an unfunded USD-M futures
  account rejects locally before margin setup or entry order placement.
- Phase 18 adds DeepSeek provider support using Chat Completions JSON mode after
  the previous OpenAI-compatible endpoint produced invalid JSON/timeouts.
- Phase 19 switches the active trial profile from 100 USDT/3x to a tighter 30
  USDT/5x trial with lower absolute notional, trade-risk, daily-loss, and
  concurrency caps.
- Phase 20 adds a read-only timer resume gate so automation resumes only after
  exchange positions, normal orders, algo orders, and AI backoff are clear.

### Active

- [x] Collect Binance USD-M futures market data needed for hot-coin filtering.
- [x] Collect narrative and hotness signals from Binance Square plus fallback
  social/news sources where access is allowed.
- [x] Record every candidate, AI decision, order intent, exchange response,
  fill, and outcome in a replayable local event store.
- [x] Rank candidate symbols by narrative heat, liquidity, price momentum, open
  interest change, taker flow, funding state, and volatility.
- [x] Use a configured AI provider to produce structured trade decisions with
  entry, invalidation, stop, target, time limit, and confidence.
- [x] Implement risk-capped Binance live execution for a small-USDT pilot account.
- [x] Deploy on server `64.83.34.222` under a project-isolated directory and
  systemd unit without modifying existing services.
- [x] Improve live AI decision quality so `trade` decisions include executable
  entry, stop, and target prices derived from market reference data.
- [x] Avoid spending AI/live execution cycles on hot symbols whose Binance
  minimum executable notional exceeds the active pilot position cap.
- [x] Use a controlled pilot symbol universe that is compatible with current
  Binance filters under small max-position-notional caps.
- [x] Fail closed when Binance margin/leverage setup cannot be applied before
  entry order submission.
- [x] Support explicit cross margin setup for the current Binance Multi-Assets
  account without increasing pilot caps.
- [x] Support explicit hedge position-side setup for the current Binance account
  without increasing pilot caps.
- [x] Reject live order intents before exchange order calls when Binance USD-M
  futures available balance is below estimated initial margin.
- [x] Switch server runtime caps to the approved 30 USDT/5x trial profile and
  verify health/live-status evidence.
- [x] Capture LVA-05 protective-order evidence after the first submitted live
  entry, or prove the fail-closed emergency path if protective orders fail.
- [x] Gate future timer resume with read-only exchange and AI-backoff checks.

### Out of Scope

- Full Hermes-style review workflow - too heavy for this faster crypto pilot.
- Real-money scaling above the active trial capital - requires separate evidence and
  explicit approval.
- Cross-exchange arbitrage - defer until Binance-only behavior is understood.
- Fully autonomous model self-modification - the system may learn from journals,
  but code/config promotion must remain explicit.
- Guaranteed imitation of any public trader's private strategy - public posts
  are incomplete and may be exaggerated.

## Context

The existing stock repository demonstrates useful operational patterns:
config-driven scripts, JSON/JSONL evidence files, dry-run/live separation,
event-store thinking, replay reports, and fail-closed execution. This project
keeps those useful patterns but deliberately stays lighter: no Hermes packet
layer, no Feishu notification dependency, no broad data-health ceremony before
every trade.

The user's chosen direction:

- New isolated directory: `F:\binance_futures_agent`.
- Deployment target: server `64.83.34.222`, root user, isolated path
  `/opt/binance-futures-agent`.
- Trading venue: Binance USD-M futures.
- Current trial capital: 30 USDT, after starting from an initial 100 USDT planning profile.
- Execution intent: live small-capital pilot, not only paper trading.
- First strategy focus: hot coins, especially Binance Square narratives.
- AI provider: DeepSeek for live use, with OpenAI Responses provider still
  available for fallback.
- Data-source preference: as many useful and allowed sources as possible.
- Binance API credentials are provided out of band; contents must be handled as
  secrets and never committed.

## Constraints

- **Isolation**: The project must not modify `F:\stock` or server-side existing
  services. Use its own repo, virtualenv, systemd unit, data directory, logs,
  and runtime files.
- **Capital**: Current trial capital is 30 USDT, so the live risk model
  must assume very small orders and high sensitivity to fees/slippage.
- **Execution**: Live mode is allowed, but default code paths must start in
  dry-run/test mode and require explicit environment configuration for live.
- **Risk**: Current trial defaults are max 5x leverage, max 12 USDT
  contract notional per position, max 0.3 USDT risk per trade, max 1 USDT
  daily loss, and max one concurrent position. Contract notional is not the
  same as initial margin; approximate margin is `notional / leverage`.
- **Exchange API**: Use official Binance USD-M futures APIs for market data,
  account state, and order placement.
- **Narrative APIs**: Binance Square reading may require browser automation,
  exports, or unofficial endpoints; implement this behind a replaceable
  collector interface and respect access limits.
- **AI**: AI provider calls must use structured JSON outputs and deterministic
  validation before a decision can become an order intent.
- **Secrets**: Store Binance, AI provider, cookie, and server credentials only
  in environment files or secret stores. Never write values to git or planning
  docs.
- **Deployment**: Server deployment must use a dedicated directory such as
  `/opt/binance-futures-agent`, a dedicated systemd unit, and gitignored runtime
  data under that directory.

## Current State

Phases 1 through 19 are complete and verified. The project is installable as an
isolated Python package, has a safe environment contract, official Binance USD-M
public market-data access, narrative/manual/RSS ingestion, normalized JSONL
evidence output, a local SQLite event store, deterministic replay/report
foundations, hot-coin candidate scoring, structured AI decision validation,
redacted AI journaling, dry-run/live risk-gated execution, signed Binance
execution helpers, reconciliation reports, deployment health checks, CLI smoke
commands, automated one-cycle trading runner, live systemd timer assets,
exchange-side protective order submission, AI provider selection, AI
timeout/backoff behavior, market-heat fallback narratives, pilot tradability
filtering, a cap-compatible pilot universe, fail-closed margin setup handling,
explicit configurable margin mode, explicit position mode, account-balance
preflight, DeepSeek support, and 30U/5x trial runtime caps.
Phase 20 also adds a read-only resume gate for timer reactivation.

The server deployment is installed under `/opt/binance-futures-agent` with a
dedicated env file and systemd units. Binance and AI credentials are configured
out of band. The active trial profile is 30 USDT account capital, 5x max
leverage, 12 USDT max position notional, 0.3 USDT max per-trade risk, 1 USDT max
daily loss, and 1 open position.

A real ZECUSDT LONG was submitted before or during the Phase 19 profile-change
window under the prior 3x settings. It filled at `467.68` for quantity `0.032`
and has exchange-visible stop-loss and take-profit algo orders. Live-status now
reports normal open orders and algo orders separately. The live timer is
currently disabled intentionally while that position is reviewed; automation can
be resumed after the position closes or after explicit operator approval to run
while the one-position cap blocks new entries.
The ZECUSDT position later cleared, and the current server `ops resume-check`
result is `resume_allowed` with zero active positions, zero normal open orders,
zero open algo orders, and no active AI backoff.
The live timer was re-enabled after that gate result; the first resumed cycle
and the next scheduled cycle both exited successfully with `submitted=false`
after the AI returned pass.

Recent live and public Binance filter checks showed that BTCUSDT and ETHUSDT can
be cap-incompatible under very small max-position-notional settings, while
several hot-coin symbols can currently fit. Candidate generation rejects
cap-incompatible symbols before AI calls instead of relying only on later
order-intent rejection. The default pilot universe uses: HYPEUSDT, SOLUSDT,
ZECUSDT, WLDUSDT, XRPUSDT, AVAXUSDT, BNBUSDT, DOGEUSDT, NEARUSDT, and ADAUSDT.

## Previous Milestone: v1.8 Position Mode And Entry Fail-Closed

**Goal:** Match the current Binance account position-side mode explicitly while
preserving the same small-capital risk limits.

**Target features:**
- Validate `BFA_POSITION_MODE` as `one_way` or `hedge`.
- Send Binance `positionSide` values in hedge mode.
- Persist entry-order failures as rejected, non-submitted evidence.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Previous Milestone: v1.9 Balance Preflight Gate

**Goal:** Avoid repeated live order attempts when the Binance USD-M futures
account has less available balance than the order intent's estimated initial
margin.

**Target features:**
- Read account `availableBalance` before margin setup or entry order placement.
- Reject insufficient available balance with `insufficient_available_balance`.
- Reject account balance read errors before entry order placement.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Previous Milestone: v1.10 DeepSeek Provider Switch

**Goal:** Switch live AI decisions to DeepSeek while preserving strict JSON
validation and all pilot risk caps.

**Target features:**
- Select AI provider with `BFA_AI_PROVIDER`.
- Use DeepSeek Chat Completions JSON mode.
- Extract fenced/prefixed JSON before schema validation.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Current Milestone: v1.11 30U Higher-Leverage Trial Profile

**Goal:** Configure the live system for a 30 USDT funded trial with a modest 5x
leverage ceiling while lowering absolute exposure.

**Target profile:**
- Account capital: 30 USDT.
- Max leverage: 5x.
- Max position notional: 12 USDT.
- Max risk per trade: 0.3 USDT.
- Max daily loss: 1 USDT.
- Max open positions: 1.

**Status:** Complete. Server caps are verified, live-status shows the current
ZECUSDT position and two protective algo orders, and the live timer is paused
for open-position review.

## Current Milestone: v1.12 Timer Resume Gate

**Goal:** Make timer resume decisions auditable with a read-only gate.

**Target features:**
- Add `ops resume-check`.
- Return `resume_allowed` only for clear exchange/backoff state.
- Return `keep_paused` for protected active positions.
- Return `urgent_attention` for unprotected active positions or orphan orders.

**Status:** Complete. Server resume check first returned `keep_paused` for the
protected ZECUSDT position, then returned `resume_allowed` after the position
and algo orders cleared. The timer was re-enabled, and the first resumed cycle
plus the next scheduled cycle submitted no order.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Create `F:\binance_futures_agent` | Keeps crypto futures work separate from the stock system. | Phase 1 complete |
| Use Python first | Binance/OpenAI clients, data processing, CLI tooling, and tests are straightforward in Python. | Phase 1 scaffold complete |
| Use Binance USD-M futures official APIs | The pilot trades USDT-margined contracts and needs supported market/order endpoints. | Phase 2 public market data complete |
| Start with hot-coin strategy | The user wants a controlled imitation of the Square/narrative-driven approach. | Phase 3 narrative collection complete |
| Use local event store before strategy assembly | Replayability and auditability are required before candidate scoring and live trading. | Phase 4 event store complete |
| Generate candidates before AI decisions | Deterministic scoring should filter and explain candidates before model evaluation. | Phase 5 candidate strategy complete |
| Use OpenAI for structured decisions, not direct raw orders | Keeps AI reasoning auditable and lets deterministic risk code retain final control. | Phase 6 complete |
| Keep deterministic risk/execution code in final control | Live mode must be explicit, risk-capped, persisted, and reconcilable before touching Binance. | Phase 7 complete |
| Deploy dry-run-first | Server deployment should prove isolation and health before any live trading mode is enabled. | Phase 8 complete |
| Keep LLM slow-path with backoff | API outages or slow responses should skip trading rather than block deterministic safety logic. | Phase 9 complete for activation |
| Track margin vs notional explicitly | Futures UI can show small margin such as 1 USDT, while Binance order filters validate contract notional and quantity. | Phase 9 follow-up |
| Require market reference price for AI trade geometry | The model should not invent executable prices from summaries alone. | Phase 11 complete |
| Filter for pilot tradability before AI | Hot symbols that cannot fit Binance minimum executable notional under the pilot cap should not consume AI/execution cycles. | Phase 12 complete |
| Use cap-compatible pilot universe | BTC/ETH can be impossible under a 20 USDT notional cap; the pilot needs tradable high-liquidity symbols without raising caps. | Phase 13 complete |
| Fail closed on margin setup errors | Binance account mode can reject isolated-margin setup; no entry should be submitted unless pre-entry setup succeeds. | Phase 14 complete |
| Make margin mode explicit | The live account is Multi-Assets/cross; using cross must be deliberate, validated, and still capped. | Phase 15 complete |
| Make position mode explicit | The live account can require hedge `positionSide`; using it must be deliberate, validated, and still capped. | Phase 16 complete |
| Add balance preflight before live orders | The live account can be unfunded even when order geometry is valid; avoid repeated exchange-side insufficient-margin errors. | Phase 17 complete |
| Add DeepSeek provider support | The previous OpenAI-compatible endpoint was intermittent and returned invalid JSON; DeepSeek can use Chat Completions JSON mode behind the same validation gates. | Phase 18 complete and deployed |
| Switch to 30U/5x trial profile | User wants to fund 30 USDT for a first live trial; higher leverage is allowed only with tighter absolute notional/loss/concurrency caps. | Phase 19 complete; timer paused for open-position review |
| Gate timer resume with exchange state | Timer resume should be a read-only decision based on live positions, open orders, algo orders, and AI backoff rather than manual JSON interpretation. | Phase 20 complete |
| Horizontal layer roadmap | User chose to build infrastructure layers before full assembly. | - Pending |
| Live small-capital pilot allowed | User explicitly chose live small本金 over testnet-only; current trial target is 30 USDT. | Phase 19 complete |

---
*Last updated: 2026-06-20 after verifying v1.12 timer resume gate.*
