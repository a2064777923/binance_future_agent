# Phase 5: Hot-Coin Candidate Strategy - Context

**Gathered:** 2026-06-19T17:00:00Z
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 ranks hot futures candidates from Phase 3 narrative records plus Phase
2 market snapshots, preferably through Phase 4 replay packets. It must produce
deterministic candidate records with scores, reason codes, data-quality notes,
and rejection reasons. It must not call OpenAI, place orders, inspect Binance
private account state, or deploy to the server.
</domain>

<decisions>
## Implementation Decisions

### Candidate Model
- **D-01:** Introduce a `CandidateSignal` dataclass with symbol, score,
  narrative score, market score, reason codes, data-quality notes, source event
  IDs, market event IDs, generated_at, and raw feature payload.
- **D-02:** Rejected candidates should be explicit records or report entries
  with symbol, rejection reason codes, and data-quality notes. Silent dropping
  is not acceptable.

### Scoring Inputs
- **D-03:** Narrative heat should count unique narrative records, source/author
  diversity, engagement values when present, and recency.
- **D-04:** Market score should use Phase 2 fields: price-change percent,
  quote volume, open interest / OI history, taker buy/sell ratio, funding, and
  volatility proxy from kline high/low/open/close where available.
- **D-05:** Missing features should reduce confidence and add data-quality
  notes, not crash the candidate generator.

### Filtering And Safety
- **D-06:** Candidate generation must reject stale narrative/market data,
  insufficient liquidity, excessive volatility, missing market confirmation,
  and unconfigured symbols before AI evaluation.
- **D-07:** Defaults should be suitable for the 100 USDT pilot: controlled
  symbols only, liquidity threshold, freshness limits, and top-N output.
- **D-08:** No candidate should imply side, leverage, entry, stop, target, or
  order intent. That belongs to the OpenAI/risk/execution phases.

### Replay Determinism
- **D-09:** Candidate generation should accept replay packets or `StoredEvent`
  dictionaries and return identical output for identical inputs.
- **D-10:** Scores must be deterministic and pure Python; no live network calls,
  wall-clock calls inside scoring, AI calls, randomization, or source collectors.

### Storage Boundary
- **D-11:** Phase 5 may persist generated candidate payloads to the Phase 4
  event store `candidates` category through explicit helper/CLI paths.
- **D-12:** Phase 5 should not alter the event-store schema.
</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/phases/02-binance-futures-market-data-layer/02-VERIFICATION.md`
- `.planning/phases/03-narrative-and-hot-coin-collection-layer/03-VERIFICATION.md`
- `.planning/phases/04-event-store-and-replay-foundation/04-VERIFICATION.md`
- `src/bfa/event_store/replay.py`
- `src/bfa/event_store/store.py`
- `src/bfa/narrative/models.py`
- `src/bfa/market/models.py`
</canonical_refs>

<deferred>
## Deferred Ideas

- OpenAI trade decisions are Phase 6.
- Risk sizing, margin, leverage, orders, and account reconciliation are Phase 7.
- Server deployment and scheduling are Phase 8.
</deferred>

---
*Phase: 5-Hot-Coin Candidate Strategy*
*Context gathered: 2026-06-19T17:00:00Z*

