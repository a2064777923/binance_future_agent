# Phase 4 Research: Event Store And Replay Foundation

**Researched:** 2026-06-19
**Status:** Ready for planning

## Executive Summary

Use dependency-free SQLite with idempotent migrations, typed insert/query helpers
for records already produced by Phases 2 and 3, generic JSON artifact tables for
future phases, deterministic replay-window queries, and small review-report
metrics over fills/outcomes.

The safest architecture is a narrow `bfa.event_store` package:

- `migrations.py` owns schema creation and versioning.
- `store.py` owns connection handling and insert/query helpers.
- `models.py` owns light result dataclasses.
- `replay.py` owns deterministic historical-window reconstruction.
- `report.py` owns review metrics.

## SQLite Approach

SQLite fits the pilot because it is durable, local, available in Python's
standard library, easy to test with temporary files, and deployable on the VPS
without another service.

Recommended defaults:

- Enable foreign keys.
- Use WAL mode for file databases where supported.
- Store timestamps as ISO strings supplied by upstream records.
- Store payloads as JSON text and parse at the Python boundary.
- Add indexes on time, symbol, source, and ref IDs used for replay.

## Schema Strategy

Create the category tables promised by EVT-01 even if later phases fill some of
them:

- `narratives`
- `market_snapshots`
- `candidates`
- `ai_decisions`
- `order_intents`
- `exchange_responses`
- `fills`
- `risk_state`
- `outcomes`
- `events`

The `events` table provides a single ordered replay stream. Typed tables
preserve category-specific query convenience.

## Replay Strategy

Phase 4 should not score candidates yet. It should provide deterministic replay
inputs:

- Events between `start` and `end`.
- Optional symbol filter.
- Stable ordering by `occurred_at`, `id`, and source category.
- JSON payloads round-tripped into dictionaries.

Phase 5 can consume this replay packet to generate candidates deterministically.

## Review Metrics

Reports can compute useful performance metrics as soon as outcomes/fills exist:

- total trades
- wins/losses
- win rate
- gross PnL
- fees
- slippage
- net PnL
- expectancy
- max drawdown
- reason-code aggregate PnL/count

Empty stores should return zeros and empty dictionaries.

## Test Strategy

Use temporary SQLite database files. Tests should cover:

- Migration idempotence.
- Required tables and schema version.
- Insert/query of narrative and market snapshot records from existing dataclasses.
- Generic future artifact inserts.
- Replay ordering and symbol/time filters.
- Review metrics with synthetic outcomes/fills.
- CLI smoke for database init and report generation if CLI is included.

