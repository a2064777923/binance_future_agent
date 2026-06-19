# Phase 4: Event Store And Replay Foundation - Context

**Gathered:** 2026-06-19T16:20:00Z
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 builds the durable local event store and replay foundation. It should
persist normalized inputs and later decision/execution artifacts in SQLite,
support deterministic historical-window reads, and compute basic outcome review
metrics. It must not implement hot-coin scoring, OpenAI decision calls, Binance
private account/order APIs, live execution, or server deployment.
</domain>

<decisions>
## Implementation Decisions

### Storage Engine
- **D-01:** Use Python standard-library `sqlite3` for the local event store.
  The project already has `BFA_DB_PATH`, and avoiding dependencies keeps server
  deployment lighter.
- **D-02:** Keep migrations as idempotent SQL executed by Python helpers rather
  than adding Alembic or another migration framework in Phase 4.
- **D-03:** Store rich payloads as JSON text where tables represent audit
  categories. This preserves flexibility for later AI/execution schemas while
  keeping queries simple.

### Tables And Event Categories
- **D-04:** Create tables for `narratives`, `market_snapshots`,
  `candidates`, `ai_decisions`, `order_intents`, `exchange_responses`,
  `fills`, `risk_state`, and `outcomes` to satisfy EVT-01.
- **D-05:** Add a generic append-only `events` table with `event_type`,
  `occurred_at`, `source`, `symbol`, `ref_id`, and JSON payload for replay
  ordering and audit continuity.
- **D-06:** Typed insert helpers should exist for Phase 2 market snapshots and
  Phase 3 narrative records immediately. Other future artifacts can use generic
  JSON helpers until their phases add stricter models.

### Replay Boundary
- **D-07:** Phase 4 replay means deterministic ordered retrieval of stored
  historical windows and a stable replay input packet. Candidate scoring itself
  belongs to Phase 5.
- **D-08:** Replay ordering should be deterministic by timestamp, event ID, and
  table/source tie-breakers. Tests must prove repeated reads return the same
  sequence.
- **D-09:** Replay code should be pure/offline and should never call Binance,
  OpenAI, source collectors, or order APIs.

### Review Reports
- **D-10:** Review reports should compute metrics from stored fills/outcomes:
  trade count, win rate, gross/net PnL, fees, slippage, expectancy, max
  drawdown, and reason-code performance where available.
- **D-11:** Missing data should produce zero/empty metrics rather than failing,
  because early phases may have partial dry-run records.

### Safety And Isolation
- **D-12:** SQLite files are runtime artifacts and remain gitignored. Unit tests
  must use temporary database files or in-memory DBs.
- **D-13:** Phase 4 must not read the Binance key file, server credentials,
  cookies, OpenAI keys, or `F:\stock`.
</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/phases/02-binance-futures-market-data-layer/02-VERIFICATION.md`
- `.planning/phases/03-narrative-and-hot-coin-collection-layer/03-VERIFICATION.md`
- `src/bfa/market/models.py`
- `src/bfa/narrative/models.py`
- `src/bfa/config.py`
- `.env.example`
</canonical_refs>

<code_context>
## Existing Code Insights

- Phase 2 market snapshots expose `to_dict()`.
- Phase 3 narrative records expose `to_dict()`.
- Config already exposes `BFA_DB_PATH`.
- Tests use `unittest`, temporary files/directories, and no live network.
- CLI is a thin `argparse` module with injectable factories.
</code_context>

<deferred>
## Deferred Ideas

- Candidate scoring belongs to Phase 5.
- OpenAI request/response schema belongs to Phase 6.
- Binance private account/order reconciliation belongs to Phase 7.
- Server migration/deployment execution belongs to Phase 8.
</deferred>

---
*Phase: 4-Event Store And Replay Foundation*
*Context gathered: 2026-06-19T16:20:00Z*

