# Context 45: Live Auto-Hot Candidate Breadth

## Trigger

The operator asked why the hot-coin list only has 10 symbols. Investigation
showed that the paper timer already uses auto-hot selection with `--top-n 40`,
but the live runner still uses the fixed `BFA_MARKET_SYMBOLS` 10-symbol
allowlist and evaluates only `agent run-once --top-n 3`.

## Decisions

- **D-01:** Add live/dry-run auto-hot scanning as an optional capability, not as
  a default live behavior.
- **D-02:** Preserve `BFA_MARKET_SYMBOLS` as the fallback and controlled pilot
  universe when live auto-hot is disabled, unavailable, or returns no symbols.
- **D-03:** Reuse the existing Binance 24h ticker hot-universe ranking logic
  already used by backtest matrix and forward-paper auto-hot selection.
- **D-04:** Make the selected symbol universe consistent across market
  collection, narrative parsing, market-heat fallback, replay packet symbols,
  and candidate allowlisting.
- **D-05:** Do not restore live automation, change leverage, change position
  size, or widen order authority in this phase. Wider scanning still flows
  through the existing `--top-n`, setup, AI overlay or quant fallback, and risk
  gates.

## Current Evidence

- `src/bfa/config.py` defaults `BFA_MARKET_SYMBOLS` to 10 symbols.
- `src/bfa/agent.py` uses `market_symbols(config)` for collector symbols,
  replay packet symbols, narrative known symbols, market-heat fallback, and
  candidate allowed symbols.
- `deploy/systemd/binance-futures-agent-live.service` runs
  `agent run-once --top-n 3`.
- `deploy/systemd/binance-futures-agent-paper.service` already uses
  `ops forward-paper-run --auto-hot-symbols --top-n 40`.
- Server state after Phase 44: paper timer active; live service and live timer
  inactive.

## Constraints

- No signed endpoint is needed for selecting hot symbols.
- The all-symbol 24h ticker request is public but broader than explicit-symbol
  requests, so keep top-N and liquidity/change filters configurable.
- `MarketDataCollector` still has a `max_symbols` cap of 10 by default; live
  auto-hot must pass an explicit max matching the selected universe size.
- This phase must not put secrets in docs, logs, commits, or command output.
