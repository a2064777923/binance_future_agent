# Roadmap: Binance Futures Agent

**Created:** 2026-06-19
**Mode:** standard
**Structure:** Horizontal layers

## Overview

This roadmap builds the trading system layer by layer: isolation and config,
official exchange data, narrative ingestion, event store/replay, strategy, AI
decisions, execution, and server deployment.

## Phases

### Phase 1: Isolated Project Foundation

**Goal:** Establish the independent repository, config contract, secret hygiene,
and developer workflow.

**Requirements:** ISO-01, ISO-02, ISO-03, CFG-01, CFG-02, CFG-03

**Success Criteria:**

1. The repo is initialized at `F:\binance_futures_agent` with no dependency on
   `F:\stock`.

2. `.env.example` documents all required settings without secret values.
3. Config validation can distinguish dry-run, testnet, and live requirements.
4. Secret-redaction behavior is covered by tests.

### Phase 2: Binance Futures Market Data Layer

**Goal:** Build official Binance USD-M futures data access and normalization.

**Requirements:** MKT-01, MKT-02, MKT-03, MKT-04

**Success Criteria:**

1. The CLI can fetch exchange metadata and symbol filters.
2. The collector can fetch required REST market metrics for selected symbols.
3. WebSocket stream handling can receive and normalize live market events.
4. Market snapshots are stored with source, timestamp, and symbol metadata.

### Phase 3: Narrative And Hot-Coin Collection Layer

**Goal:** Ingest Binance Square and fallback narrative sources behind pluggable
collector adapters.

**Requirements:** NAR-01, NAR-02, NAR-03, NAR-04

**Success Criteria:**

1. At least one Binance Square ingestion path works without hardcoding secrets.
2. Manual/export ingestion works as a fallback for Square or social data.
3. Narrative records normalize symbol mentions, engagement, source, and time.
4. Duplicate narrative events are collapsed before scoring.

### Phase 4: Event Store And Replay Foundation

**Goal:** Persist all input and decision events in a replayable local store.

**Requirements:** EVT-01, EVT-02, EVT-03

**Success Criteria:**

1. SQLite migrations create tables for narratives, market snapshots,
   candidates, AI decisions, orders, fills, risk state, and outcomes.

2. Stored historical windows can be replayed through deterministic candidate
   generation.

3. Review reports compute win rate, expectancy, drawdown, fees/slippage, and
   reason-code performance.

### Phase 5: Hot-Coin Candidate Strategy

**Goal:** Rank hot futures candidates from narrative heat plus market anomalies.

**Requirements:** STR-01, STR-02, STR-03, STR-04

**Success Criteria:**

1. Candidate scoring combines narrative heat, liquidity, price momentum, volume
   spike, OI change, taker flow, funding, and volatility.

2. Each candidate includes reason codes and data-quality notes.
3. Untradeable or stale candidates are rejected before AI evaluation.
4. Candidate generation is deterministic under replay.

### Phase 6: OpenAI Decision Layer

**Goal:** Convert candidates into validated AI trade decisions.

**Requirements:** AI-01, AI-02, AI-03, AI-04

**Success Criteria:**

1. The AI context packet is compact, redacted, and reproducible.
2. OpenAI responses conform to a JSON schema with entry, stop, target,
   confidence, hold time, and reasons.

3. Invalid or risk-inconsistent AI responses are rejected.
4. Requests and responses are journaled with secret-safe redaction.

### Phase 7: Risk-Gated Binance Execution

**Goal:** Add dry-run and explicit live order execution for the 100 USDT pilot.

**Requirements:** EXE-01, EXE-02, EXE-03, EXE-04, EXE-05

**Success Criteria:**

1. Dry-run mode creates order intents without submitting exchange orders.
2. Live mode requires explicit config and refuses to run with missing risk
   limits or active kill switch.

3. Execution enforces isolated margin, max 3x leverage, max 20 USDT notional,
   max 1 USDT risk per trade, max 3 USDT daily loss, max two open positions,
   and cooldown.

4. Orders respect Binance symbol filters and are reconciled against account
   state after startup and stream interruptions.

### Phase 8: Isolated Server Deployment

**Goal:** Deploy the agent to `64.83.34.222` without affecting existing projects.

**Requirements:** DEP-01, DEP-02, DEP-03, DEP-04

**Success Criteria:**

1. Deployment uses `/opt/binance-futures-agent`, `/etc/binance-futures-agent/env`,
   and a dedicated `binance-futures-agent.service`.

2. Existing server directories, services, cron jobs, databases, and stock
   project files are not modified.

3. Health checks verify config, Binance, OpenAI, DB, risk state, and kill switch.
4. The service can run one dry-run cycle before live mode is enabled.

## Requirement Coverage

- v1 requirements: 34
- Mapped: 34
- Unmapped: 0

## Next Step

Run:

```bash
$gsd-discuss-phase 4
```
