# Phase 2: Binance Futures Market Data Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19T10:35:51Z
**Phase:** 2-Binance Futures Market Data Layer
**Areas discussed:** Binance API surface, candidate symbol scope, normalization/storage boundary, error handling/rate safety

---

## Binance API Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Official public USD-M market data only | REST market endpoints plus public WebSocket market streams; no private account/order APIs. | yes |
| Add private user-data stream now | Would mix market data with account/order state. | |
| Include narrative/Square sources now | Belongs to Phase 3. | |

**User's choice:** Auto-selected official public USD-M market data only.
**Notes:** This follows the roadmap boundary and the user's desire to keep this
pilot controlled before live execution.

---

## Candidate Symbol Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Small configurable symbol allowlist | Controlled hot-coin candidate set, safe for 100 USDT pilot development. | yes |
| Broad all-symbol scanner | More complete but easy to over-request and not needed before strategy ranking. | |
| Hardcoded single symbol | Too narrow for hot-coin workflows. | |

**User's choice:** Auto-selected small configurable allowlist.
**Notes:** Broad scanning can be added once request pacing and feature ranking
are validated.

---

## Normalization And Storage Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Typed normalized snapshots plus optional JSONL | Gives Phase 3/5 useful market objects without pre-building the event store. | yes |
| SQLite event store now | Durable event store is explicitly Phase 4. | |
| Raw exchange JSON only | Too weak for downstream strategy and replay planning. | |

**User's choice:** Auto-selected typed normalized snapshots with optional JSONL.
**Notes:** Snapshot shape must include source, event type, symbol, event time,
and received time.

---

## Error Handling And Rate Safety

| Option | Description | Selected |
|--------|-------------|----------|
| Structured errors plus conservative pacing hooks | Keeps endpoint/status/params visible without building a scheduler. | yes |
| Ignore request weights until later | Risky with public market-data endpoints. | |
| Full scheduler and retry service now | Larger than Phase 2 needs. | |

**User's choice:** Auto-selected structured errors plus conservative pacing hooks.
**Notes:** Unit tests should mock transports and not depend on live Binance.

## the agent's Discretion

- Exact module names and fixture layout.
- Whether to use standard-library transport directly or wrap it behind a small
  dependency-free interface.

## Deferred Ideas

- Narrative collection, durable SQLite event store, strategy ranking, OpenAI
  decisioning, order placement, and server deployment remain in later phases.
