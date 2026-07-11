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
