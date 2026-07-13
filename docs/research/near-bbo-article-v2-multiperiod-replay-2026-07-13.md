# Near-BBO `article_v2` corrected fill audit (2026-07-13)

## Verdict

The earlier statement that only 6 of 172 admitted quotes filled was not a
credible estimate of exchange fill rate. It was the result of a five-second
quote lifetime and a deliberately pessimistic model that required trades to
consume the full synthetic displayed queue without modeling cancellations.
It is superseded by this report.

After correcting the replay contract and testing a fill envelope, the low-fill
claim disappears but the profitability conclusion does not:

- across five outcome-blind cached windows, 117 of 176 displayed-queue
  admissions received at least one price-and-aggressor-side match within 20
  seconds;
- after quantizing entries to a causally inferred price grid, the same run
  produced 90 fills under strict trade-through-or-full-queue, 98 under 10%
  queue, 108 under 1% queue, and 116 under the optimistic touch upper bound;
- the touch upper bound still had only 32 wins from 116 fills, PF 0.1939, and
  -7.2958U net PnL;
- prior-only market-ranked windows and self-collected individual ticks also
  remained negative.

The framework was too pessimistic about fills. The current `article_v2` entry
and exit combination is independently negative after costs. Neither finding
should be hidden by the other.

No live service, sentinel, exchange order, manual position, or kill-switch
state was changed. This is offline research and does not authorize a restart.

## What was wrong in the previous replay

| Issue | Effect | Correction |
| --- | --- | --- |
| Five-second replay TTL versus the intended 20-second micro quote | Expired orders before the intended contract ended | Default TTL is now 20 seconds; the post-window tail covers TTL plus hold time |
| Last trade treated as synthetic midpoint | A taker buy/sell print was displaced from the side where it normally executed | Taker buys anchor the synthetic ask and taker sells anchor the synthetic bid |
| One full synthetic displayed queue treated as truth | Required roughly 8,000-13,000U of queue to trade without any cancellations | Report touch, 1%, 10%, and full displayed-queue scenarios as an envelope |
| No per-order touch/queue diagnostics | An untouched quote and a touched-but-queue-blocked quote looked identical | Labels now retain price touches, matching aggressor count/quantity/notional, displayed/applied/remaining queue, and consumed fraction |
| Queue fraction leaked into strategy fill probability and ranking | Fill scenarios could select different quotes before the fill model was applied | Strategy ranking always uses the same displayed-queue geometry; queue fraction is applied only in the shadow ledger after admission |
| Fixed cached symbols treated as market opportunity discovery | Could not show whether better prior-only market selection changed the result | Replay can consume hourly schedule-v2 market rankings built only from completed earlier bars |
| Public aggregate trades treated as equivalent to live individual prints | Aggregate rows preserve volume but coarsen event counts and intra-order timing | A matched self-collected individual-tick comparison is reported separately |
| Prices could pass a synthetic limit while the order remained queue-blocked | Ignored price-time priority and materially undercounted fills | Infer tick size causally from completed one-second trade prices; quantize BBO; fill on strict correct-side trade-through or same-price queue consumption |
| Stop gaps used the ideal trigger price | Understated losses after adverse sweeps | Stop exits use the observed worse trade plus slippage |
| Max-hold used the previous trade | Could exit on a stale price and omit the deadline trade from MFE/MAE | The trade that reaches the deadline updates price and excursion before closing |

Fill scenarios can still diverge after admission: a scenario that fills an
order occupies a shared seat and excludes that symbol until the position
closes, while a scenario that expires it can consider another quote. That is a
real downstream consequence of the fill assumption. The corrected code only
prevents the queue assumption from changing the initial strategy score.

## Corrected replay contract

All corrected runs use:

- 400U research capital;
- 120U notional per intent;
- at most three pending/open intents, so maximum modeled concurrent notional is
  360U and 40U remains unallocated;
- one active intent per symbol;
- 15-minute warm-up and three-second evaluation cadence;
- 20-second quote TTL, 30-second maximum hold, and a 55-second post-window
  resolution tail;
- `article_v2` regime/scout signals;
- 2.5 bps synthetic spread and 15,000U combined synthetic top depth;
- aggressor-side quote anchoring;
- a causally inferred per-symbol tick grid from already completed one-second
  trade prices, with passive bid rounded down and ask rounded up;
- the same fee, slippage, stop, target, and evidence-exit accounting in every
  fill scenario.

The four fill scenarios are not exchange reconstructions:

| Scenario | Fill rule | Interpretation |
| --- | --- | --- |
| `touch_upper_bound` | First correct-side aggressive trade at or through the limit | Optimistic upper bound; ignores queue |
| `queue_1pct` | Strict correct-side trade-through, or correct aggressor volume consumes 1% of displayed queue at the limit | Light-queue sensitivity |
| `queue_10pct` | Strict trade-through, or 10% same-price queue consumption | Moderate-queue sensitivity |
| `displayed_queue` | Strict trade-through, or all displayed same-price queue is consumed | Conservative same-price queue with price-time priority |

Public `aggTrades` and the extracted individual ticks are trade-only sources.
Neither contains historical BBO/L2 updates, cancellations, or authenticated
queue priority. A correct-side touch is necessary for a passive fill but is
not proof that the exchange would have filled our order.

## Five-window outcome-blind cached-symbol result

The frozen UTC windows remain 2026-06-30 00:00-03:00, 2026-07-03
06:00-09:00, 2026-07-05 12:00-15:00, 2026-07-08 18:00-21:00, and
2026-07-10 15:00-18:00. Stable SHA-256 selection over cache-complete symbols
covered 75 unique symbols and 7,012,504 public aggregate trades. It did not use
outcomes or current 24-hour rankings.

| Fill scenario | Admitted | Correct-side touch | Filled | Wins | Win rate | PF | Net PnL (U) | Positive windows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `displayed_queue` | 176 | 117 | 90 | 22 | 24.44% | 0.1568 | -7.1111 | 0/5 |
| `queue_10pct` | 176 | 117 | 98 | 27 | 27.55% | 0.1549 | -7.4154 | 0/5 |
| `queue_1pct` | 176 | 116 | 108 | 31 | 28.70% | 0.1849 | -7.2158 | 0/5 |
| `touch_upper_bound` | 176 | 116 | 116 | 32 | 27.59% | 0.1939 | -7.2958 | 0/5 |

The slight admission/touch differences are caused by the shared-capacity
lifecycle described above. They are not caused by different strategy queue
scores.

The displayed-queue/trade-through scenario averaged +4.78 bps MFE and -6.00
bps MAE. Modeled round-trip cost is about 5.2 bps, so the average favorable
excursion does not cover cost before authentic queue uncertainty. Its 22
winning fills averaged +0.0601U while 68 losing fills averaged -0.1240U. With
that payoff shape, the break-even win rate is about 67.4%; aiming for 70% is
compensating for compressed winners rather than proving a durable edge.

Only 9 of 90 fills reached take profit. Exit reasons were 40
`evidence_adverse_selection`, 16 `evidence_profit_lock`, 18 `max_hold_exit`, 7
`stop_loss`, and 9 `take_profit`. Eighty-three of the 90 fills followed strict
trade-through, direct evidence that passive fills are concentrated when price
is already moving adversely. Entry adverse selection and an exit policy that
often realizes small outcomes both require further work.

## Prior-only market-ranked result

Three hourly schedule-v2 runs selected 24 symbols from completed earlier bars
before each signal hour. The union of scheduled symbols exceeded local tick
cache coverage, so missing symbols are explicit rather than silently replaced:

| Window | Scheduled union | Cached/replayed | Missing | Raw aggTrades |
| --- | ---: | ---: | ---: | ---: |
| 2026-07-05 12:00-15:00 | 32 | 24 | 8 | 2,166,941 |
| 2026-07-08 18:00-21:00 | 33 | 28 | 5 | 1,850,700 |
| 2026-07-10 15:00-18:00 | 37 | 24 | 13 | 2,194,148 |

This is a 51-unique-symbol, 6,211,789-row partial-coverage test, not a claim of
complete all-market replay.

| Fill scenario | Admitted | Correct-side touch | Filled | Wins | Win rate | PF | Net PnL (U) | Positive windows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `displayed_queue` | 71 | 60 | 41 | 10 | 24.39% | 0.1404 | -3.3783 | 0/3 |
| `queue_10pct` | 71 | 60 | 42 | 10 | 23.81% | 0.1356 | -3.5176 | 0/3 |
| `queue_1pct` | 70 | 59 | 51 | 13 | 25.49% | 0.1962 | -3.3868 | 0/3 |
| `touch_upper_bound` | 70 | 59 | 59 | 16 | 27.12% | 0.2340 | -3.1460 | 0/3 |

Touch-upper-bound results by window were:

| Window | Admissions | Fills | Wins | Win rate | PF | Net PnL (U) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-07-05 | 16 | 13 | 3 | 23.08% | 0.1530 | -0.7612 |
| 2026-07-08 | 27 | 25 | 5 | 20.00% | 0.2233 | -1.3710 |
| 2026-07-10 | 27 | 21 | 8 | 38.10% | 0.2974 | -1.0138 |

Prior-only market opportunity ranking improved neither PF nor date-level
robustness. Fixed symbol selection was therefore not the main cause of negative
expectancy.

## Matched public aggregate versus self-collected individual ticks

The exact same 2026-07-10 20:50-23:50 UTC window, six symbols, parameters, and
touch fill rule were replayed from both sources:

| Source | Trade rows | Admissions | Touch/fills | Wins | Win rate | PF | Net PnL (U) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Public `aggTrades` | 377,051 | 9 | 9 | 1 | 11.11% | 0.1420 | -0.7538 |
| Self-collected individual ticks | 1,168,787 | 10 | 10 | 2 | 20.00% | 0.3247 | -0.5933 |

All nine public-source proposal IDs also existed in the individual-tick run.
Individual ticks added one XPINUSDT long trend-pullback proposal, which reached
take profit. Exact event granularity therefore matters and public aggregation
can miss setups driven by event count and intra-order timing.

It did not reverse the strategy verdict. The individual-tick touch run still
had 2 wins and 8 losses. Its full fill envelope was:

| Fill scenario | Admitted | Filled | Wins | PF | Net PnL (U) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `displayed_queue` | 10 | 8 | 0 | 0.0000 | -0.8786 |
| `queue_10pct` | 10 | 8 | 0 | 0.0000 | -0.8786 |
| `queue_1pct` | 10 | 9 | 1 | 0.1420 | -0.7538 |
| `touch_upper_bound` | 10 | 10 | 2 | 0.3247 | -0.5933 |

## Throughput versus expectancy

The corrected replay no longer shows a one-fill throughput problem. The
displayed-queue/trade-through scenario completed 90 fills in 15 hours (6/hour)
in the five-window test, 41 in 9 hours (4.6/hour) in the market-ranked test,
and 8 in 3 hours (2.7/hour) across six individual-tick symbols. The optimistic
touch rates were 7.7/hour, 6.6/hour, and 3.3/hour respectively. Sustained over
a day, these are dozens to more than one hundred fills; profitability, not raw
throughput, is now the blocking problem.

This does not come from the three-seat cap alone. The major repeated rejection
families are stale synthetic books, excessive short-window momentum, invalid
trend-pullback depth, CHOP regime, insufficient trade events, direction score,
range position, and volatility. `article_v2` also requires a two-step scout,
blocks BREAKOUT/CHOP, and only trades range edges or trend pullbacks.

The largest rejection family needs careful interpretation. Historical replay
updates its synthetic BBO only when a trade prints, while the live model has a
one-second fail-closed book freshness requirement. Authentic bookTicker can
update without a trade. Therefore trade-only replay is conservative about
signal frequency as well as queue fills. Extending stale synthetic quotes would
manufacture activity and weaken a live safety gate; the proper fix is to record
and replay authentic BBO/depth.

Thousands of daily market movements are not automatically thousands of
cost-covering passive setups. The current evidence says both that the replay
misses some opportunities and that the opportunities it does admit are
adversely selected.

## Performance and reproducibility

The replay performs one chronological k-way merge per window. It updates
strategy state from bounded one-second summaries and forwards raw rows to a
ledger only while that symbol has an active intent. Eligibility checks now
skip redundant wall-time pruning for symbols outside the current market-scan
hour or already active.

The corrected five-window run processed 7,012,504 rows in about 168 seconds on
the development machine. The market-ranked run processed 6,211,789 rows in
about 160 seconds. Maximum per-window evaluation p95 was 1.020 ms and 1.006 ms
respectively; the market-ranked maximum individual evaluation was 3.432 ms.
The individual-tick run processed 1,168,787 rows with 0.405 ms maximum-window
p95. The framework does not reproduce a server-breaking evaluation bottleneck.

Reproduce the three evidence sets locally:

```powershell
$env:PYTHONPATH=(Resolve-Path .\src).Path

python scripts\run_near_bbo_replay.py `
  --cache-dir runtime\aggTrades-cache `
  --output runtime\research\near_bbo_corrected_fill_envelope_random.json `
  --quiet

python scripts\run_near_bbo_replay.py `
  --cache-dir runtime\aggTrades-cache `
  --output runtime\research\near_bbo_corrected_market_ranked_2026-07-05_08_10.json `
  --eligibility-schedule runtime\micro-grid-market-scan-watch24-2026-07-05_08.json `
  --eligibility-schedule runtime\micro-grid-market-scan-watch24-2026-07-10.json `
  --window ranked-2026-07-05,2026-07-05T12:00:00Z,2026-07-05T15:00:00Z `
  --window ranked-2026-07-08,2026-07-08T18:00:00Z,2026-07-08T21:00:00Z `
  --window ranked-2026-07-10,2026-07-10T15:00:00Z,2026-07-10T18:00:00Z `
  --quiet

python scripts\run_near_bbo_replay.py `
  --cache-dir runtime\self-collected-tick-validation-20260710\cache `
  --output runtime\research\near_bbo_corrected_self_ticks_2026-07-10.json `
  --window self-ticks-2026-07-10,2026-07-10T20:50:00Z,2026-07-10T23:50:00Z `
  --symbols SKLUSDT,BUSDT,LABUSDT,TAGUSDT,XPINUSDT,TACUSDT `
  --data-source-kind self_collected_individual_ticks `
  --quiet
```

Runtime JSON and raw ticks remain gitignored and must not be committed.

## Improvement plan

### P0: make the evidence authentic before loosening live gates

1. Persist event-time bookTicker plus sequenced L2 depth alongside individual
   trades, including reconnect/gap diagnostics.
2. Replay quote freshness, spread, microprice, displayed depth, cancel/change
   rate, and queue-consumption envelopes from that source.
3. Keep touch, partial-queue, and conservative queue scenarios; no single
   unverifiable queue assumption should be called truth.
4. Keep live and testnet disabled for this lane until the same-process
   user-data fill and immediate protection path is separately proven.

### P1: improve entry expectancy and let winners pay for costs

1. Label post-touch returns, MFE/MAE, flow persistence, volume expansion,
   microprice, spread, depth imbalance, and price acceptance at 1/3/5/10/20/30
   seconds. Optimize adverse-selection probability, not raw signal count.
2. Use 1m/5m/15m trend, range, RSI, and Stoch context as continuous/dynamic
   features. Do not copy fixed article thresholds across symbols and regimes.
3. Separate range-reversion and trend-pullback calibration; a shared threshold
   can hide opposite behavior.
4. Test a net-of-cost profit lock that cannot declare success below fees and
   slippage, plus a runner policy that preserves favorable excursions.
5. Test early failure exits only on persistent joint evidence (microprice/flow,
   expanding volume, and price acceptance), not one noisy tick.

### P2: require unseen, market-ranked proof

1. Use chronological, outcome-purged train/validation splits and prior-only
   hourly market selection.
2. Satisfy the existing minimums of 500 compatible labels, 100 fills, 20 wins,
   and 20 losses before fitting; do not lower them to force a model.
3. Require positive net PnL and PF above 1 after fees/slippage, more than half
   of unseen windows positive, no single-symbol/date concentration, and stable
   results across queue scenarios.
4. Optimize expected value and drawdown first. A 70% win rate is acceptable as
   a consequence of a robust payoff distribution, not as a tunable target that
   can be manufactured by taking tiny profits.

Until those gates pass, keep the three micro pending seats as a capacity limit,
not a throughput target, and do not promote `article_v2` to live execution.
