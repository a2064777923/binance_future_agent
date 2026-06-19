# Requirements: Binance Futures Agent

**Defined:** 2026-06-19
**Core Value:** Turn hot-coin narrative momentum into auditable, risk-capped Binance futures signals and small live trades without contaminating existing projects or losing control of downside.

## v1 Requirements

### Project Isolation

- [x] **ISO-01**: The project exists in `F:\binance_futures_agent` as an independent git repository.
- [x] **ISO-02**: The project includes gitignore rules that exclude secrets, runtime data, logs, local databases, and raw exports.
- [x] **ISO-03**: The project documents server deployment paths that do not overlap existing projects.

### Configuration And Secrets

- [x] **CFG-01**: User can configure Binance, OpenAI, runtime mode, risk limits, and data paths through env/config files without committing secret values.
- [x] **CFG-02**: The system can validate required config for dry-run, testnet, and live modes.
- [x] **CFG-03**: The system can redact secret values in logs, diagnostics, and config-check output.

### Binance Market Data

- [x] **MKT-01**: User can fetch Binance USD-M exchange metadata and symbol filters.
- [x] **MKT-02**: User can fetch ticker, kline, funding, open interest, long/short, and taker buy/sell data for candidate symbols.
- [x] **MKT-03**: User can subscribe to relevant WebSocket streams for live candidate monitoring.
- [x] **MKT-04**: The system stores normalized market snapshots with timestamps and source metadata.

### Narrative Collection

- [x] **NAR-01**: User can ingest Binance Square hot-coin data through at least one supported collector path.
- [x] **NAR-02**: User can ingest fallback narrative sources such as manual exports, RSS/news, X, or Telegram when configured.
- [x] **NAR-03**: The system can normalize narrative records into symbols, text, source, engagement, and timestamp fields.
- [x] **NAR-04**: The system can deduplicate repeated posts or duplicate symbol mentions before scoring.

### Candidate Strategy

- [x] **STR-01**: User can generate ranked hot-coin candidates from narrative heat and futures-market features.
- [x] **STR-02**: Each candidate includes explicit reason codes and data-quality notes.
- [x] **STR-03**: The system can reject candidates that fail liquidity, volatility, min-notional, or data-freshness filters.
- [x] **STR-04**: Candidate generation is deterministic and replayable from stored inputs.

### OpenAI Decision Layer

- [x] **AI-01**: User can send a compact candidate context packet to an OpenAI model.
- [x] **AI-02**: The model response is parsed as structured JSON with side, decision, confidence, entry, stop, target, hold time, and reasons.
- [x] **AI-03**: Invalid, incomplete, or risk-inconsistent model responses are rejected before execution.
- [x] **AI-04**: Every model request and redacted response is journaled for later review.

### Event Store And Replay

- [x] **EVT-01**: The system stores narratives, market snapshots, candidates, AI decisions, order intents, exchange responses, fills, and outcomes in a local event store.
- [x] **EVT-02**: User can replay a historical window to regenerate candidates and compare decisions against outcomes.
- [x] **EVT-03**: User can generate a review report with win rate, expectancy, drawdown, fee/slippage impact, and reason-code performance.

### Risk And Execution

- [x] **EXE-01**: User can run the system in dry-run mode without placing exchange orders.
- [x] **EXE-02**: User can enable live mode explicitly for Binance USD-M futures.
- [x] **EXE-03**: Live mode enforces isolated margin, leverage cap, position notional cap, per-trade risk cap, daily loss cap, max open positions, cooldown, and kill switch checks.
- [x] **EXE-04**: The executor can place, inspect, and cancel Binance futures orders while respecting symbol filters.
- [x] **EXE-05**: The executor reconciles local state against Binance account/order state after startup and after stream interruptions.

### Server Deployment

- [x] **DEP-01**: User can deploy the project to server `64.83.34.222` under `/opt/binance-futures-agent`.
- [x] **DEP-02**: Deployment creates or documents a dedicated env file, virtualenv, data directory, log directory, runtime directory, and systemd unit.
- [x] **DEP-03**: Deployment does not modify existing project directories, services, cron jobs, or databases on the server.
- [x] **DEP-04**: User can run server-side health checks for config, Binance connectivity, OpenAI connectivity, database access, risk state, and kill switch.

## v2 Requirements

### Product Surface

- **UI-01**: User can view candidates, decisions, positions, and performance in a web dashboard.
- **NOTIFY-01**: User can receive concise Telegram/Feishu alerts for entries, exits, and kill-switch events.
- **LEARN-01**: User can generate AI-assisted prompt/config improvement proposals from trade journals.

### Strategy Expansion

- **STR2-01**: User can run additional strategies beyond hot coins, such as funding squeeze, liquidation cascade, or trend continuation.
- **STR2-02**: User can compare strategies through shared replay metrics.
- **XEX-01**: User can add non-Binance exchanges as data sources without enabling cross-exchange execution.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Trading above 100 USDT pilot capital | Requires separate evidence and explicit approval. |
| Full Hermes-style review workflow | Too heavy for the desired crypto pilot. |
| Automatic strategy self-promotion | Dangerous for live futures; changes must be explicit. |
| Cross-exchange execution | Adds complexity before Binance-only behavior is validated. |
| Guaranteed replication of public trader returns | Public screenshots are incomplete and not a strategy contract. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ISO-01 | Phase 1 | Complete |
| ISO-02 | Phase 1 | Complete |
| ISO-03 | Phase 1 | Complete |
| CFG-01 | Phase 1 | Complete |
| CFG-02 | Phase 1 | Complete |
| CFG-03 | Phase 1 | Complete |
| MKT-01 | Phase 2 | Complete |
| MKT-02 | Phase 2 | Complete |
| MKT-03 | Phase 2 | Complete |
| MKT-04 | Phase 2 | Complete |
| NAR-01 | Phase 3 | Complete |
| NAR-02 | Phase 3 | Complete |
| NAR-03 | Phase 3 | Complete |
| NAR-04 | Phase 3 | Complete |
| EVT-01 | Phase 4 | Complete |
| EVT-02 | Phase 4 | Complete |
| EVT-03 | Phase 4 | Complete |
| STR-01 | Phase 5 | Complete |
| STR-02 | Phase 5 | Complete |
| STR-03 | Phase 5 | Complete |
| STR-04 | Phase 5 | Complete |
| AI-01 | Phase 6 | Complete |
| AI-02 | Phase 6 | Complete |
| AI-03 | Phase 6 | Complete |
| AI-04 | Phase 6 | Complete |
| EXE-01 | Phase 7 | Complete |
| EXE-02 | Phase 7 | Complete |
| EXE-03 | Phase 7 | Complete |
| EXE-04 | Phase 7 | Complete |
| EXE-05 | Phase 7 | Complete |
| DEP-01 | Phase 8 | Complete |
| DEP-02 | Phase 8 | Complete |
| DEP-03 | Phase 8 | Complete |
| DEP-04 | Phase 8 | Complete |

**Coverage:**

- v1 requirements: 34 total
- Mapped to phases: 34
- Unmapped: 0

---
*Requirements defined: 2026-06-19*
*Last updated: 2026-06-20 after Phase 8 verification*
