# Micro-grid scalping blind-validation manifest (2026-07-11)

This manifest was frozen before downloading or evaluating the listed symbol
windows. It prevents choosing only favorable dates or coins after seeing the
results.

## Selection rule

- Seed: `micro-grid-blind-v1-2026-07-11`
- Candidate symbols: `HYPEUSDT`, `NEARUSDT`, `ONDOUSDT`, `PUMPUSDT`,
  `SUIUSDT`, `ZECUSDT`
- Candidate UTC dates: `2026-07-05`, `2026-07-06`, `2026-07-08`,
  `2026-07-09`
- Candidate start hours: `00`, `06`, `12`, `18`
- Window length: six hours
- Ranking: ascending SHA-256 of
  `seed|symbol|date|two-digit-start-hour`; take the first row for each unique
  symbol.

## Frozen blind windows

| Symbol | Signal window (UTC) |
| --- | --- |
| ZECUSDT | 2026-07-09 18:00:00 through 23:59:59 |
| NEARUSDT | 2026-07-06 06:00:00 through 11:59:59 |
| ONDOUSDT | 2026-07-06 06:00:00 through 11:59:59 |
| SUIUSDT | 2026-07-05 18:00:00 through 23:59:59 |
| PUMPUSDT | 2026-07-09 00:00:00 through 05:59:59 |
| HYPEUSDT | 2026-07-06 18:00:00 through 23:59:59 |

The previously inspected `SLXUSDT`, `ALLOUSDT`, `MAGMAUSDT`, `SENTUSDT`, and
`EDGEUSDT` windows are excluded from blind validation. They may be used only
for strategy development and ablation.

## Promotion gates

The scalping confirmation and exit policy may move beyond research/shadow only
only if the combined blind result meets every gate:

- at least 30 filled portfolio trades;
- win rate at least 70%;
- net PnL greater than zero after maker entry fee, taker exit fee, modeled exit
  slippage, and configured entry taker-risk allowance;
- profit factor at least 1.20;
- no single symbol supplies more than 50% of positive PnL;
- positive net PnL on at least four of the six windows;
- no hidden increase in stop distance or loss size whose main purpose is to
  manufacture a high win rate.

Failure of any gate keeps the change disabled in live configuration. A small
sample with a high win rate is evidence for more research, not permission to
trade live.

## Predeclared coverage extension

The six intraday windows above test time-of-day portability but are unlikely to
produce 30 fills by themselves. Before any blind result was viewed, the
following full-day symbol/date matrix was therefore frozen as the sample-size
extension. Each symbol receives the first three unique dates ranked by
SHA-256 of `seed|coverage|symbol|date`.

| Symbol | Full UTC dates |
| --- | --- |
| HYPEUSDT | 2026-07-05, 2026-07-08, 2026-07-09 |
| ONDOUSDT | 2026-07-09, 2026-07-05, 2026-07-06 |
| PUMPUSDT | 2026-07-06, 2026-07-09, 2026-07-08 |
| SUIUSDT | 2026-07-05, 2026-07-09, 2026-07-06 |
| NEARUSDT | 2026-07-06, 2026-07-08, 2026-07-05 |
| ZECUSDT | 2026-07-06, 2026-07-09, 2026-07-08 |

The 18 symbol-days are evaluated once with the development-selected profile.
The six-hour windows remain separately reported and are not replaced by the
coverage extension.

## Eligible-universe blind check

The broad-universe check may legitimately produce no trades because the
strategy is intended for sufficiently active, wick-producing symbols. To
distinguish safe abstention from a strategy that never generalizes, a second
set was frozen before evaluation from higher-beta or recently active contracts.

- Seed: `micro-grid-eligible-blind-v2-2026-07-11`
- Candidate dates: 2026-07-07 through 2026-07-09
- Candidate UTC starts: 00, 08, 16
- Window length: eight hours
- Selection: first SHA-256-ranked row for every unique symbol

| Symbol | Signal window (UTC) |
| --- | --- |
| AINUSDT | 2026-07-07 00:00:00 through 07:59:59 |
| HUSDT | 2026-07-08 00:00:00 through 07:59:59 |
| 1000BONKUSDT | 2026-07-08 00:00:00 through 07:59:59 |
| SPKUSDT | 2026-07-07 16:00:00 through 23:59:59 |
| GUSDT | 2026-07-09 00:00:00 through 07:59:59 |
| KAITOUSDT | 2026-07-09 16:00:00 through 23:59:59 |
| VIRTUALUSDT | 2026-07-08 16:00:00 through 23:59:59 |

This check uses the already frozen development-selected profile. It is not a
replacement for the 30-trade promotion gate; it only tests whether the edge is
portable inside the strategy's intended universe.

## Two-stage reversal-scout blind matrix

This matrix was frozen before downloading or evaluating these symbol/date
combinations. None of the symbols appeared in the earlier development,
calibration, broad-blind, or eligible-universe sets.

Frozen research profile:

- 400 USDT initial capital, 30x assumed leverage;
- 40 USDT absolute stop-risk cap, 2,400 USDT position-notional cap, 80 USDT
  position-margin cap, 400 USDT portfolio-margin cap, and 4,800 USDT
  portfolio-notional cap;
- three concurrent micro positions and live-like pullback sizing;
- dynamic Stoch/flow confirmation, pullback quality >= 0.50, mature wick stop
  rate <= 0.30;
- passive order remains inactive for at least five seconds and activates only
  after a side-favorable five-second return of at least 0.02%;
- original 20-second signal-to-fill deadline remains unchanged.

Blind symbols: `ARBUSDT`, `OPUSDT`, `WLDUSDT`, `SEIUSDT`, `TIAUSDT`,
`JUPUSDT`, `TRUMPUSDT`, and `DOGEUSDT`.

Blind full UTC dates: `2026-07-03`, `2026-07-04`, and `2026-07-07`, for a
total of 24 unseen symbol-days. All 24 rows are included regardless of trade
count or result. The existing promotion gates still apply without alteration.

## Shared-capital multi-symbol portfolio matrix

This matrix was frozen before running the additional portfolio tests requested
after the 400 USDT sizing correction. Every run uses one shared 400 USDT
account, 30x assumed leverage, at most three concurrent micro positions, 40
USDT stop risk per trade, 2,400 USDT position notional, 80 USDT position
margin, 400 USDT portfolio margin, and 4,800 USDT portfolio notional. Candidate
symbols compete by score and entry time; capital is not reset per symbol.

Operational stress windows using already-inspected symbols:

1. `2026-07-03..2026-07-04`: ALLO, ARB, DOGE, JUP, MAGMA, OP, SEI, SLX,
   TAIKO, TIA, TRUMP, WLD (12 symbols, continuous two-day account).
2. `2026-07-06`: HYPE, NEAR, ONDO, PUMP, SUI, ZEC (6 symbols).
3. `2026-07-07`: AIN, ARB, DOGE, HOT, JUP, MAGMA, OP, SEI, SPK, TIA,
   TRUMP, WLD (12 symbols).
4. `2026-07-08`: 1000BONK, H, HYPE, NEAR, PUMP, VIRTUAL, ZEC (7 symbols).
5. `2026-07-09`: EDGE, G, HYPE, KAITO, ONDO, PUMP, SENT, SUI, ZEC
   (9 symbols).

Fresh large-cap portfolio validation windows:

- universe: BTC, ETH, SOL, XRP, BNB, ADA, LINK, AVAX, DOT, LTC;
- period A: `2026-07-05..2026-07-06`, continuous two-day account;
- period B: `2026-07-08..2026-07-09`, continuous two-day account.

The operational windows use the strict quality profile. Each fresh large-cap
period is run once with the strict quality profile and once with the frozen
five-second reversal-activation scout. Results are reported even when no orders
fill.

## Guard-value ablation matrix

The strict-versus-loose attribution was completed before these variants were
run. Extra relaxed trades rejected by adverse taker flow and mature wick stop
rate were strongly negative, while trades rejected only by the pullback 0.50
floor or fixed 80/20 Stoch extremity were positive in the attribution sample.

Two frozen partial-relaxation variants are therefore evaluated without changing
entry, stop, target, costs, or 400 USDT sizing:

1. `flow_wick_no_pullback`: keep dynamic 80/20 Stoch, adverse-flow guard, and
   mature wick stop-rate <= 0.30; remove only the pullback >= 0.50 hard floor.
2. `flow_wick_stoch_70_30`: keep adverse-flow and mature wick guards, remove the
   pullback hard floor, and reduce minimum Stoch distance from 30 to 20 (roughly
   70/30 rather than 80/20 before dynamic tightening).

Both variants are run on the five shared-capital operational periods and the two
fresh ten-large-cap periods. No thresholds are changed after results are seen.

## Market-wide opportunity-ranking matrix

This matrix was frozen before downloading or inspecting its one-minute market
scan inputs. It tests the operator's hypothesis that a sparse fixed-symbol
backtest misses many valid opportunities and that cross-sectional discovery is
more useful than making every entry gate uniformly stricter.

Frozen scan and selection contract:

- evaluation dates: `2026-07-05`, `2026-07-08`, and `2026-07-10` UTC;
- universe: every currently listed Binance USD-M `TRADING` crypto perpetual
  quoted and margined in USDT whose `onboardDate` is no later than the feature
  window; current 24-hour ticker rank, price change, and volume are not used;
- each UTC hour is a separate selection window;
- a cheap first pass uses the 72 completed five-minute bars ending immediately
  before that hour and retains the top 48 symbols; a second pass recomputes the
  same feature family from 360 completed one-minute bars for those candidates;
  no bar from the selected signal hour is eligible in either pass;
- basic executable-data floor: at least 90% one-minute coverage and 1,000,000
  USDT quote volume in the trailing 360 minutes;
- ranking inputs: trailing liquidity, cost-adjusted range, turn/center-cross
  frequency, wick frequency and wick/body ratio, path efficiency, drift, recent
  activity, and taker-buy-flow balance/alternation;
- feature ranks are cross-sectional and use fixed documented weights; no trade
  outcomes are used to train or change the weights. The two-stage scan is a
  performance optimization only: exact aggTrades are downloaded solely for the
  final top eight symbol-hours;
- the top eight symbols at each hour enter that hour's exact aggTrade replay;
  all other symbols are skipped before the expensive second-level wick fit;
- maker entry, taker exit, slippage, aggressor-side fill checks, millisecond
  ordering, and the existing 20-second passive-entry deadline remain unchanged.

The same frozen eligibility schedule is compared under four entry profiles:

1. `strict`: dynamic 80/20 Stoch, adverse-flow <= 0.18, pullback quality >=
   0.50, and mature wick stop-rate <= 0.30;
2. `flow_wick_no_pullback`: strict flow/wick/Stoch guards with no pullback hard
   floor;
3. `flow_wick_stoch_70_30`: flow and mature-wick guards, no pullback hard floor,
   and approximately 70/30 Stoch location;
4. `capacity_relaxed`: no confirmation gate, pullback floor zero, and mature
   wick stop-rate cap 1.0, while retaining the structural range and passive
   spike-entry model.

Every exact replay uses the same shared 400 USDT account contract: 30x assumed
leverage, at most three open micro positions, 40 USDT stop risk, 2,400 USDT
position notional, 80 USDT position margin, 400 USDT portfolio margin, 4,800
USDT portfolio notional, and `pullback_scale_mode=none`. Results are reported
for every date and profile even if no orders fill. The existing promotion gates
remain unchanged; market-wide ranking is not allowed to substitute a high win
rate for positive net PnL, PF >= 1.20, at least 30 trades, and distributed
profits.

## Top-three live-order/cadence confirmation

The first market-wide run retained eight symbol-hours so discovery quality
could be studied. A post-result diagnostic found that simply retaining the
three highest *predeclared opportunity scores* (matching the operator's three
micro pending slots) would have improved the July 8/10 subset. That diagnostic
is exploratory and is not promotion evidence. The following confirmation set
was frozen before its market scan or exact outcomes were inspected.

- Seed: `market-top3-live-cadence-v1-2026-07-11`.
- Candidate dates: `2026-06-27` through `2026-07-02` UTC.
- Selection: ascending SHA-256 of `seed|date`; take the first three dates.
- Frozen dates: `2026-06-30`, `2026-07-01`, and `2026-06-28`.
- Market scan: unchanged all-crypto universe, 360-minute prior-only lookback,
  top-48 5m prefilter, 1m final rank, fixed component weights, and no outcome
  training; retain only the leading three symbols each UTC hour.
- Exact entry profile: strict 80/20 dynamic Stoch, adverse-flow 0.18,
  pullback 0.50, and mature wick stop-rate 0.30.
- Execution model: `live_best`, meaning the same live order score selects only
  one generated layer/side for each symbol check. Legacy research baskets are
  not allowed in this confirmation.
- Current-live cadence: one signal check every 120 seconds. Since the passive
  order deadline is 20 seconds, one order per top-three symbol cannot overlap
  the next scheduled check under the modeled cadence.
- Opportunity upper bound: repeat with a 3-second research cadence using the
  same top-three schedule and `live_best` order selection. This is reported
  separately and cannot justify deployment unless a dedicated fast micro loop
  is implemented and resource-tested.
- Sizing and promotion gates are unchanged from the market-wide matrix.

The 120-second result is the deployability test. The 3-second result answers a
different question: whether enough edge exists in principle if the micro leg
is later separated from the two-minute trend/AI cycle. Neither result may be
combined with July 8/10 as if all dates were unseen.

## Cost-aware profit-lock confirmation

The top-three dense confirmation exposed a recurring loss shape: many eventual
stop losses had first reached roughly one-half or more of the planned target.
The following exit variant was then developed on `2026-06-28`, `2026-06-30`,
and `2026-07-01`. Its parameters are frozen before the validation dates below
are market-scanned or replayed:

- retain the same top-three prior-only market rank, strict entry profile,
  `live_best` single order, 3-second opportunity cadence, 20-second pending
  deadline, costs, and 400 USDT sizing;
- activate target-progress protection at 45% of planned target movement;
- nominal lock fraction 10% of target movement;
- permitted giveback 35% of target movement;
- do not activate the profit lock until favorable movement covers modeled
  maker entry, taker exit, and exit slippage; once covered, the stop lock may
  not be less than that full round-trip cost;
- all other entry, stop, target, hold, and trailing settings remain unchanged.

Frozen validation dates: `2026-06-27`, `2026-06-29`, and `2026-07-02` UTC.
Each date is run once with the unchanged baseline and once with the frozen
cost-aware profit lock. The variant must still meet at least 30 trades, 70%
wins, PF >= 1.20, positive net PnL, distributed positive PnL, and positive net
PnL on at least two of the three dates. This is a dedicated-fast-loop research
test only: the separate 120-second test already showed that the current main
live cadence supplies almost no fills.
