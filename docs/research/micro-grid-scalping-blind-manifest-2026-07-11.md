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
