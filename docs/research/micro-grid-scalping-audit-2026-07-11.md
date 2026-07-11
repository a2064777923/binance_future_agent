# Micro-grid scalping framework and strategy audit (2026-07-11)

## Outcome

The current micro-grid strategy has not demonstrated a generalizable 70% win
rate. A development-selected profile reached 8 wins from 9 trades (88.89%, PF
3.91, +0.3327 USDT), but the predeclared unseen universe produced only 2 trades
across 18 symbol-days, with 1 win, 1 loss, PF 0.988, and -0.0006 USDT. All six
predeclared intraday windows and all seven higher-beta eligible-universe windows
produced zero trades.

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

On the same MAGMAUSDT full-day confirmation run, candidate-generation time fell
from 59.8249 seconds to 24.4331 seconds (59.2% lower) with identical candidate
summary and portfolio summary. Diagnostic `passed_windows` changes intentionally
because confirmation rejections are now counted before wick fitting.

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

All rows below use corrected aggTrade replay. The live-like rows use
`--pullback-scale-mode none`; therefore their PnL scale differs from the older
legacy-cap research outputs.

| Profile | Trades | Win rate | PF | Net PnL (USDT) | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| Corrected broad baseline | 37 | 48.65% | 0.298 | -0.4910 | No edge |
| Dynamic Stoch/flow confirmation, legacy size cap | 11 | 72.73% | 1.017 | +0.0015 | High win rate, economically negligible |
| Dynamic confirmation, live-like sizing | 11 | 72.73% | 0.817 | -0.0998 | Fails economic gate |
| + 8-second post-fill confirmation | 11 | 36.36% | 1.379 | +0.0693 | Cuts loss size but misclassifies delayed winners |
| + target-progress trailing | 11 | 72.73% | 0.550 | -0.2449 | Locks too early in weak windows |
| + adaptive profit lock | 11 | 72.73% | 0.525 | -0.2585 | Same failure mode |
| Pullback >= 0.50 and mature wick stop rate <= 0.30 | 9 | 88.89% | 3.909 | +0.3327 | Development winner; sample too small |

The 8-second early-exit rule reduced drawdown in some losses, but it also closed
the eventual MAGMA winner and several other winners before their reversal
developed. Aggregate taker flow during the first eight seconds did not separate
winners cleanly: several profitable mean reversions first showed strongly
adverse flow, consistent with capitulation or passive absorption. It therefore
stays disabled.

## Generalization result

The exact blind windows and selection rules are recorded in
`docs/research/micro-grid-scalping-blind-manifest-2026-07-11.md`.

| Blind set | Coverage | Trades | Win rate | PF | Net PnL (USDT) |
| --- | --- | ---: | ---: | ---: | ---: |
| Arbitrary intraday | 6 windows, 7 symbol-window observations | 0 | n/a | n/a | 0.0000 |
| Broad coverage extension | 18 symbol-days | 2 | 50.00% | 0.988 | -0.0006 |
| Higher-beta eligible universe | 7 eight-hour windows | 0 | n/a | n/a | 0.0000 |

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

## Recommended next plan

### P0 — keep research truthful

- retain the corrected aggressor, cost, millisecond, horizon, and intraday
  replay behavior;
- keep the new confirmation and wick-stop gate disabled in live configuration;
- require net PnL, PF, drawdown, and sample size together with win rate;
- add an L2/queue-aware replay before any claim about 20-second passive fill
  probability.

### P1 — redesign entry as a two-stage decision

- stage 1 scouts a band edge but does not immediately assume reversal;
- stage 2 distinguishes continuation from exhaustion using a short flow slope,
  price acceptance outside the band, and an actual reversal follow-through;
- maintain a deep passive quote only while adverse pressure remains high;
  otherwise move to a bounded near-edge quote, but cancel if price acceptance
  confirms a breakout;
- score symbol eligibility from trailing cost-adjusted range, wick frequency,
  spread, and realized fill rate using only information available before the
  test window.

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
