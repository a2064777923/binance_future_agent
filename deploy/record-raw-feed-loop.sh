#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${BFA_ENV_FILE:-/etc/binance-futures-agent/env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

APP_DIR="${BFA_APP_DIR:-/opt/binance-futures-agent/app}"
PYTHON="${BFA_PYTHON:-/opt/binance-futures-agent/.venv/bin/python}"
OUTPUT_DIR="${BFA_RAW_FEED_DIR:-/opt/binance-futures-agent/data/raw-feed}"
SECONDS_CACHE_OUTPUT="${BFA_RAW_FEED_SECONDS_CACHE:-/opt/binance-futures-agent/runtime/raw-feed-seconds.json}"
SECONDS_CACHE_WINDOW="${BFA_RAW_FEED_SECONDS_CACHE_WINDOW:-1200}"
SECONDS_CACHE_FLUSH_SECONDS="${BFA_RAW_FEED_SECONDS_CACHE_FLUSH_SECONDS:-2}"
SYMBOLS="${BFA_RAW_FEED_SYMBOLS:-}"
BASE_URL="${BFA_RAW_FEED_WS_BASE_URL:-${BINANCE_FUTURES_WS_BASE_URL:-wss://fstream.binance.com}}"
REST_BASE_URL="${BFA_RAW_FEED_REST_BASE_URL:-${BINANCE_FUTURES_BASE_URL:-https://fapi.binance.com}}"
DEPTH_SPEED_MS="${BFA_RAW_FEED_DEPTH_SPEED_MS:-100}"
ROTATE_SECONDS="${BFA_RAW_FEED_ROTATE_SECONDS:-3600}"
AUTO_HOT="${BFA_RAW_FEED_AUTO_HOT_SYMBOLS:-${BFA_LIVE_AUTO_HOT_SYMBOLS:-false}}"
AUTO_HOT_TOP_N="${BFA_RAW_FEED_AUTO_HOT_TOP_N:-${BFA_LIVE_AUTO_HOT_TOP_N:-80}}"
AUTO_HOT_MIN_QUOTE_VOLUME="${BFA_RAW_FEED_AUTO_HOT_MIN_QUOTE_VOLUME_USDT:-${BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT:-10000000}}"
AUTO_HOT_MIN_ABS_CHANGE="${BFA_RAW_FEED_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT:-${BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT:-0.5}}"
AUTO_HOT_CRYPTO_ONLY="${BFA_RAW_FEED_AUTO_HOT_CRYPTO_ONLY:-${BFA_LIVE_AUTO_HOT_CRYPTO_ONLY:-true}}"
FALLBACK_SYMBOLS="${BFA_MARKET_SYMBOLS:-BTCUSDT,ETHUSDT,SOLUSDT,HYPEUSDT,ONDOUSDT,PUMPUSDT,SUIUSDT,NEARUSDT,ZECUSDT}"

mkdir -p "$OUTPUT_DIR"
cd "$APP_DIR"

truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

select_symbols() {
  if [[ -n "$SYMBOLS" ]]; then
    printf '%s\n' "$SYMBOLS"
    return 0
  fi
  if truthy "$AUTO_HOT"; then
    args=(
      scripts/select_raw_feed_symbols.py
      --base-url "$REST_BASE_URL"
      --top-n "$AUTO_HOT_TOP_N"
      --min-quote-volume-usdt "$AUTO_HOT_MIN_QUOTE_VOLUME"
      --min-abs-price-change-percent "$AUTO_HOT_MIN_ABS_CHANGE"
      --fallback-symbols "$FALLBACK_SYMBOLS"
    )
    if truthy "$AUTO_HOT_CRYPTO_ONLY"; then
      args+=(--crypto-only)
    fi
    if selected="$("$PYTHON" "${args[@]}")"; then
      printf '%s\n' "$selected"
      return 0
    fi
  fi
  printf '%s\n' "$FALLBACK_SYMBOLS"
}

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  output="$OUTPUT_DIR/binance-usdm-raw-${stamp}.gz"
  active_symbols="$(select_symbols)"
  "$PYTHON" scripts/record_binance_raw_feed.py \
    --symbols "$active_symbols" \
    --output "$output" \
    --base-url "$BASE_URL" \
    --depth-speed-ms "$DEPTH_SPEED_MS" \
    --duration-seconds "$ROTATE_SECONDS" \
    --seconds-cache-output "$SECONDS_CACHE_OUTPUT" \
    --seconds-cache-window "$SECONDS_CACHE_WINDOW" \
    --seconds-cache-flush-seconds "$SECONDS_CACHE_FLUSH_SECONDS"
  sleep 2
done
