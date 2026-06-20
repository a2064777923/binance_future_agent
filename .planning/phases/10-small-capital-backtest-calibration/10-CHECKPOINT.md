# Phase 10 Checkpoint: Small-Capital Backtest Calibration

**Captured:** 2026-06-20
**Status:** Local backtest harness added and public-kline smoke runs completed.

## Implemented

- Added `bfa.backtest` package:
  - kline dataset loading/writing/fetching;
  - hot-momentum baseline backtest;
  - staged short-window sweeps;
  - strict, balanced, and aggressive built-in variants.
- Added CLI commands:
  - `python -m bfa.cli backtest fetch-klines`
  - `python -m bfa.cli backtest run`
  - `python -m bfa.cli backtest sweep`
  - `python -m bfa.cli backtest matrix`
- Added hot matrix reporting:
  - auto-selects current hot USDT futures from Binance 24h ticker data;
  - supports fixed-symbol reruns for reproducibility;
  - fetches multiple intervals and runs staged sweeps per interval;
  - emits aggregate promotion verdicts such as `keep_caps_unchanged` and
    `mixed_candidate_collect_more_data`.
- Added `docs/backtesting.md` with commands, limitations, and promotion rules.
- Added `results/` to `.gitignore`; generated reports and raw data remain
  local/runtime evidence, not tracked source.

## Verification

- `python -m unittest discover -s tests`
  - 181 tests passed after matrix tooling.
- Targeted matrix tests:
  - `python -m unittest tests.test_backtest_matrix tests.test_backtest_engine tests.test_backtest_data -v`
  - `python -m unittest tests.test_market_rest_metrics -v`
  - `python -m unittest tests.test_cli -v`
- `git diff --check`
  - passed with Windows LF/CRLF warnings only.
- Public Binance kline fetches succeeded without secrets:
  - 5m major sample: BTCUSDT, ETHUSDT, SOLUSDT, 144 bars each.
  - 15m major sample: BTCUSDT, ETHUSDT, SOLUSDT, 96 bars each.
  - 5m hot sample: REUSDT, BTWUSDT, BICOUSDT, HEIUSDT, ESPORTSUSDT,
    ZECUSDT, HYPEUSDT, METUSDT, 144 bars each.
  - 15m hot sample: same hot symbols, 96 bars each.
- Public Binance matrix smoke runs succeeded without secrets:
  - auto-hot matrix selected REUSDT, ZECUSDT, LABUSDT, WLDUSDT, BICOUSDT,
    BTWUSDT, HEIUSDT, BEATUSDT and returned
    `keep_caps_unchanged_drawdown_risk`.
  - fixed-hot matrix selected REUSDT, BTWUSDT, BICOUSDT, HEIUSDT,
    ESPORTSUSDT, ZECUSDT, HYPEUSDT, METUSDT and returned
    `candidate_for_forward_paper`.
  - major matrix selected BTCUSDT, ETHUSDT, SOLUSDT and returned
    `keep_caps_unchanged`.

## Public-Kline Smoke Results

Major-coin 5m sweep:

- `strict`: 0 trades, insufficient.
- `balanced`: 3 trades, net `-0.26533502` USDT, insufficient.
- `aggressive`: 19 trades, net `-0.75598821` USDT, negative.

Major-coin 15m sweep:

- `strict`: 0 trades, insufficient.
- `balanced`: 4 trades, net `-0.50732940` USDT, insufficient.
- `aggressive`: 14 trades, net `-0.49029817` USDT, negative.

Hot-coin 5m sweep:

- `strict`: 49 trades, net `-1.39172544` USDT, negative.
- `balanced`: 83 trades, net `-1.67674468` USDT, negative.
- `aggressive`: 78 trades, net `+2.16604406` USDT, positive in 2/3
  windows; candidate for forward paper only.

Hot-coin 15m sweep:

- `strict`: 52 trades, net `-1.87997469` USDT, negative.
- `balanced`: 86 trades, net `+1.79707531` USDT, positive in 3/5 windows;
  candidate for forward paper only.
- `aggressive`: 81 trades, net `+0.03034178` USDT, positive in 3/5 windows,
  but worst drawdown `4.62425683` USDT exceeds the 3 USDT pilot daily-loss cap;
  not a promotion candidate.

## Interpretation

The first real public-kline samples do not justify raising live limits. Major
coins are weak under this baseline. Current hot-coin samples show possible
momentum edge in the 5m aggressive and 15m balanced variants, but the worst
windows and drawdowns are too unstable for scaling. Treat those variants as
candidates for more rounds of short-window backtesting and forward observation
under the existing 100 USDT pilot caps; do not raise live limits.

Historical Square/social narrative data is still incomplete, so this checkpoint
tests a market-heat proxy. It should not be described as a verified copy of a
private Lana-style system.

The matrix results also show high universe-selection sensitivity: the fixed-hot
pool had candidate cells, while the auto-hot pool failed drawdown gates. That
supports continued forward observation, not a live cap increase.
