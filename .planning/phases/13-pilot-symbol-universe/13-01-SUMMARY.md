# Summary 13-01: Pilot Symbol Universe

## Completed

- Queried current Binance USD-M public data to identify symbols with:
  - `status=TRADING`;
  - perpetual USDT contracts;
  - high 24h quote volume;
  - minimum executable notional within the 20 USDT pilot cap.
- Updated default `BFA_MARKET_SYMBOLS` to:
  `HYPEUSDT,SOLUSDT,ZECUSDT,WLDUSDT,XRPUSDT,AVAXUSDT,BNBUSDT,DOGEUSDT,NEARUSDT,ADAUSDT`.
- Updated `.env.example` and `deploy/server-env.example`.
- Updated config tests to assert the new controlled allowlist.
- Updated CLI strategy fixture tests to pass their BTC/ETH fixture allowlist
  explicitly.

## Evidence

- Current Binance public-data check showed many high-liquidity symbols fit the
  20 USDT cap; BTCUSDT and ETHUSDT did not.
- `python -m unittest tests.test_config tests.test_market_collector tests.test_agent_runner`
  passed 22 tests.
- `python -m unittest discover -s tests` passed 187 tests.

## Follow-Up

- Deploy the new defaults.
- Update `/etc/binance-futures-agent/env` on the server with the selected symbol
  list, preserving all existing secrets and risk caps.
- Observe the next timer cycle for candidate/AI behavior.
