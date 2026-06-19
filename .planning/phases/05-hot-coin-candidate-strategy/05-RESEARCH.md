# Phase 5 Research: Hot-Coin Candidate Strategy

**Researched:** 2026-06-19
**Status:** Ready for planning

## Executive Summary

Build a deterministic feature extractor and candidate scorer over replay events.
The first useful strategy should combine narrative heat with market confirmation
and conservative rejection gates:

- narrative mention count and source diversity
- engagement totals when available
- recency/freshness
- price momentum
- quote volume/liquidity
- open-interest change
- taker-flow bias
- funding state
- volatility proxy

Candidate generation should remain a ranking/filtering layer. It should not
pick long/short direction, entries, stops, targets, leverage, or order sizes.

## Feature Strategy

Narrative features:

- `mention_count`
- `source_count`
- `author_count`
- `engagement_score`
- `latest_narrative_at`
- quality flags from narrative records

Market features:

- `price_change_percent` from ticker snapshots
- `quote_volume` from ticker snapshots
- `open_interest` and `sum_open_interest_value`
- `taker_buy_sell_ratio`
- `funding_rate`
- `kline_range_percent` from high/low/open/close

## Scoring Strategy

Use a simple additive deterministic score:

- Narrative score: mentions + source diversity + author diversity + engagement
- Market score: liquidity + momentum + OI + taker-flow + sane funding +
  volatility proxy
- Final score: weighted sum, capped to a predictable range

Weights should live in a config dataclass so tests can pin expected values.

## Rejection Strategy

Reject candidates before AI if:

- symbol is not in configured allowlist
- no narrative evidence
- no market confirmation
- market or narrative data is stale
- quote volume is below threshold
- volatility is above threshold

Every rejection should include reason codes and quality notes.

## Test Strategy

Use static replay packets with narrative and market event payloads. Tests should
prove deterministic output, ranking order, feature extraction, rejection reasons,
and event-store persistence of candidate payloads.

