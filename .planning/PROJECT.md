# Binance Futures Agent

## What This Is

Binance Futures Agent is an isolated crypto futures trading system for Binance
USD-M contracts. It watches hot coins from Binance Square and other narrative
sources, confirms them with futures-market anomalies, asks an OpenAI model for
structured trade decisions, and can run a tightly capped 100 USDT live pilot on
a dedicated server.

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
- Phase 6 validated compact OpenAI decision context packets, strict structured
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

### Active

- [x] Collect Binance USD-M futures market data needed for hot-coin filtering.
- [x] Collect narrative and hotness signals from Binance Square plus fallback
  social/news sources where access is allowed.
- [x] Record every candidate, AI decision, order intent, exchange response,
  fill, and outcome in a replayable local event store.
- [x] Rank candidate symbols by narrative heat, liquidity, price momentum, open
  interest change, taker flow, funding state, and volatility.
- [x] Use OpenAI to produce structured trade decisions with entry, invalidation,
  stop, target, time limit, and confidence.
- [x] Implement risk-capped Binance live execution for a 100 USDT pilot account.
- [x] Deploy on server `64.83.34.222` under a project-isolated directory and
  systemd unit without modifying existing services.
- [ ] Improve live AI decision quality so `trade` decisions include executable
  entry, stop, and target prices derived from market reference data.
- [ ] Capture LVA-05 protective-order evidence after the first submitted live
  entry, or prove the fail-closed emergency path if protective orders fail.

### Out of Scope

- Full Hermes-style review workflow - too heavy for this faster crypto pilot.
- Real-money scaling above the 100 USDT pilot - requires separate evidence and
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
- Initial capital: 100 USDT.
- Execution intent: live small-capital pilot, not only paper trading.
- First strategy focus: hot coins, especially Binance Square narratives.
- AI provider: OpenAI.
- Data-source preference: as many useful and allowed sources as possible.
- Binance API credentials are provided out of band; contents must be handled as
  secrets and never committed.

## Constraints

- **Isolation**: The project must not modify `F:\stock` or server-side existing
  services. Use its own repo, virtualenv, systemd unit, data directory, logs,
  and runtime files.
- **Capital**: Initial account capital is 100 USDT, so the first live risk model
  must assume very small orders and high sensitivity to fees/slippage.
- **Execution**: Live mode is allowed, but default code paths must start in
  dry-run/test mode and require explicit environment configuration for live.
- **Risk**: Initial intelligent defaults are max 3x leverage, max 20 USDT
  contract notional per position, max 1 USDT risk per trade, max 3 USDT daily
  loss, and max two concurrent positions. Contract notional is not the same as
  initial margin; approximate margin is `notional / leverage`.
- **Exchange API**: Use official Binance USD-M futures APIs for market data,
  account state, and order placement.
- **Narrative APIs**: Binance Square reading may require browser automation,
  exports, or unofficial endpoints; implement this behind a replaceable
  collector interface and respect access limits.
- **AI**: OpenAI calls must use structured JSON outputs and deterministic
  validation before a decision can become an order intent.
- **Secrets**: Store Binance, OpenAI, cookie, and server credentials only in
  environment files or secret stores. Never write values to git or planning docs.
- **Deployment**: Server deployment must use a dedicated directory such as
  `/opt/binance-futures-agent`, a dedicated systemd unit, and gitignored runtime
  data under that directory.

## Current State

Phases 1 through 10 are complete and verified. The project is installable as an
isolated Python package, has a safe environment contract, official Binance USD-M
public market-data access, narrative/manual/RSS ingestion, normalized JSONL
evidence output, a local SQLite event store, deterministic replay/report
foundations, hot-coin candidate scoring, OpenAI structured decision validation,
redacted AI journaling, dry-run/live risk-gated execution, signed Binance
execution helpers, reconciliation reports, deployment health checks, CLI smoke
commands, automated one-cycle trading runner, live systemd timer assets,
exchange-side protective order submission, OpenAI-compatible base URL
configuration, AI timeout/backoff behavior, market-heat fallback narratives, and
158 passing unit tests. The server deployment is installed under
`/opt/binance-futures-agent` with a dedicated env file and systemd units. Binance
and OpenAI credentials are configured out of band, the live timer is enabled and
active, and a candidate-driven live cycle has reached OpenAI and returned
pass/no submission. The OpenAI-compatible endpoint is intermittent under the
5 second timeout; timeouts enter `openai_backoff` and skip execution.
Recent live cycles also show a second quality issue: the model can return
`decision=trade` while leaving entry, stop, and target null. Local validation
correctly rejects those decisions, but the prompt/context should be improved so
the model either returns an executable decision with complete prices or returns
`pass`.

## Current Milestone: v1.3 Decision Robustness

**Goal:** Improve the live AI decision layer so executable trades carry complete
reference-price-based entry, stop, and target data, while non-executable model
outputs fail closed without polluting live evidence.

**Target features:**
- Include latest market reference price in AI decision context.
- Tighten decision instructions around complete trade geometry versus pass.
- Classify incomplete trade outputs as fail-closed AI validation, not live trade
  evidence.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

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
| Require market reference price for AI trade geometry | The model should not invent executable prices from summaries alone. | Phase 11 active |
| Horizontal layer roadmap | User chose to build infrastructure layers before full assembly. | - Pending |
| Live small-capital pilot allowed | User explicitly chose live small本金 over testnet-only, with 100 USDT initial capital. | Phase 9 active on server |

---
*Last updated: 2026-06-20 after starting v1.3 decision robustness.*
