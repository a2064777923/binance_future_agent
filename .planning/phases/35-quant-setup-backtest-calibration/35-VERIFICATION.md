---
phase: 35-quant-setup-backtest-calibration
verified: 2026-06-20T21:05:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 35: Quant Setup Backtest Calibration Verification Report

**Phase Goal:** Make the deterministic setup layer backtestable through the
existing staged sweep and matrix tooling.
**Verified:** 2026-06-20
**Status:** passed locally

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `quant_setup` is a built-in backtest variant. | VERIFIED | `BacktestConfig.to_dict()` includes `strategy_type`; `built_in_variants()` exposes `quant_setup`. |
| 2 | Backtest signal generation can call deterministic setup logic from completed bars. | VERIFIED | `tests.test_backtest_engine` covers setup-driven long and short trades. |
| 3 | Setup-driven simulation supports long and short futures PnL with fees and slippage. | VERIFIED | Long/short tests assert side and setup reason codes; full suite passes. |
| 4 | Matrix and CLI accept `quant_setup` as a variant. | VERIFIED | `tests.test_backtest_matrix` and `tests.test_cli` cover variant acceptance and output. |
| 5 | Full local tests pass. | VERIFIED | `python -m unittest discover -s tests` passed with `303` tests. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_backtest_engine tests.test_backtest_matrix` | Passed, `13` tests |
| Focused CLI backtest tests | Passed, `3` tests |
| `python -m unittest discover -s tests` | Passed, `303` tests |
| `git diff --check` | Passed |
| Manual `backtest run --variant quant_setup` smoke | Passed |
| Manual `backtest sweep --variants quant_setup` smoke | Passed |

## Live Safety

This phase is offline-only. It does not change live env settings, live service
state, exchange orders, or profile confirmation gates.
