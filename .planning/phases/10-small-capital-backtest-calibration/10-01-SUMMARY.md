---
phase: "10-small-capital-backtest-calibration"
plan: "10-01"
subsystem: backtest-calibration
tags:
  - backtest
  - calibration
  - risk
key-files:
  created:
    - src/bfa/backtest/__init__.py
    - src/bfa/backtest/data.py
    - src/bfa/backtest/engine.py
    - src/bfa/backtest/matrix.py
    - src/bfa/backtest/models.py
    - tests/test_backtest_data.py
    - tests/test_backtest_engine.py
    - tests/test_backtest_matrix.py
    - docs/backtesting.md
  modified:
    - src/bfa/cli.py
    - src/bfa/market/binance_rest.py
    - tests/test_cli.py
    - tests/test_market_rest_metrics.py
    - README.md
    - .gitignore
requirements-completed:
  - BT-01
  - BT-02
  - BT-03
metrics:
  tests: "python -m unittest discover -s tests"
  test_count: 181
---

# Plan 10-01 Summary

## Delivered

- Added a dependency-free `bfa.backtest` package for public Binance USD-M kline
  fetching, local dataset loading, small-capital hot-momentum backtests, staged
  sweeps, and hot-universe matrix reports.
- Added strict, balanced, and aggressive baseline variants with 100 USDT
  pilot-style risk caps.
- Added CLI commands:
  - `python -m bfa.cli backtest fetch-klines`
  - `python -m bfa.cli backtest run`
  - `python -m bfa.cli backtest sweep`
  - `python -m bfa.cli backtest matrix`
- Extended the Binance public REST client so `/fapi/v1/ticker/24hr` can fetch
  all symbols for hot-universe selection without signed credentials.
- Documented the runbook and promotion rules in `docs/backtesting.md`.

## Calibration Evidence

Public Binance smoke runs used public kline/ticker endpoints only. Generated raw
reports were written under gitignored `results/`.

| Matrix | Symbols | Overall Verdict |
|--------|---------|-----------------|
| Auto hot | REUSDT, ZECUSDT, LABUSDT, WLDUSDT, BICOUSDT, BTWUSDT, HEIUSDT, BEATUSDT | `keep_caps_unchanged_drawdown_risk` |
| Fixed hot | REUSDT, BTWUSDT, BICOUSDT, HEIUSDT, ESPORTSUSDT, ZECUSDT, HYPEUSDT, METUSDT | `candidate_for_forward_paper` |
| Majors | BTCUSDT, ETHUSDT, SOLUSDT | `keep_caps_unchanged` |

Fixed-hot `aggressive` survived both 5m and 15m sweeps in this sample, but the
auto-hot matrix failed the drawdown gate and majors were weak. That means the
current edge is highly sensitive to universe selection and is not strong enough
to raise live caps.

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 181 tests |
| `git diff --check` | Passed; Windows LF-to-CRLF warnings only |
| `python -m unittest tests.test_backtest_matrix tests.test_cli tests.test_market_rest_metrics -v` | Passed, 36 tests |

## Decision

Keep the live 100 USDT pilot caps unchanged. Treat any positive matrix cells as
forward-paper candidates only until repeated runs and real forward/live
protective-order evidence are stronger.
