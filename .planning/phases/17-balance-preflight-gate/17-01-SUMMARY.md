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
- Server focused tests passed 21 tests after deployment.
- Server health check passed in live mode with redacted secrets.
- Server read-only futures account balance showed `availableBalance=0.00000000`.
- Server safe preflight using the real account payload and fake order methods
  returned `status=rejected`, `submitted=false`,
  `risk_reasons=insufficient_available_balance`, and `calls=account`.
- Post-deploy live timer cycle exited 0 with `ai_rejected` invalid JSON from
  the OpenAI-compatible endpoint and no submission.
- Live timer was re-enabled and active after deployment.

## Follow-Up

- Fund or transfer USDT into the Binance USD-M futures account before expecting
  a real entry submission.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
