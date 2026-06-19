# Phase 2 Research: Binance Futures Market Data Layer

**Date:** 2026-06-19
**Sources:** Official Binance USD-M Futures developer docs only.
**Note:** The typed research subagent failed before writing this file with an
upstream stream error, so this research was completed inline using official
Binance documentation.

## Phase Goal

Build the official Binance USD-M futures market data layer:

- MKT-01: fetch exchange metadata and symbol filters.
- MKT-02: fetch ticker, kline, funding, open interest, long/short, and taker
  buy/sell data for candidate symbols.
- MKT-03: subscribe to relevant public WebSocket market streams.
- MKT-04: store normalized market snapshots with source, timestamp, and symbol
  metadata.

## Official API Facts

### General Rules

Official docs state:

- Production REST base endpoint: `https://fapi.binance.com`.
- Testnet REST base endpoint: `https://demo-fapi.binance.com`.
- Production WebSocket base endpoint: `wss://fstream.binance.com`.
- Testnet WebSocket base endpoint: `wss://fstream.binancefuture.com`.
- Timestamp fields use milliseconds.
- GET endpoint parameters are query-string parameters.
- Public market-data endpoints in this phase should not require signed private
  account credentials.
- Responses may include request-weight headers; callers must back off on 429
  and avoid repeated rate-limit violations.

Source:
`https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`

### REST Endpoints To Implement

| Capability | Endpoint | Weight / Limits Noted In Docs | Phase Use |
|------------|----------|--------------------------------|-----------|
| Exchange metadata | `GET /fapi/v1/exchangeInfo` | documented as exchange info; includes `rateLimits` and symbol metadata | MKT-01 symbol filters, status, contract metadata |
| 24h ticker stats | `GET /fapi/v1/ticker/24hr` | heavier when all symbols are requested | MKT-02 price/volume/change features |
| Klines | `GET /fapi/v1/klines` | weight varies by `limit` | MKT-02 OHLCV/volatility features |
| Funding history | `GET /fapi/v1/fundingRate` | default/recent records behavior documented | MKT-02 derivatives carry/funding features |
| Current open interest | `GET /fapi/v1/openInterest` | request weight 1 | MKT-02 current interest snapshot |
| Open interest history | `GET /futures/data/openInterestHist` | request weight 0; IP rate limit documented; latest month only | MKT-02 trend/anomaly feature |
| Top trader long/short position ratio | `GET /futures/data/topLongShortPositionRatio` | request weight 0; latest 30 days only | MKT-02 sentiment/positioning feature |
| Taker buy/sell volume | `GET /futures/data/takerlongshortRatio` | request weight 0; latest 30 days only | MKT-02 flow feature |

Sources:

- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Top-Trader-Long-Short-Ratio`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Taker-BuySell-Volume`

### WebSocket Streams

Official docs state:

- WebSocket routed base paths include `/public`, `/market`, and `/private`.
- Combined streams use `/stream?streams=<stream1>/<stream2>`.
- Raw stream mode uses `/ws/<streamName>`.
- Combined stream events are wrapped as `{"stream": "...", "data": ...}`.
- Stream symbols are lowercase.
- A connection is valid for 24 hours.
- The server sends ping frames every 3 minutes and expects pong within 10
  minutes.
- Incoming messages are limited to 10 per second.
- A single connection can listen to up to 1024 streams.

Phase 2 should support public/market stream URL building and parsing for the
market streams that later phases need:

- `symbol@ticker` or mini ticker for 24h updates.
- `symbol@kline_<interval>` for live candles.
- `symbol@markPrice` for mark/funding context if used in plans.
- `symbol@bookTicker` for best bid/ask snapshots if used in plans.

Do not implement `/private` or user-data listen-key streams in this phase.

Source:
`https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams`

## Recommended Architecture

### Modules

Use a small dependency-free shape:

- `src/bfa/market/binance_rest.py`
  - REST transport protocol.
  - URL/query building.
  - Public endpoint methods.
  - Structured `BinanceMarketDataError`.
- `src/bfa/market/models.py`
  - Dataclasses for exchange symbols, filters, normalized snapshots, and REST
    response wrappers.
- `src/bfa/market/normalize.py`
  - Converters from Binance payloads to normalized snapshots.
- `src/bfa/market/binance_ws.py`
  - Stream name builders, combined stream URL builders, and message parser.
  - Keep actual long-running reconnect loop minimal or adapter-shaped.
- `src/bfa/market/collector.py`
  - Symbol allowlist orchestration for REST snapshot collection.
- `tests/fixtures/binance_market/*.json`
  - Static fixture payloads based on official response shapes, with no real
    user data.

### Normalized Snapshot Shape

Every normalized market record should include:

- `source`: e.g. `binance_usdm`.
- `event_type`: e.g. `exchange_symbol`, `ticker_24h`, `kline`,
  `funding_rate`, `open_interest`, `open_interest_hist`,
  `top_long_short_position`, `taker_buy_sell_volume`, `ws_ticker`,
  `ws_kline`, `ws_mark_price`, `ws_book_ticker`.
- `symbol`.
- `event_time`: exchange event timestamp when available.
- `received_at`: local ingestion timestamp in milliseconds or ISO UTC.
- `payload`: source-specific normalized fields.

This gives Phase 3/5/6 a stable market-data interface while deferring durable
event storage to Phase 4.

## Testing Strategy

- Unit tests should not call live Binance.
- REST tests use fake transport objects that capture method, path, params, and
  return static JSON fixtures.
- Error tests cover non-2xx status, Binance `{code,msg}` error payloads, and
  timeout/transport exceptions.
- Normalization tests cover representative payloads for exchange info, ticker,
  kline, funding, open interest, long/short ratio, and taker buy/sell volume.
- WebSocket tests cover stream name lowercasing, combined URL construction,
  combined event wrapper parsing, raw event parsing, and unknown stream handling.
- Optional integration smoke command can be added but should default off and
  must require explicit opt-in to hit live Binance.

## Pitfalls And Constraints

- Avoid all-symbol heavy endpoints by default; prefer explicit symbol allowlists.
- Do not copy Binance docs' example credentials or signed endpoint examples into
  project artifacts. Phase 2 is public market data only.
- Preserve request-weight headers where the transport exposes them; later phases
  can use this for pacing.
- Do not parse decimals as floats where exact filters matter. Keep string values
  or use `decimal.Decimal` for price/quantity filter data.
- Binance WebSocket stream symbols are lowercase; local user config may be
  uppercase. Normalize stream names carefully while preserving normalized output
  symbol casing.
- Keep route paths explicit in tests so endpoint typos are caught before live
  usage.

## Plan Recommendation

1. REST foundation and exchange metadata.
2. REST market metrics for selected symbols.
3. Normalized snapshot model and optional JSONL writer.
4. WebSocket stream utilities and parsers.
5. CLI smoke commands and final phase verification.

The plan count can be 4-5 depending on granularity. Keep each plan testable
without live credentials.

## Research Complete

This research supports Phase 2 planning for MKT-01 through MKT-04.
