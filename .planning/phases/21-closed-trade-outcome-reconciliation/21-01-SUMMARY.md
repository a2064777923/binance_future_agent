# Summary 21-01: Closed Trade Outcome Reconciliation

## Completed

- Added signed Binance `userTrades` support through
  `BinanceFuturesSignedClient.user_trades`.
- Added trade outcome reconstruction from the latest locally submitted intent
  plus Binance account trade fills.
- Added `ops trade-outcome` with optional `--persist`.
- Persisted fills and round-trip outcome artifacts into existing event-store
  tables.
- Made persistence idempotent by fill/outcome `ref_id` so repeated
  reconciliation does not duplicate accounting artifacts.
- Deployed the Phase 21 source and focused tests to
  `/opt/binance-futures-agent/app`.

## Evidence

- Local focused suite passed: 35 tests.
- Server focused suite passed: 35 tests.
- Server `ops trade-outcome --symbol ZECUSDT --persist` reconstructed the
  closed ZECUSDT LONG:
  - gross realized PnL `0.12288` USDT
  - commission `0.0150272` USDT
  - net realized PnL `0.1078528` USDT
  - status `closed`
  - 2 fills and 1 outcome persisted
- A repeated server reconciliation inserted no duplicates:
  `fills=0`, `fills_existing=2`, `outcome_inserted=0`.
- Post-run live-status still showed the separate BNBUSDT LONG protected by two
  algo orders; Phase 21 did not modify exchange state.
