# Backtesting Runbook

This file documents the early candle-based hot-momentum backtest harness. It is
not a full replay of the current live fused strategy. For the live regime router
plus micro-grid fast lane state, read `docs/current-live-strategy.md`; for
trade-level live forensics, use `scripts/server_live_trade_forensics.py`.

The first backtest layer is a small-capital, short-window sanity check for the
hot-momentum strategy family. It is deliberately conservative:

- signals use completed candles only;
- entries occur at the next candle open;
- same-candle stop/target collisions count as stop-loss first;
- taker fees and configurable slippage are included;
- notional, per-trade risk, daily loss, and concurrent-position caps mirror the
  100 USDT pilot style.

This does not prove a private "Lana-style" social trading system. It tests the
project's own market-heat proxy before live limits are increased.

## Fetch A Small Dataset

Use public Binance USD-M kline data. This does not require API keys.

```bash
python -m bfa.cli backtest fetch-klines \
  --env-file .env \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --interval 5m \
  --limit 288 \
  --output data/backtest/klines-5m-latest.json
```

For a specific historical window:

```bash
python -m bfa.cli backtest fetch-klines \
  --env-file .env \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --interval 5m \
  --start 2026-06-19T00:00:00Z \
  --end 2026-06-20T00:00:00Z \
  --limit 288 \
  --output data/backtest/klines-5m-20260619.json
```

## Run One Variant

```bash
python -m bfa.cli backtest run \
  --input data/backtest/klines-5m-latest.json \
  --variant balanced \
  --include-trades \
  --output results/backtest-balanced.json
```

Built-in variants:

- `strict`: fewer trades, tighter volatility and confirmation thresholds.
- `balanced`: default pilot calibration.
- `aggressive`: more trades, looser thresholds, higher expected noise.

## Run Staged Short-Window Sweeps

For 5m candles, `window-bars=72` is about 6 hours. This checks whether a setup
works across multiple short market regimes rather than one lucky full-period
result.

```bash
python -m bfa.cli backtest sweep \
  --input data/backtest/klines-5m-latest.json \
  --window-bars 72 \
  --step-bars 36 \
  --variants strict,balanced,aggressive \
  --output results/backtest-sweep-5m.json
```

## Run A Hot-Coin Matrix

The matrix command automates the daily validation loop:

- fetch all Binance USD-M 24h tickers;
- select high-volume USDT contracts with large absolute 24h moves;
- fetch multiple kline intervals;
- run staged sweeps for each interval and variant;
- emit one promotion report.

```bash
python -m bfa.cli backtest matrix \
  --env-file .env \
  --intervals 5m,15m \
  --limit 144 \
  --window-bars 72 \
  --step-bars 36 \
  --variants strict,balanced,aggressive \
  --top-n 8 \
  --min-quote-volume-usdt 10000000 \
  --min-abs-price-change-percent 3 \
  --output results/backtest-hot-matrix.json
```

To reproduce a fixed symbol set rather than the current 24h hot list:

```bash
python -m bfa.cli backtest matrix \
  --env-file .env \
  --symbols REUSDT,BTWUSDT,BICOUSDT,HEIUSDT,ESPORTSUSDT,ZECUSDT,HYPEUSDT,METUSDT \
  --intervals 5m,15m \
  --limit 144 \
  --window-bars 72 \
  --step-bars 36 \
  --output results/backtest-fixed-hot-matrix.json
```

Important verdicts:

- `candidate_for_forward_paper`: eligible for more forward observation only.
- `mixed_candidate_collect_more_data`: some edge, not enough stability.
- `keep_caps_unchanged_drawdown_risk`: drawdown breaches the pilot cap.
- `keep_caps_unchanged`: no promotion evidence.

## Run The Market-wide Micro-grid Funnel

Do not use today's 24h ticker rank to decide which historical micro-grid symbols
to replay. The dedicated scanner uses only bars completed before each signal
hour, scans the public crypto USDT perpetual universe with cheap 5m data, and
downloads 1m data only for the leading 48 symbols:

```bash
python scripts/run_micro_grid_market_scan.py \
  --dates 2026-06-27,2026-06-29,2026-07-02 \
  --prefilter-top-n 48 \
  --final-top-n 3 \
  --workers 16 \
  --cache-dir runtime/market-scan-klines \
  --output runtime/micro-grid-market-scan.json \
  --quiet
```

The output contains `eligibility_schedule`, plus the exact selected symbols per
date. Pass that same artifact to tick replay. `live_best` is the CLI default and
submits one generated order using the same score as live. Use `basket` only to
reproduce older multi-layer research:

```bash
python scripts/run_micro_grid_research.py \
  --symbols AGLDUSDT,BELUSDT,BTWUSDT \
  --start-date 2026-06-27 \
  --end-date 2026-06-27 \
  --eligibility-schedule runtime/micro-grid-market-scan.json \
  --execution-order-mode live_best \
  --signal-stride-seconds 3 \
  --order-wait-seconds 20 \
  --initial-capital 400 \
  --max-open-positions 3 \
  --max-leverage 30 \
  --max-risk-per-trade-usdt 40 \
  --max-position-notional-usdt 2400 \
  --max-margin-per-position-usdt 80 \
  --max-portfolio-margin-usdt 400 \
  --max-portfolio-notional-usdt 4800 \
  --pullback-scale-mode none \
  --entry-maker-cost \
  --output runtime/micro-grid-exact.json \
  --quiet
```

With `live_best`, the replay will not resubmit the same symbol until its pending
deadline or filled position lifecycle completes. Eligibility windows are also
trimmed by the pending lifetime so an old hourly selection cannot leak into the
next one.

Always report cadence separately:

- `--signal-stride-seconds 120` approximates the current two-minute main live
  cycle;
- `--signal-stride-seconds 3` is an opportunity upper bound for a future
  dedicated micro loop and is not current-live evidence.

The replay still lacks L2 queue position. Aggressor-side crossing is necessary
for a passive fill but does not prove our order would have reached the front of
the exchange queue.

## Promotion Rules

Do not raise live limits just because one run is green. Treat a variant as a
candidate for forward paper/live observation only when:

- it has enough trades to avoid one-trade conclusions;
- total net PnL remains positive after fees and slippage;
- more than half the staged windows are positive;
- max drawdown stays comfortably below the configured daily loss cap;
- results survive reruns on different symbols, intervals, and dates.

If results are weak, keep live caps unchanged and use the reports to tighten
filters before collecting more forward evidence.
