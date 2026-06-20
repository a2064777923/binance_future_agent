---
phase: 10-small-capital-backtest-calibration
verified: 2026-06-20T00:00:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 10: Small-Capital Backtest Calibration Verification Report

**Phase Goal:** Add repeatable short-window backtests before raising live risk
limits in a volatile crypto futures market.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Historical Binance USD-M kline datasets can be fetched without secrets. | VERIFIED | `fetch_historical_klines()`, `write_klines_dataset()`, `backtest fetch-klines`, fake-client tests, and public Binance smoke runs. |
| 2 | The baseline uses completed candles and enters at the next candle open. | VERIFIED | `run_hot_momentum_backtest()` generates signals from prior bars; `tests/test_backtest_engine.py` asserts next-open entries. |
| 3 | Fees, slippage, notional, risk-per-trade, daily-loss, and open-position caps are reported. | VERIFIED | `BacktestConfig`, `BacktestResult.summary()`, engine risk gates, and tests for fees/slippage, daily loss, and concurrency. |
| 4 | Staged sweeps compare strict, balanced, and aggressive variants across small windows. | VERIFIED | `run_staged_sweep()`, built-in variants, `backtest sweep`, and staged sweep tests. |
| 5 | Results are written to gitignored data/results paths and documented before live cap increases. | VERIFIED | `.gitignore` covers `data/` and `results/`; `docs/backtesting.md` documents commands, verdicts, and promotion rules. |

**Score:** 5/5 truths verified.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| BT-01: Local small-capital backtest harness with completed candles, next-open entry, fees/slippage, and pilot caps. | SATISFIED | `src/bfa/backtest/data.py`, `engine.py`, `models.py`, and tests. |
| BT-02: Staged short-window sweep reporting across conservative variants. | SATISFIED | `run_staged_sweep()`, `backtest sweep`, `backtest matrix`, and matrix tests. |
| BT-03: Document commands, limitations, and promotion rules before live risk-limit increase. | SATISFIED | `docs/backtesting.md`, `README.md`, and Phase 10 summary/checkpoint. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 181 tests |
| `git diff --check` | Passed; Windows LF-to-CRLF warnings only |
| `python -m unittest tests.test_backtest_matrix tests.test_cli tests.test_market_rest_metrics -v` | Passed, 36 tests |

## Public Smoke Evidence

| Run | Overall Verdict | Interpretation |
|-----|-----------------|----------------|
| Auto hot matrix | `keep_caps_unchanged_drawdown_risk` | Current hot universe has drawdown risk above the pilot cap in loose variants. |
| Fixed hot matrix | `candidate_for_forward_paper` | Fixed hot pool shows possible edge, especially aggressive, but this is not enough for scale-up. |
| Major coin matrix | `keep_caps_unchanged` | BTC/ETH/SOL baseline does not show promotion evidence. |

## Human Verification Required

None for local backtest tooling. Live trading remains active under existing
100 USDT pilot caps; no cap increase is justified by this phase.

## Gaps Summary

No Phase 10 implementation gaps found. The main strategy gap is empirical:
historical social/Square data is incomplete, and the current backtest validates
a market-heat proxy rather than reproducing a private Lana-style system.

---
*Verified: 2026-06-20*
*Verifier: Codex inline verifier*
