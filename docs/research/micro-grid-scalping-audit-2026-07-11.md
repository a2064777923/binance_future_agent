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

## Recommended next plan

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
