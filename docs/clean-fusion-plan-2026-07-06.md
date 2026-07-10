# Clean Fusion Plan 2026-07-06

This document is the current strategy contract for the next implementation
pass. It intentionally overrides older GSD phase notes and older live handoff
assumptions when they conflict.

## Why This Exists

Recent live review showed two opposite risks:

- the micro-grid leg still needs faster and cleaner edge execution, but its
  original design is already mean-reversion at predicted band edges, not a new
  idea to rediscover;
- the trend leg has at least one strong positive example, `BIRBUSDT` on
  2026-07-05 around 20:30 Asia/Hong_Kong, where trend continuation was detected
  and layered pullback limits gave a good entry before the move completed.

The next pass should not add another broad blended score. It should keep the
two legs separate, define exact setup families, and improve observability so
the system can learn from real completed trades.

## BIRBUSDT Positive Trend Sample

Observed from the server event store and exchange responses:

- `strategy_leg=trend`, `regime_label=TREND`, confidence `0.7376`.
- Long setup at `2026-07-05T12:29:28Z`.
- Key features: kline momentum `+1.1596%`, micro momentum `+0.4918%`,
  volume change `+109.95%`, taker buy/sell ratio `1.4062`, EMA spread
  `+0.1944%`, close position `82.93%`.
- It did not blindly chase. It posted a three-layer pullback ladder:
  `0.07754`, `0.07702`, `0.07669`.
- The shallow layer filled near `2026-07-05T12:40:54Z`.
- The user-observed post-trade chart showed the completed trade kept moving in
  the expected direction after close. This must be reconciled into `outcomes`
  before using outcome-ledger statistics to judge the trend leg.

Lesson: this is a useful `Trend Pullback Continuation` setup. The useful
pattern is strong directional evidence plus a passive pullback ladder. Do not
collapse it back into a generic 12-factor vote.

Implementation caveat verified on 2026-07-06: the server history contains
`trend_entry_ladder_*` reason codes and `trc/trm/tra` client order IDs, but
this local branch does not currently contain a matching named ladder generator.
Before claiming this branch fully preserves the BIRB-style trend ladder, compare
the deployed server copy or reintroduce the ladder explicitly with tests.

## Architecture

Each symbol/cycle should stay routed:

- `TREND`: trend pullback continuation only.
- `RANGE`: micro-grid mean reversion only.
- `CHOP`: no new entry.

The legs may coexist on the same symbol only when ownership is clear:

- an existing trend position may allow small isolated micro-grid scalps;
- a micro-grid position should block a new opposite trend entry on that symbol;
- protection, exits, and outcome attribution must remain leg-specific.

## Trend Leg Rules

Trend setup family:

```text
Trend Pullback Continuation =
  regime TREND
  + aligned EMA/momentum
  + volume expansion
  + taker flow in the trade direction
  + no strong spike-reversal conflict
  + passive pullback ladder instead of market chase
```

Execution:

- Trend limit wait is `1800` seconds by default.
- A long-lived trend limit order is valid only while the trend thesis remains
  valid. Revalidate periodically rather than treating the original signal as
  timeless.
- Ladder sizing should favor better pullback prices, not only the shallow
  layer. The default target is:
  - strong trend: `30 / 35 / 35`
  - normal trend: `25 / 35 / 40`
  - near-resistance long or near-support short: `20 / 35 / 45`
- Each ladder layer may have its own target:
  - shallow layer: first structure/near resistance target;
  - mid layer: normal trend target;
  - deep/anchor layer: runner or wider target.

Protection:

- Trend protection is slower than micro-grid protection.
- Do not move trend stops more often than every 180 seconds unless protection is
  missing.
- A fresh fill should run a quick thesis check. If price action, flow, or VWAP
  context no longer agrees with the original direction, exit small rather than
  waiting for the full stop.

## Micro-Grid Rules

Micro-grid remains the range/needle leg:

- long entries must be near predicted lower band/needle depth;
- short entries must be near predicted upper band/needle depth;
- use two or more layers for average-liquidity symbols so one layer can catch
  a reachable pullback and another can catch the real edge;
- stop distance is volatility/needle-depth based, while size is derived from
  max loss;
- profit protection activates only after enough actual progress, not at tiny
  floating profit.

The execution EV model may score `P_fill`, `P_win`, and net reward, but it is
only an execution gate. It is not the market-sensing layer.

## Outcome Persistence Requirement

Live learning is invalid if completed trades are missing from `outcomes`.

The reconciler must include:

- normal `submitted` intents;
- pending-limit intents later reconciled by the watchdog as `submitted`;
- pending-limit fills that were protected later than the original live cycle.

Every completed live position should be recoverable from signed Binance
`userTrades` into idempotent `fills` and `outcomes`.

Root cause found on the `BIRBUSDT` sample:

- historical code/research defaults used `limit_wait_seconds=75`, but the
  current trend contract is `1800` seconds. All live, risk, executor, backtest,
  and research calibration paths must preserve the 1800-second trend wait
  unless a future plan explicitly changes it;
- the pending-limit watchdog treated sibling ladder orders as filled when one
  order on the same symbol created an active position. In the BIRB case only
  the shallow `trc` layer was `FILLED`; the `trm` and `tra` exchange queries
  were still `NEW` with `executedQty=0`, but old code wrote them as
  `submitted`;
- outcome reconciliation used the watchdog-submitted row time and same-symbol
  next-intent windows, so layered orders from one original signal could miss
  the actual entry fill or truncate each other's user-trade query window.

Required behavior:

- if Binance `query_order` explicitly says an order is `NEW` or otherwise
  unfilled with `executedQty=0`, the watchdog must leave it pending; do not
  infer a fill merely from a same-symbol position;
- if the watchdog later submits a filled pending limit, outcome reconciliation
  must use the original pending signal time from latency metadata;
- if old data contains watchdog-submitted rows whose saved query proves
  `NEW`/`0` fill, the reconciler must skip those rows so learning does not
  ingest phantom fills;
- same-symbol layered orders with the same original signal timestamp must not
  truncate each other's `userTrades` query window.

Verified server state on 2026-07-06:

- `order_intents` and `exchange_responses` extended to
  `2026-07-05T12:40:58Z`;
- `fills` and `outcomes` were still capped at `2026-07-05T12:30:31.060000Z`;
- for the BIRB ladder, `trc` was `FILLED` with `executedQty=10646`, while
  `trm` and `tra` were `NEW` with `executedQty=0`.

This proves the missing-outcome issue is real and that historical watchdog rows
can contain phantom submitted sibling layers.

## Backtest Requirement

Backtests for this plan must:

- run the full routed fusion, not trend-only or micro-only unless explicitly
  labelled;
- use second-level aggTrades path for limit fills and exits;
- use `limit_entry_max_wait_seconds=1800` for the trend leg;
- keep micro-grid `order_wait_seconds=20`;
- report trend, micro, and fusion summaries separately;
- include trend signal rejection histograms so a 0-trade result can be split
  into router rejection, setup rejection, and limit no-fill instead of being
  guessed after the fact.

## 2026-07-04 Full Fusion Backtest Snapshot

Local command set:

- trend: `scripts/run_second_agg_compound_backtest.py`
  with `quant_setup_live_action_flow`, 400U capital, 30x max leverage,
  1200U trend notional cap, 20U per-trade risk, 60U daily loss, and
  `limit_entry_max_wait_seconds=1800`;
- micro-grid: `scripts/run_micro_grid_research.py` with 20s order wait,
  7 max open positions, 30x max leverage, 5% risk fraction, and the same
  symbol basket;
- fusion: `scripts/run_strategy_fusion_replay.py` with regime router enforced.

Outputs are under `runtime/backtests/clean_fusion_20260704_latest_diag/`.

Result:

- trend produced 0 simulated trades. The new histogram shows the dominant gate
  was router classification, not limit fill: `router:skip_chop:CHOP=5142`,
  `router:skip_leg_mismatch:RANGE=312`, `router:skip_low_confidence:CHOP=163`,
  and only `setup:pass=23` setup-level rejects;
- micro-grid produced 99 trades, win rate `63.64%`, PF `0.7456`, net
  `-0.2962U`, fees `0.2787U`, max drawdown `0.4176U`;
- routed fusion produced 90 trades, all `RANGE|micro_grid`, win rate
  `64.44%`, PF `0.6878`, net `-0.5189U`, fees `0.3626U`, max drawdown
  `0.6944U`.

Interpretation:

- this run does not prove the trend leg is bad; it proves the current router
  and selected symbol/day window routed almost all trend candidates to CHOP or
  RANGE before setup/fill simulation;
- micro-grid still has a cost and tail-loss problem: it wins often, but
  LABUSDT, SLXUSDT, MUSDT, and OUSDT stop-loss clusters dominate the positive
  symbols;
- the next tuning pass should not blindly loosen all gates. First decide
  whether `regime_range_width_expanding` is too coarse for trend, and whether
  micro-grid needs stricter stop-tail avoidance on the losing symbol regimes.

## 2026-07-06 Trend Router Fix

Root cause for the previous `0` trend-trade backtest:

- signal generation did not reach limit-fill simulation at all;
- `classify_regime()` computed `width_expansion_ratio` as the recent lookback
  high-low range divided by the average bar range;
- for trend impulses, that ratio naturally exceeds `1.75`, but the old
  `_chop_reasons()` treated `regime_range_width_expanding` as CHOP even when
  `trend_signal=True`;
- because CHOP is applied before the TREND branch, clean expansion trends were
  routed to `skip_chop` and never reached setup or exchange simulation.

Fix:

- `regime_range_width_expanding` is now a CHOP reason only when there is no
  clean trend signal;
- trend edge-exhaustion, conflict, low-confidence, and true no-direction width
  guards remain active.

Verification on the same 2026-07-04 symbol basket:

- trend-only second-agg backtest changed from `0` trades to `13` candidate
  trades, with `13` filled and `2` unfilled limit orders;
- trend-only result: win rate `61.54%`, PF `1.1622`, net `+14.2078U`;
- routed fusion result: `98` trades, `12` accepted trend trades and `86`
  micro-grid trades, win rate `66.33%`, PF `1.0803`, net `+7.0561U`;
- remaining risk: accepted trend trades were concentrated in `LABUSDT` and
  produced large stop-loss drawdowns, so this is a router availability fix, not
  a final trend-quality endorsement.

## 2026-07-06 Long Backtest And Micro Sizing Correction

Long-window local backtest:

- window: `2026-07-01` through `2026-07-04` UTC, 20-symbol basket;
- risk config: 400U initial capital, 30x max leverage, 1200U max notional,
  20U per-trade risk, 60U daily loss;
- outputs: `runtime/backtests/long_20260701_20260704/` and
  `runtime/backtests/long_20260701_20260704_live_like/`.

Important correction:

- the historical micro-grid research replay treated
  `pullback_size_multiplier` as a hard portfolio scale cap. A 20U base basket
  with multiplier `0.35` stayed near 7U notional even when the live account
  allowed much larger positions;
- live setup sizing instead uses risk/notional/margin caps and quality scale.
  It does not use `pullback_size_multiplier` as a global notional cap;
- `scripts/run_micro_grid_research.py` now has
  `--pullback-scale-mode cap|none`. Use `none` for live-like sizing and keep
  `cap` only for legacy apples-to-apples research comparisons.

Results:

- legacy cap micro-grid: 448 trades, win rate `60.04%`, PF `0.8755`,
  net `-0.7779U`, average margin only `0.144U`;
- live-like micro-grid without extra quality gate: 448 trades, win rate
  `60.04%`, PF `0.8315`, net `-105.5473U`, max drawdown `147.1819U`,
  average margin `14.92U`;
- live-like micro-grid with `--min-net-notional-reward-percent 0.60` and
  `--max-reversal-response-rate 0.70`: 200 trades, win rate `59.50%`,
  PF `1.0685`, net `+26.3099U`, max drawdown `44.6243U`;
- routed fusion using the quality-gated micro-grid: 203 trades, win rate
  `60.10%`, PF `1.9467`, net `+133.2816U`, max drawdown `80.0550U`.

Interpretation:

- the old tiny micro-grid PnL was not representative of live risk. It hid
  the real tail-loss problem by shrinking every trade;
- micro-grid's raw issue remains average loss greater than average win. The
  quality gate improves candidate selection, but PF `1.07` standalone is not a
  final edge proof;
- fusion remains dominated by the trend leg. The quality-gated micro-grid is
  no longer negative in fusion, but it does not materially reduce trend-driven
  drawdown yet.

## 2026-07-06 Micro-Grid Cross-Validation Notes

To avoid fitting only the full 2026-07-01 through 2026-07-04 window, the
micro-grid changes were rerun on two non-overlapping slices:

- early slice: `2026-07-01` through `2026-07-02`;
- late slice: `2026-07-03` through `2026-07-04`.

Live-like baseline versus quality-v1:

| Window | Variant | Trades | Net | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| 2026-07-01..02 | baseline | 228 | `-48.19U` | `0.8787` | `85.02U` |
| 2026-07-01..02 | quality-v1 | 104 | `+18.79U` | `1.0857` | `44.62U` |
| 2026-07-03..04 | baseline | 220 | `-65.22U` | `0.7495` | `71.69U` |
| 2026-07-03..04 | quality-v1 | 96 | `+7.19U` | `1.0456` | `32.35U` |

Quality-v1 means:

- `--pullback-scale-mode none`;
- `--min-net-notional-reward-percent 0.60`;
- `--max-reversal-response-rate 0.70`.

Rejected follow-up ideas:

- target-progress trailing at `65%` target progress improved the late slice
  (`+20.03U`) but broke the early slice (`-3.63U`). A more conservative `80%`
  target-progress version also broke the early slice and did not help the late
  slice. Keep this as an explicit experimental switch only;
- rolling symbol quality guard with 3 samples, PF floor `0.9`, and stop-rate
  cap `0.60` reduced trade count and some drawdown, but made both slices net
  negative. Do not enable it by default.

Adaptive profit lock:

- added as an explicit research switch, `--adaptive-profit-lock-enabled`;
- it locks only after a trade has moved toward its original target and uses
  setup-derived continuation confidence. Higher confidence delays activation,
  locks less profit, and gives the trade more room to run; lower confidence
  locks earlier and tighter;
- early slice result: quality-v1 `+18.79U` versus adaptive lock `+9.73U`;
- late slice result: quality-v1 `+7.19U` versus adaptive lock `+26.36U`;
- full 2026-07-01..04 standalone result: quality-v1 `+26.31U`, PF `1.0685`,
  max DD `44.62U`; adaptive lock `+36.73U`, PF `1.1295`, max DD `53.89U`;
- full routed fusion result: quality-v1 `+133.28U`; adaptive lock `+133.51U`.

Decision:

- adaptive lock is better than fixed target-progress trailing and should remain
  available for further research;
- do not make it live default yet. It improved total standalone PnL, but it
  worsened the early validation slice and increased standalone max drawdown;
- to ship it live, validate on more dates and implement the same logic in the
  position protection layer, not only in the research backtest.

Conclusion:

- quality-v1 is the only micro-grid filter in this pass that improved both
  independent slices;
- target-progress trailing, rolling symbol guard, and adaptive profit lock are
  not robust enough to ship as defaults yet;
- the next improvement should focus on better entry/stop geometry and
  post-fill validation, not generic early lock-profit rules.
