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

### Active

- [x] Collect Binance USD-M futures market data needed for hot-coin filtering.
- [x] Collect narrative and hotness signals from Binance Square plus fallback
  social/news sources where access is allowed.
- [x] Record every candidate, AI decision, order intent, exchange response,
  fill, and outcome in a replayable local event store.
- [ ] Rank candidate symbols by narrative heat, liquidity, price momentum, open
  interest change, taker flow, funding state, and volatility.
- [ ] Use OpenAI to produce structured trade decisions with entry, invalidation,
  stop, target, time limit, and confidence.
- [ ] Implement risk-capped Binance live execution for a 100 USDT pilot account.
- [ ] Deploy on server `64.83.34.222` under a project-isolated directory and
  systemd unit without modifying existing services.

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
- Binance API key file exists locally at `F:\币安API密鈅.txt`; contents must be
  handled as secrets and never committed.

## Constraints

- **Isolation**: The project must not modify `F:\stock` or server-side existing
  services. Use its own repo, virtualenv, systemd unit, data directory, logs,
  and runtime files.
- **Capital**: Initial account capital is 100 USDT, so the first live risk model
  must assume very small orders and high sensitivity to fees/slippage.
- **Execution**: Live mode is allowed, but default code paths must start in
  dry-run/test mode and require explicit environment configuration for live.
- **Risk**: Initial intelligent defaults are max 3x leverage, max 20 USDT
  notional per position, max 1 USDT risk per trade, max 3 USDT daily loss, and
  max two concurrent positions.
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

Phases 1 through 4 are complete and verified. The project is installable as an
isolated Python package, has a safe environment contract, official Binance USD-M
public market-data access, narrative/manual/RSS ingestion, normalized JSONL
evidence output, a local SQLite event store, deterministic replay/report
foundations, CLI smoke commands, and 88 passing unit tests. Phase 5 should build
the hot-coin candidate scoring strategy on top of stored narrative and market
inputs.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Create `F:\binance_futures_agent` | Keeps crypto futures work separate from the stock system. | Phase 1 complete |
| Use Python first | Binance/OpenAI clients, data processing, CLI tooling, and tests are straightforward in Python. | Phase 1 scaffold complete |
| Use Binance USD-M futures official APIs | The pilot trades USDT-margined contracts and needs supported market/order endpoints. | Phase 2 public market data complete |
| Start with hot-coin strategy | The user wants a controlled imitation of the Square/narrative-driven approach. | Phase 3 narrative collection complete |
| Use local event store before strategy assembly | Replayability and auditability are required before candidate scoring and live trading. | Phase 4 event store complete |
| Use OpenAI for structured decisions, not direct raw orders | Keeps AI reasoning auditable and lets deterministic risk code retain final control. | - Pending |
| Horizontal layer roadmap | User chose to build infrastructure layers before full assembly. | - Pending |
| Live small-capital pilot allowed | User explicitly chose live small本金 over testnet-only, with 100 USDT initial capital. | - Pending |

---
*Last updated: 2026-06-19 after Phase 4 verification.*
