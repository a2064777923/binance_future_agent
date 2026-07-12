# Micro-grid scalping framework and strategy audit (2026-07-11)

## Outcome

The current micro-grid strategy has not demonstrated a generalizable 70% win
rate. The first report accidentally used the script's legacy 30 USDT / 10x / 1%
risk defaults instead of the current 400 USDT live risk profile. After rerunning
with the server's non-secret 400 USDT caps, the development-selected profile
reached 8 wins from 9 trades (88.89%, PF 1.878, +8.6226 USDT), but the
predeclared unseen universe produced only 2 trades across 18 symbol-days, with
1 win, 1 loss, PF 0.934, and -0.0939 USDT. All six predeclared intraday windows
and all seven higher-beta eligible-universe windows produced zero trades.

This is a failed promotion result, not a reason to loosen live risk. The new
confirmation remains research/shadow only. Live and sentinel remain disabled.

## Backtest framework audit

The following issues were found and corrected in
`scripts/run_micro_grid_research.py`:

1. Passive aggTrade fills used price crossing without checking aggressor side.
   A passive long buy now requires a seller-aggressed trade
   (`buyer_maker=true`); a passive short sell requires a buyer-aggressed trade.
2. Maker-accurate economic gates omitted the taker exit fee. The modeled round
   trip now contains maker entry fee, taker exit fee, exit slippage, and the
   optional entry taker-risk allowance. The target-net-USDT gate uses the same
   cost model instead of recomputing a different formula.
3. Sparse tick streams could label a trade `data_end_exit` before its configured
   hold horizon. The replay now closes from the corresponding one-second bar
   state when the bar series covers the horizon.
4. Tick serialization truncated timestamps to whole seconds. ISO timestamps now
   preserve milliseconds so event ordering survives JSON round trips.
5. Research could only scan full UTC days. `--signal-start` and `--signal-end`
   now bound signal generation while retaining the required earlier history.
6. The article-inspired confirmation used to run after the expensive rolling
   wick/EV fit. If both sides fail Stoch/flow confirmation, the scan now exits
   before fitting. Multi-layer order generation also computes confirmation only
   once per side.
7. Portfolio replay exposed only fractional caps and did not record the sizing
   arguments in its JSON artifact. It now supports and records absolute
   per-trade risk, position notional, position margin, portfolio margin, and
   portfolio notional caps. This prevents a nominally "live-like" run from
   silently using the old 30 USDT defaults.
8. The live pending-quality context and the research replay had separate
   implementations. Second-bar flow, return, volume expansion, VWAP acceptance,
   and absorption diagnostics now share one pure implementation. Research can
   model pending cancellation or a two-stage inactive scout without changing
   live execution.

On the same MAGMAUSDT full-day confirmation run, candidate-generation time fell
from 59.8249 seconds to 24.4331 seconds (59.2% lower) with identical candidate
summary and portfolio summary. Diagnostic `passed_windows` changes intentionally
because confirmation rejections are now counted before wick fitting.

### Current 400 USDT sizing used for corrected results

The corrected runs explicitly use:

```text
--initial-capital 400
--max-open-positions 3
--risk-per-trade-fraction 0.10
--max-notional-fraction 6
--max-margin-fraction 1.0
--max-leverage 30
--max-risk-per-trade-usdt 40
--max-position-notional-usdt 2400
--max-margin-per-position-usdt 80
--max-portfolio-margin-usdt 400
--max-portfolio-notional-usdt 4800
--pullback-scale-mode none
```

These map to the selected non-secret server limits. The standalone micro replay
uses three concurrent positions to match the micro pending capacity. The JSON
artifact now carries the complete values under `portfolio_sizing`.

### Remaining model limitations

- aggTrades prove aggressor direction, but not queue position or whether enough
  volume traded ahead of our passive order. L2 or a conservative queue model is
  still required before treating fill probability as exchange-realistic.
- the reported equity drawdown is based on realized exits. Overlapping
  intratrade MAE is visible per trade but is not a full mark-to-market portfolio
  drawdown curve.
- one-second OHLC fallback is conservative for stop/target ambiguity, but it
  cannot reconstruct the exact path when aggTrades are absent.
- repeated rolling wick-model fitting remains the dominant cost on windows that
  pass the cheap structural and confirmation gates.

## What was retained from the scalping article

The useful ideas were translated into adaptive evidence rather than fixed
templates:

- Stoch extremes are treated as location, not proof of reversal. Both K and D
  must be sufficiently far from 50, and the required extremity increases when
  volatility and the adverse EMA context are stronger.
- active taker flow is used to reject entries when directional pressure is
  still extreme. The allowed adverse flow tightens with adverse context.
- the existing fast/mid/slow EMA stack remains a trend-pressure input; it is not
  used as a simple fixed moving-average crossover.
- historical wick stop rate can reject a side only after the model has at least
  the configured minimum fill sample. This avoids treating a two-event estimate
  as mature evidence.
- fixed PEPE-style stop and target prices were not copied. Entries, stops, and
  targets remain normalized by current band width, volatility, cost, flow,
  learned wick behavior, and exchange fees.

RSI was not added as another hard gate in this iteration. On these horizons it
is highly correlated with the existing Stoch and EMA inputs; adding a correlated
indicator after seeing a small sample would increase overfit without proving new
information. The article's important warning — overbought can remain strong and
oversold can remain weak — is supported by the losing paths observed here.

## Development ablations

All rows below use corrected aggTrade replay and the explicit 400 USDT sizing
above. Older 30 USDT PnL figures are superseded.

| Profile | Trades | Win rate | PF | Net PnL (USDT) | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| Corrected broad baseline | 38 | 50.00% | 0.265 | -104.4294 | No edge; 26.1% capital loss across separate windows |
| Dynamic Stoch/flow confirmation | 11 | 72.73% | 0.896 | -2.1398 | Win rate alone still hides negative expectancy |
| Pullback >= 0.50 and mature wick stop rate <= 0.30 | 9 | 88.89% | 1.878 | +8.6226 | Development winner; sample too small |
| Fixed 15-second inactive scout | 6 | 83.33% | 1.155 | +1.5226 | Removes winners and retains the large loss |
| Reversal-activated scout, development only | 9 | 88.89% | 1.878 | +8.6226 | Same development trades as quality profile |
| Reversal scout plus calibration day | 10 | 90.00% | 2.013 | +9.9453 | Promising in seen data only |

The 8-second early-exit rule reduced drawdown in some losses, but it also closed
the eventual MAGMA winner and several other winners before their reversal
developed. Aggregate taker flow during the first eight seconds did not separate
winners cleanly: several profitable mean reversions first showed strongly
adverse flow, consistent with capitulation or passive absorption. It therefore
stays disabled.

The live pending-quality rule was also replayed before fills. On the calibration
day it canceled the profitable PUMP order and retained the losing NEAR order.
The evidence capable of separating them appeared only after NEAR had already
touched its entry. This is a timing/architecture problem, not a threshold
problem. The live scan runs every two minutes while micro entries expire after
20 seconds; the 10-second pending watchdog currently handles lifecycle and
protection, not market-quality rescoring. No live behavior was changed.

A research-only two-stage scout was therefore added. In reversal mode the order
is not active until at least five seconds have elapsed and a side-favorable
five-second return appears. It improved the seen calibration day from 1 win / 1
loss to 1 win / 0 losses while preserving all nine development trades. This did
not solve generalization: the subsequently frozen 24-symbol-day blind matrix
created 35 orders, filled none, and therefore supplied no evidence for live
promotion.

## Generalization result

The exact blind windows and selection rules are recorded in
`docs/research/micro-grid-scalping-blind-manifest-2026-07-11.md`.

| Blind set | Coverage | Trades | Win rate | PF | Net PnL (USDT) |
| --- | --- | ---: | ---: | ---: | ---: |
| Arbitrary intraday | 6 windows, 7 symbol-window observations | 0 | n/a | n/a | 0.0000 |
| Broad coverage extension, corrected 400U sizing | 18 symbol-days | 2 | 50.00% | 0.934 | -0.0939 |
| Higher-beta eligible universe | 7 eight-hour windows | 0 | n/a | n/a | 0.0000 |
| Reversal-scout matrix | 24 unseen symbol-days | 0 | n/a | n/a | 0.0000 |

Across the 18 symbol-days, only 31 individual orders were created; 3 layers
filled (9.68% order fill rate), producing 2 portfolio trades. The dominant
rejections were width outside profile, drift too large relative to width, width
not covering modeled cost, weak edge response, and insufficient edge
alternation. This shows that the development profile is a narrow specialist,
not a portable scalping system.

Moving entries closer increased fills on the former blind data, but the tested
variants lost every trade: disabling spike-depth produced 0 wins from 4 trades,
and capping entry depth at -0.30 span with a 0.60-span stop also produced 0 wins
from 4 trades. The lack of fills is therefore not the only problem; the closer
signals often represent continuation rather than reversal.

The reversal-scout blind matrix created 35 orders. Seven were rejected because
no qualifying reversal appeared and the remaining 28 expired unfilled. This is
safe abstention, but a zero-trade test cannot establish a 70% edge.

## Shared-capital multi-symbol portfolio runs

Additional runs used one shared 400 USDT account per period. Symbols competed
by candidate score and entry time; the replay enforced three open micro
positions, 40 USDT stop risk, 2,400 USDT position notional, 80 USDT position
margin, 400 USDT portfolio margin, and 4,800 USDT portfolio notional. Capital
was not reset per symbol.

| Period | Symbols | Trades | Win rate | PF | Net PnL | Max DD | Max concurrent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-07-03..04 | 12 | 14 | 71.43% | 5.186 | +27.0675U | 5.4002U | 1 |
| 2026-07-06 | 6 | 2 | 50.00% | 0.934 | -0.0939U | 1.4167U | 1 |
| 2026-07-07 | 12 | 1 | 100.00% | inf | +1.5393U | 0.0000U | 1 |
| 2026-07-08 | 7 | 0 | n/a | n/a | 0.0000U | 0.0000U | 0 |
| 2026-07-09 | 9 | 6 | 83.33% | 1.108 | +1.0567U | 9.8168U | 1 |
| Trade aggregate | 46 symbol-period observations | 23 | 73.91% | 2.671 | +29.5696U | n/a | 1 |

The aggregate is a trade-level diagnostic across separate account windows, not
a claim that one account compounded continuously across all dates. The
continuous 2026-07-03..04 window supplied 91.5% of aggregate net profit.
Results were concentrated in MAGMA (+12.68U), SENT (+8.01U), TAIKO (+6.67U),
and SLX (+6.08U), while EDGE (-6.95U), NEAR (-1.42U), and ALLO (-0.37U) were
negative.

Six-hour UTC entry buckets further show regime concentration:

| UTC bucket | Trades | Win rate | PF | Net PnL |
| --- | ---: | ---: | ---: | ---: |
| 00:00-06:00 | 8 | 50.00% | 2.629 | +10.5343U |
| 06:00-12:00 | 4 | 100.00% | inf | +11.2234U |
| 12:00-18:00 | 9 | 77.78% | 1.135 | +1.5161U |
| 18:00-24:00 | 2 | 100.00% | inf | +6.2958U |

Across these windows the strategy created 562 individual grid orders, filled
25 layers (4.45%), and produced 23 portfolio trades. No two accepted positions
overlapped, so real market evidence did not exercise the configured three-slot
capacity. A deliberately looser 12-symbol capacity stress run produced 63
trades but still only one concurrent position; it fell to 58.73% wins, PF
0.978, -2.2960U, and 28.9241U maximum drawdown. The concurrency implementation
is covered synthetically, but increasing signal count in market data degraded
the edge rather than creating useful parallel exposure.

Two fresh two-day portfolios of BTC, ETH, SOL, XRP, BNB, ADA, LINK, AVAX, DOT,
and LTC were also run with both strict quality and reversal-scout profiles:

- 2026-07-05..06: 10 strict-profile orders, zero fills/trades;
- 2026-07-08..09: 1 strict-profile order, zero fills/trades;
- reversal scout: zero fills/trades in both periods.

The strategy is therefore a sparse specialist for a few high-wick contracts,
not a general multi-coin scalp. The 73.91% aggregate win rate does not override
the period concentration, zero large-cap coverage, and sub-30 trade sample.

## Market-wide opportunity-ranking follow-up

The fixed-symbol audit above did not answer the operator's core objection: a
large futures market can contain many simultaneous micro opportunities, so the
system should discover and rank them instead of treating one fixed list and one
uniformly strict gate as the whole opportunity set. A second research pass
therefore added `scripts/run_micro_grid_market_scan.py` and an eligibility
schedule consumed by the exact aggTrade replay.

### Prior-only two-stage discovery

The scanner uses no current 24-hour ticker rank and no future signal-window
bar. For every UTC hour it:

1. evaluates every current crypto USDT perpetual whose `onboardDate` existed at
   the feature window;
2. ranks a cheap 360-minute 5m view and retains 80 symbols;
3. recomputes liquidity, cost-adjusted range, turns, center crosses, wick
   magnitude/frequency, path efficiency, drift, recent activity, and taker-flow
   balance from 360 completed 1m bars;
4. emits a broad 24-symbol/hour watch universe for exact tick replay; pending
   capacity is applied later, after simultaneous attempts are ranked.

The original frozen July 5/8/10 scan covered 528 contracts and 72 hourly
windows. After cache warm-up, 3,168 5m archives and 653 1m archives were read
with no missing final-stage data in 20.72 seconds. That run used the older
48/top-eight shape and remains useful only as a historical diagnostic. The
current prefilter-80/watch-24 schema keeps eligibility broader than capacity and
still avoids downloading aggTrades or fitting rolling wick models for the full
market.

### What strict and relaxed actually mean

The strict entry profile adds all of the following to the structural range and
passive spike-entry model:

- dynamically tightened Stoch location, approximately 80/20 before context;
- maximum adverse-flow allowance 0.18;
- side pullback quality at least 0.50;
- mature historical wick stop-rate at most 0.30.

The capacity-relaxed profile disables confirmation, sets the pullback floor to
zero, and allows mature wick stop-rate up to 1.0. Partial variants removed only
the pullback floor or also moved Stoch toward 70/30.

On the same July 5 market-ranked top-eight schedule:

| Profile | Trades | Win rate | PF | Net PnL |
| --- | ---: | ---: | ---: | ---: |
| Strict | 31 | 67.74% | 0.777 | -23.4573U |
| No pullback floor | 33 | 66.67% | 0.784 | -27.2864U |
| Stoch about 70/30, no pullback floor | 51 | 60.78% | 0.655 | -89.3878U |
| Capacity relaxed | 91 | 58.24% | 0.478 | -189.8134U |

The relaxed-run attribution is more nuanced than "every strict guard is
good." Trades failing Stoch plus pullback were especially poor (24 trades, PF
0.306, -134.91U), and all Stoch failures together were also poor (53 trades,
PF 0.393, -183.35U). However, the 23 trades rejected only by adverse-flow
confirmation were positive on this date (PF 1.313, +6.16U). Earlier fixed-list
attribution found the opposite for adverse flow. Therefore adverse flow should
be researched as regime-aware evidence, not declared a universally correct
hard threshold from either sample. The current live profile is unchanged.

Across July 5/8/10, the legacy top-eight/basket diagnostic produced 97 trades,
65.98% wins, PF 0.905, and -30.9113U. Gross price-path PnL was only +17.2890U,
while fees were 48.2004U. The mean winner was 4.61U and the mean loser 9.87U.
This confirms that finding more active coins is insufficient when entries still
admit continuation paths and reward is small relative to stop loss and cost.

### Additional framework mismatches corrected

The market-wide pass found three material research/live mismatches:

1. The deployed main cycle runs every two minutes, whereas dense research
   evaluates every three seconds. The three-second result is an opportunity
   upper bound, not current-live evidence.
2. Live generates several layers/sides but submits only the highest-ranked one.
   Legacy research simulated a filled multi-layer basket. New
   `--execution-order-mode live_best` shares the exact live order score and
   simulates one submitted order.
3. Dense research could submit another order for the same symbol while the
   previous 20-second limit was still pending, and could resignal while its
   prior position was open. `live_best` replay now blocks that symbol until the
   pending deadline or position exit plus cooldown, and trims the last pending
   lifetime from each eligibility window so an old hourly schedule cannot
   overlap the next one.

Live and research no longer maintain duplicate order-score implementations;
`micro_grid_live` calls the shared research score. This is a no-behavior-change
refactor for live ranking and prevents future scoring drift.

### Historical Top-three result and corrected capacity boundary

Selecting the best three symbol-hours does **not** match three pending slots.
It excludes every lower-ranked symbol for the entire hour, whereas a capacity
model must let all watched symbols compete again when an order expires or a
position exits. The earlier frozen current-cadence check on June 28/30 and July
1 used `live_best` but a 120-second stride. It produced only one filled trade
across three days; two days had zero fills. This directly explains why the
operator saw almost no effective 20-second micro orders: a two-minute sampler
observes only one of every forty possible three-second decision points, and the
hourly Top-three schedule further suppressed replacement opportunities.

A separate frozen three-second top-three confirmation initially failed (55
trades, 69.09% wins, PF 0.795, -39.5425U). A later, independent validation on
June 27/29 and July 2 added the corrected pending/position lifecycle and
produced:

| Date | Trades | Win rate | PF | Net PnL |
| --- | ---: | ---: | ---: | ---: |
| 2026-06-27 | 11 | 63.64% | 1.646 | +16.0205U |
| 2026-06-29 | 14 | 78.57% | 2.750 | +48.5685U |
| 2026-07-02 | 16 | 75.00% | 1.517 | +37.5220U |
| Aggregate | 41 | 73.17% | 1.816 | +102.1110U |

The aggregate is a trade-level diagnostic across three independently reset
400U day accounts, not one continuously compounded account. All three dates
were positive. Trades spanned 17 symbols, 10 symbols were net positive, and
the largest symbol supplied 29.38% of gross winning-trade PnL. Submitted candidate
orders fell from 951 before lifecycle enforcement to 594 after it, a 37.5%
reduction. This clears the frozen statistical gates for a *research-only
dedicated fast loop* under the old eligibility assumption, not for the current
two-minute live service. The corrected capacity model supersedes it as promotion
evidence.

The corrected replay watches 24 symbols and applies global pending=3 and
active-intent=3 only after ranking all same-timestamp attempts. On three fixed,
three-hour July 5/8/10 windows:

| Profile | Trades | Win rate | PF | Net PnL | Fills/hour |
| --- | ---: | ---: | ---: | ---: | ---: |
| Relaxed | 42 | 59.52% | 0.562 | -14.5282U | 4.67 |
| Strict `all` | 18 | 61.11% | 0.302 | -8.2750U | 2.00 |
| Conjunctive research mode | 51 | 54.90% | 0.526 | -16.5198U | 5.67 |

Conjunctive mode treats isolated Stoch, adverse-flow, and mature wick-stop
failures as evidence rather than hard blocks, rejecting only Stoch+adverse-flow
or Stoch+weak-pullback combinations. It increased activity but worsened the
aggregate loss. July 8 alone produced 13 trades, 15.38% wins, PF 0.061, and
-14.5084U. This candidate failed on development data, so no additional
historical threshold tuning or reused-window “validation” was performed. The
default and live profile remain `all`.

### Public near-BBO forward shadow

A lightweight alternative was implemented as a public-data-only shadow lane.
It subscribes to `bookTicker` and public trades, keeps bounded one-second flow
buckets, ranks a broad watch set, and admits at most three queue-proxy intents.
It has no signed client or order method.

The independent 600-second 24-symbol evidence-exit run processed 1,207,624
messages and completed all 200 three-second evaluations with 0 misses. Ranking
p95 was 0.243ms and max was 0.554ms; two code-1006 disconnects recovered via
backoff. The ledger used 400U shadow capital, 120U notional per intent, and at
most three active intents. It admitted 49 intents, filled 12, and therefore
demonstrated 72.05 shadow fills/hour—but every fill lost after modeled costs:
0% wins, PF 0,
-1.1637U, and 0 profitable fills/hour. Four evidence-adverse-selection exits
lost -0.5738U, six max-hold exits lost -0.3862U, one stop lost -0.2028U, and one
profit-lock exit finished approximately flat after costs.

This separates the questions cleanly: the performance architecture can observe
high-frequency fills, but the current imbalance/flow/microprice heuristic is
uncalibrated and selects toxic fills. The evidence exit can limit some losses;
it cannot manufacture entry expectancy. A connected-but-silent stream now also
ages against wall time so stale data fails closed.

Remaining promotion blockers are important:

- aggTrades show aggressor side but not queue depth or volume ahead of the
  post-only order;
- the live raw seconds cache currently holds about 20 minutes, while the market
  rank uses a six-hour 1m history;
- no authenticated three-second service with user-data fills and immediate
  same-process protection has been built; only the public no-order shadow was
  resource-tested;
- current exchangeInfo creates a small survivorship limitation for old dates;
- live and sentinel remain disabled, and no research flag is enabled in live.

### Article-informed regime/scout candidate (2026-07-12 follow-up)

The scalping article was incorporated as a set of market-structure principles,
not as fixed RSI/Stoch thresholds or a promise of a 70% win rate. The new
`article_v2` public-shadow candidate uses a bounded 1m context with 5/15-minute
EMAs, path efficiency, range width/location, edge alternation, volume, and
breakout acceleration. Its range location is Stoch-like, while width and
volatility provide a dynamic alternative to fixed Bollinger distances.

The route is explicit:

- `RANGE` permits only edge-aligned `range_reversion` scouts;
- `TREND` permits only direction-aligned `trend_pullback` scouts that have not
  broken too far through the slow EMA;
- `BREAKOUT` and `CHOP` admit no passive scalp; breakout is retained as a
  distinct diagnostic state rather than mislabeled as a pullback;
- a scout must survive a later evaluation with aligned microprice, improving
  taker-flow change, fast flow, favorable price reversal, signal persistence,
  bounded five-second volatility, and bounded adverse continuation.

Before a trained calibrator exists, confirmed `article_v2` scouts are admitted
only as public-shadow exploration. Their old heuristic fill/win/EV values are
retained as features but do not block label collection. `legacy` mode keeps its
original probability gates; a loaded calibrator restores fail-closed learned
fill, win, and conditional-net gates. This is the narrow relaxation supported
by the 0/16 evidence, not a relaxation of liquidity, freshness, spread,
momentum, regime, volatility, or confirmation controls.

This addresses the article's multi-timeframe trend/range and reverse-signal
ideas without hard-coding `RSI < 30` or `Stoch < 20` across every coin. Those
lagging indicator thresholds remain unsuitable as universal hard gates; the
earlier strict/conjunctive experiments already showed that adding more fixed
filters can reduce frequency without producing positive expectancy.

The four prior public-shadow JSONL sessions were also normalized into one
label contract. They contain 77 resolved intents and 16 queue-proxy fills, all
16 unprofitable. Predicted win probability was nearly identical for unfilled
and filled intents (68.79% versus 69.29%), so the old score had no useful
discrimination. Filled intents had higher five-second volatility (4.40 versus
2.73 bps), then averaged only +2.68 bps MFE against -7.94 bps MAE. Average MFE
did not cover the roughly 5.2 bps modeled round-trip cost. This is conditional
fill toxicity, not merely an exit-timing problem.

Every resolved `article_v2` intent now writes a native training label with its
lane, regime, fill-within-TTL outcome, costed profitability, net PnL, MFE/MAE,
queue pressure, TTL, spread, target/stop, cost, and shadow exit-policy context.
The calibrator fits three separate surfaces: `P(fill within TTL)`,
`P(profitable | fill)`, and `E(net bps | fill)`. It uses a chronological,
outcome-purged train/validation split and refuses to emit a model unless at
least 500 compatible labels, 100 fills, 20 profitable fills, and 20 losing
fills exist, with proportional class coverage retained in training. A loaded
artifact must be `status=trained`, match the exact feature schema and execution
configuration domain, and still remains public-shadow-only.

Legacy and feature-incomplete rows are visible in `observed_*` audit counts but
cannot train the new lane. The existing evidence therefore reports 77 observed
labels, 16 observed fills, 0 observed winners, 0 compatible `article_v2`
labels, `status=insufficient_data`, and `model=null`. Lowering the minimums to
force a model would turn known bad evidence into false confidence.

Clean 400U / three-intent forward comparison:

| Candidate | Watch | Admitted | Fills / wins | PF / net | p95 / max eval | Missed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Inherited heuristic probability gates | 24 | 0 | 0 / 0 | n/a / 0U | 0.237 / 0.446ms | 0 / 600 |
| Confirmed-scout exploration, current hot universe | 40 | 7 | 2 / 0 | 0 / -0.11935U | 0.900 / 1.335ms | 0 / 600 |

The first clean 30-minute run processed 2,633,053 messages but produced zero
eligible proposals. Of 14,400 symbol evaluations, 46.75% failed top-of-book
notional and 18.92% had stale trades because the reused 24-symbol list was no
longer a suitable current universe. More importantly, 10.60% were stopped by
the uncalibrated fill heuristic, 2.43% by its win heuristic, and 0.31% by its
derived EV before regime/scout could collect outcomes. Keeping those known-bad
priors as mandatory gates was therefore a label-collection design error.

After removing only those priors and selecting 40 current public hot/liquid
symbols, the second clean 30-minute run processed 6,156,309 messages with one
connection, zero reconnects, and zero missed evaluations. It admitted three
`range_reversion` and four `trend_pullback` intents. Five expired and two
filled; both fills reached the 30-second max-hold exit and lost. The range fill
lost -0.02698U and the trend fill lost -0.09237U. Across fills, mean MFE was
+3.97 bps, mean MAE was -4.71 bps, and mean net was -4.97 bps. Full-run
throughput was 4 fills/hour; excluding the mandatory 15-minute warm-up, the
observed opportunity pace was about 28 intents/hour and 8 fills/hour.

This fixes the one-fill/zero-label architecture problem but still rejects the
candidate as a profitability result. Two losses are far too few for strategy
selection, yet they repeat the prior warning that favorable movement often
does not cover costs. No threshold was tuned against this seen window.

Regardless of this short result, promotion still requires multiple
predeclared unseen windows and symbols, at least 30 fills, win rate >= 70%, PF
>= 1.20, positive net PnL, bounded drawdown, and non-concentrated profits. The
70% target is a promotion gate, not a parameter to optimize on one seen window.

### Cost-aware profit protection

Many losses first reached 45%-80% of target. Target-progress trailing was
therefore hardened so it cannot claim breakeven before favorable movement
covers maker entry, taker exit, and modeled slippage. The capability remains
disabled by default.

The frozen variant (45% activation, 10% nominal lock, 35% giveback, full-cost
floor) raised the lifecycle-validation win rate from 73.17% to 82.93% and PF
remained 1.580, but net PnL fell from +102.1110U to +44.0709U and July 2 became
negative. It rescued large reversals but cut too many full-target winners. It
is not approved for live or as the new research default. The next exit model
should condition protection on continuation/exhaustion state rather than apply
one lock curve to every profitable trade.

## Self-collected tick replay and recorder audit

The live raw-feed collector was still active while live trading and the
position sentinel remained inactive and the kill switch remained present. A
read-only inventory at `2026-07-11T20:40Z` found 206 gzip files, 6.994 GB
compressed, spanning nominally `2026-07-10T19:31:06Z` through
`2026-07-11T20:40:22Z`. This confirms roughly one day of usable retention, not
a multi-day validation store. File transitions included one 103.6-second gap
and many roughly 9-11-second gaps. `systemctl` reported 169 service restarts at
the observation point, and the journal contained repeated keepalive ping
timeouts and connection resets.

### Frozen comparison

Before reading tick outcomes, the validation fixed:

- the existing prior-only 528-contract market scan and hourly top three;
- `2026-07-10T20:50:00Z..23:50:00Z`, clipped from the available raw coverage
  after the selected symbols first appeared at about `20:31:46Z` plus a
  15-minute strategy warm-up;
- six schedule symbols: `SKLUSDT`, `BUSDT`, `LABUSDT`, `TAGUSDT`, `XPINUSDT`,
  and `TACUSDT`;
- 400U capital, 30x maximum leverage, three open slots, three-second signals,
  20-second pending limits, strict confirmation, maker entry cost, and
  `live_best` single-order lifecycle.

The self-collected extract contained 1,231,762 individual Binance `@trade`
events. The same fixed replay was then run once with public daily aggTrades and
once with the local extract, with network fallback disabled. Both produced the
same single SKL long:

| Field | Public aggTrades | Self-collected trades |
| --- | ---: | ---: |
| Signal | 23:27:39Z | 23:27:39Z |
| Entry | 23:27:42.813Z at 0.00488455 | identical |
| Exit | 23:27:55.589Z at 0.00489426 | identical |
| Exit reason | take profit | take profit |
| Net PnL | +1.1912207U | +1.1912207U |
| Created / expired orders | 12 / 11 | 10 / 9 |

Thus the one realized path is reproducible, while individual trades versus
aggregated trades still change some rejected/pending candidate states. One win
is not evidence of a 100% win rate and does not add meaningful statistical
support to the earlier 41-trade validation.

### Recorder bottleneck found and corrected

The long raw extract showed receive-minus-exchange-event p95 latency of roughly
6-9 seconds, p99 of 13-25 seconds, and maxima above 53 seconds for the selected
symbols. Small negative values are server clock offset; the multi-second tail
is real backlog. Code review found four compounding hot-path costs:

1. every 100ms depth message was JSON-decoded even though only trades update
   the second cache;
2. every trade rescanned up to 1,200 cached seconds for expiry, even when many
   trades shared the same second;
3. stale symbols were pruned relative to their own last event and therefore
   remained forever; the 21.47MB cache held 287 historical symbols;
4. the event loop synchronously serialized and rewrote the full cache every two
   seconds while also compressing every raw line and servicing WebSocket pings.

The corrected recorder fast-rejects depth for cache parsing, prunes each active
symbol at bounded intervals, globally removes inactive symbols, batches raw
writes at gzip level 3, disables redundant WebSocket compression, enlarges the
receive queue, and writes immutable cache snapshots in a background thread.
Live candidate health now separately checks `latest_event_time_ms`, so recent
processing of delayed messages cannot pass the freshness gate.

On the real 21.47MB server cache snapshot, the compact/pruned representation
kept the current 80 symbols and 44,072 bars, fell to 7.30MB (-66.0%), and JSON
serialization was 2.71x faster. A separate 90-second server `/tmp` canary used
the same 80 symbols and 100ms depth while the official recorder continued
unchanged. Both captured exactly 63,012 trades in the matched interval:

| Receive minus event latency | Existing recorder | Corrected canary |
| --- | ---: | ---: |
| p50 | -30ms | -40ms |
| p95 | 1,053ms | -22ms |
| p99 | 1,197ms | 22ms |
| max | 1,388ms | 85ms |

The canary completed without reconnect, used 13.042 user CPU seconds and 1.335
system CPU seconds, peaked at 36.9MB RSS, and did not drop a matched trade. This
is strong evidence that the recorder bottleneck is operational rather than a
market-data limitation. It is not evidence for strategy profitability. The
official server service was not restarted or replaced during this audit.

The replay now supports `--archive-cache-only`, and schedule intervals are
clipped to the requested signal window before history loading. This prevents a
self-collected test from silently downloading public archives for irrelevant
hours or missing local days. `prepare_self_collected_tick_replay.py` performs a
single-pass selected-symbol extraction and records coverage/latency without
placing orders. Full depth is still present in the original gzip files, but
this comparison used trade events only and still does not model queue position.

### Revised recommendation

- Keep `live_best`, pending/position lifecycle enforcement, prior-only market
  ranking, watch-24 eligibility, and downstream pending=3 capacity in the
  truthful research path.
- Reject the tested conjunctive gate. Do not globally relax Stoch and pullback
  or promote adverse flow from this sample.
- Keep cost-aware target protection available but disabled.
- Continue the separate public shadow only to collect a much larger labeled
  fill/non-fill data set. The historical scanner still needs an incremental
  six-hour 1m ring buffer; AI/trend work stays out of this path.
- Add L2/queue-aware fill estimation and calibrate entry probabilities from
  forward outcomes. The historical 41-trade Top-three result is superseded and
  is not permission to trade.

## Recommended next plan

### Current P0 - keep research truthful

- make `live_best` the CLI default; require explicit `basket` for legacy
  reproduction;
- retain corrected aggressor side, costs, millisecond order, cross-day warmup,
  pending expiry, position lifecycle, and prior-only eligibility schedules;
- require net PnL, PF, drawdown, sample size, per-date results, and profit
  concentration together with win rate;
- add an L2/queue-aware replay before any claim about 20-second passive fill
  probability.

### Current P1 - calibrate the separate shadow lane

- turn the two-stage historical scanner into an incremental watch-24 ranker:
  broad cheap universe, six-hour 1m ring buffer, then downstream pending=3;
- keep trend/AI work out of the three-second public shadow and enforce one
  intent per selected symbol;
- retain the measured latency/missed-cycle budgets and collect enough forward
  labels to calibrate fill probability and post-fill adverse selection;
- do not consider testnet until queue-aware replay is positive and a user-data
  fill/protection design closes the current watchdog protection gap.

### Current P2 - protect failures without clipping runners

- replace one unconditional target-progress lock with an evidence state machine:
  adverse continuation, absorption/exhaustion, delayed reversal, and
  high-confidence runner states;
- use post-fill flow *change*, price acceptance, and giveback speed rather than
  one aggregate flow ratio;
- validate every new exit on fresh dates with at least 30 trades, win rate >=
  70%, PF >= 1.20, positive net PnL, and distributed profits;
- do not deploy or enable live until queue-aware replay and forward shadow gates
  pass.

The older P0-P2 list below is retained as the pre-market-scan historical plan;
the current plan above supersedes it where they differ.

### P0 — keep research truthful

- retain the corrected aggressor, cost, millisecond, horizon, and intraday
  replay behavior;
- keep the new confirmation and wick-stop gate disabled in live configuration;
- require net PnL, PF, drawdown, and sample size together with win rate;
- add an L2/queue-aware replay before any claim about 20-second passive fill
  probability.

### P1 — separate eligibility, reversal, and passive-grid legs

- retain the research-only stage-1/stage-2 switches, but do not deploy them;
- stop tuning the same deep passive geometry against the now-seen windows;
- build a separate eligibility model from trailing cost-adjusted range, wick
  frequency, spread, and realized fill rate before choosing symbols;
- compare a confirmed-reversal entry leg against the deep passive micro-grid as
  a separate strategy, rather than forcing one set of entries to do both jobs;
- require any new variant to produce enough fills on a fresh manifest before
  optimizing its exits.

### P2 — exit and validation

- replace the unconditional “no reversal after N seconds” exit with an evidence
  state machine: adverse continuation, absorption/exhaustion, delayed reversal,
  and profit-runner states;
- use post-fill flow *change* and price acceptance rather than one aggregate
  flow ratio;
- validate with nested walk-forward splits and a fresh predeclared symbol/date
  manifest; minimum 30 trades, win rate >= 70%, PF >= 1.20, positive net PnL,
  and profit spread across symbols remain mandatory;
- do not deploy or enable live until those gates pass.
