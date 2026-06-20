# Summary 17-01: Balance Preflight Gate

## Completed

- Added a live account-balance preflight before margin setup and entry order
  placement.
- Rejected order intents with `insufficient_available_balance` when Binance
  futures `availableBalance` is below the estimated initial margin.
- Rejected order intents with `account_balance_check_failed:<code>` when the
  Binance account read fails.
- Rejected order intents with `account_available_balance_unknown` when the
  account payload does not contain a parseable available balance.
- Added execution regressions for insufficient balance and account-read failure.
- Preserved dry-run, testnet, cross-margin, hedge-position, and
  protective-order behavior.

## Evidence

- `python -m unittest tests.test_execution_executor` passed 10 tests.
- `python -m unittest discover -s tests` passed 197 tests.
- `git diff --check` passed with Windows LF-to-CRLF warnings only.
- Secret scan over changed files reported only synthetic test fixture key names;
  no real secret values were found.

## Follow-Up

- Deploy to `/opt/binance-futures-agent`.
- Keep `BFA_MARGIN_MODE=cross`, `BFA_POSITION_MODE=hedge`, and all pilot caps
  unchanged.
- Observe the next live timer cycle. With the currently unfunded USD-M futures
  account, the expected result is a local rejection with
  `insufficient_available_balance` and no entry order attempt.
- Fund or transfer USDT into the Binance USD-M futures account before expecting
  a real entry submission.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
