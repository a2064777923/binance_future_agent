# Summary 45-01: Live Auto-Hot Candidate Breadth

## Completed

- Added live/dry-run auto-hot configuration:
  - `BFA_LIVE_AUTO_HOT_SYMBOLS`
  - `BFA_LIVE_AUTO_HOT_TOP_N`
  - `BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT`
  - `BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT`
- Kept live auto-hot disabled by default in code and env examples.
- Reused the existing Binance USD-M 24h ticker hot-symbol ranking logic.
- Added `run_agent_once` symbol resolution so auto-hot symbols are used for:
  - market data collection;
  - manual/RSS narrative known symbols;
  - market-heat fallback;
  - replay packet `symbols`;
  - candidate allowlisting.
- Added `scan_symbols` to agent run output so each cycle shows what universe was
  scanned.
- Preserved `agent run-once --top-n` behavior: it still limits how many ranked
  candidates are evaluated, not how many symbols can be scanned.
- Documented the difference between live auto-hot scanning and paper auto-hot
  observation.

## Evidence

- Focused local tests passed with `31` tests:
  `tests.test_config`, `tests.test_deploy_assets`, and focused agent runner
  auto-hot tests.
- `tests.test_agent_runner` passed with `10` tests.
- Focused CLI regression checks passed with `2` tests.
- Full local suite passed with `335` tests.
- `git diff --check` passed.
- Secret-pattern scan over `git diff` found no matches.

## Not Changed

- Live timer was not restored.
- Server env was not modified.
- Leverage, sizing, risk profile, max open positions, and live service/timer
  state were not changed.
- No exchange order, close, or position adjustment was executed.

## Operational Result

The live runner no longer has to be limited to the fixed 10-symbol pilot
allowlist when explicitly configured otherwise. It can scan a wider auto-hot
universe while still passing candidates through deterministic setup scoring,
AI overlay or quant fallback, execution filters, risk caps, and the
one-order-per-cycle limit.

## Next

Deploy the code-only change to the server without enabling
`BFA_LIVE_AUTO_HOT_SYMBOLS`, then run dry-run/manual evidence before deciding
whether live env should opt into wider scanning.
