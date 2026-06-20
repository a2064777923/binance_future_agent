# Backtesting Runbook

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
