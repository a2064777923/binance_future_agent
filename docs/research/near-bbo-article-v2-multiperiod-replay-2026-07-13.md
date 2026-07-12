# Near-BBO `article_v2` multi-period replay (2026-07-13)

## Scope

This is the missing historical validation layer for the public near-BBO
scalping improvement.  It evaluates the same `NearBboUniverse` and
`NearBboShadowLedger` used by the public shadow runner over several fixed UTC
windows while symbols compete for one shared 400U research account:

- 120U per intent;
- one global pending/open capacity of 3;
- one active intent per symbol;
- 15-minute historical warm-up;
- 3-second evaluations;
- 5-second quote TTL and 30-second maximum hold;
- post-window ticks are retained long enough to resolve pending/open intents.

The windows were fixed before reading outcomes:

| Window (UTC) | Watch symbols | Raw aggTrades |
| --- | ---: | ---: |
| 2026-06-30 00:00–03:00 | 7 | 1,303,777 |
| 2026-07-03 06:00–09:00 | 24 | 1,885,933 |
| 2026-07-05 12:00–15:00 | 24 | 1,149,536 |
| 2026-07-08 18:00–21:00 | 24 | 1,133,883 |
| 2026-07-10 15:00–18:00 | 24 | 1,526,924 |

The first window has only seven symbols because the local cache must contain
the 15-minute warm-up and post-window archive for every selected symbol.  The
other four windows have 24.  Selection is a stable SHA-256 ordering over the
intersection of cached symbols; it does not use outcomes, archive size, or
current 24-hour rankings.  There are 75 unique symbols across the five windows.

## BBO and fill-data boundary

The cached Binance USD-M daily `aggTrades` files contain millisecond trade
time, price, quantity, and `is_buyer_maker`.  They do **not** contain historical
bookTicker/L2 snapshots, cancellations, or authenticated queue position.

The replay therefore runs four predeclared synthetic-BBO sensitivities.  A
synthetic quote is centered on the latest trade, uses the declared spread and
combined bid/ask depth, and splits that depth using a bounded rolling
aggressor-flow imbalance.  Raw aggTrades still drive the queue-proxy ledger;
an entry fills only after opposing aggressor quantity consumes its synthetic
queue-ahead amount.  This is useful for timing, capacity, and sensitivity
analysis, but it is not an historical exchange fill reconstruction.

| Variant | Spread | Combined top notional | Flow imbalance scale |
| --- | ---: | ---: | ---: |
| `baseline` | 2.5 bps | 15,000U | 0.75 |
| `low_imbalance` | 2.5 bps | 15,000U | 0.35 |
| `deep_queue` | 2.5 bps | 30,000U | 0.75 |
| `wide_spread` | 4.0 bps | 15,000U | 0.75 |

## Aggregate result

All four scenarios remain negative.  The win-rate differences are not
meaningful profitability evidence because there are only 4–8 proxy fills per
scenario.

| Variant | Admitted | Proxy fills | Wins | Win rate | PF | Net PnL (U) | Positive windows | Max concurrent | Capacity dropped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` | 172 | 6 | 1 | 16.67% | 0.0316 | -0.6093 | 0/5 | 2 | 0 |
| `low_imbalance` | 144 | 8 | 1 | 12.50% | 0.0215 | -0.9061 | 0/5 | 2 | 0 |
| `deep_queue` | 172 | 4 | 1 | 25.00% | 0.0775 | -0.2367 | 0/5 | 2 | 0 |
| `wide_spread` | 172 | 4 | 2 | 50.00% | 0.0901 | -0.3083 | 1/5 | 2 | 0 |

The baseline produced 0.40 proxy fills per signal hour (six fills over 15
hours).  The lower-imbalance case produced the most fills at 0.53/hour, but
also the worst net result.  A wider synthetic spread happened to leave one
tiny positive window (+0.0016U), while the aggregate stayed negative and 95%
of its gross positive profit came from one BTCUSDT fill.  This is concentration,
not a robust edge.

The fixed global capacity was not the bottleneck in these windows:

- `eligible_proposal_count == selected_proposal_count` for every variant;
- capacity-selection drops were zero;
- the ledger never used more than two of the three pending/open seats.

The low activity therefore comes before capacity enforcement.  The largest
rejection counts were stale synthetic books, excessive short-window momentum,
CHOP, invalid trend-pullback depth, insufficient trade events, and low
direction score.  The result does not support loosening all gates blindly,
but it does identify stale-book handling and passive entry geometry as the next
research variables.

## Outcome diagnostics

For `baseline`, the six proxy fills split into three `max_hold_exit`, two
`evidence_adverse_selection`, and one `stop_loss`.  Mean favorable excursion
was only +3.41 bps versus mean adverse excursion -6.26 bps.  The modeled
round-trip cost is approximately 5.2 bps before any unmodeled queue effects,
so the observed favorable excursion is usually too small to pay for entry,
exit, and slippage.  This is consistent with the earlier forward shadow:
the problem is fill/entry selection bias, not simply a missing trailing stop.

The `deep_queue` sensitivity lowered fills and adverse excursion but remained
negative.  `low_imbalance` increased fills while worsening adverse excursion.
No variant produced a distributed positive result across dates and symbols.

## Performance and implementation

The replay reads each selected archive once and performs a k-way chronological
merge.  Raw rows are sent to the ledger only while a symbol has an active
intent.  Strategy features are updated from ordered one-second summaries, and
all four BBO variants share the same pass.  The five-window run processed
7,000,053 raw rows in about 162 seconds on the development machine.  Per
evaluation p95 latency was below 1.1ms in every window/variant (maximum observed
4.72ms), so the replay does not reproduce the earlier one-intent performance
bottleneck.

Run it locally with:

```bash
$env:PYTHONPATH=(Resolve-Path .\src).Path
python scripts/run_near_bbo_replay.py \
  --cache-dir runtime/aggTrades-cache \
  --output runtime/research/near_bbo_article_v2_multiperiod.json
```

The JSON result is runtime data and is intentionally not committed.  The
script has no signed Binance client, no order mutation, and no live/sentinel
side effects.

## Decision and next validation plan

This replay validates the intended architecture (multi-date, simultaneous
symbols, shared capital, global three-seat capacity) but does **not** validate
positive expectancy.  Do not enable `article_v2`, increase live risk, or train
a calibration artifact from these synthetic queue labels.

The next research steps are:

1. Re-run the same frozen windows against any period with authentic historical
   bookTicker/depth data, or align the self-collected raw-feed depth archive
   when enough dates are retained.
2. Compare signal eligibility with a book-freshness model that does not infer
   quote updates solely from trades; keep the comparison shadow-only.
3. Test entry-distance and queue-ahead distributions separately from direction
   scoring, with fees and adverse-selection labels unchanged.
4. Require unseen dates, at least 30 fills per candidate, positive PF after
   costs, and no single-symbol/date concentration before considering promotion.
5. Keep live, sentinel, manual-position handling, and the kill switch exactly
   as they are; this research path cannot authorize a restart.
