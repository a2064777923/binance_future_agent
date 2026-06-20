# Summary 30-01: Portfolio Risk And Multi-Position Profile

## Completed

- Added portfolio cap config keys for margin, margin fraction, notional, and
  same-direction notional.
- Extended live risk state extraction to include active exposure notional,
  initial margin, and leverage when Binance position data provides them.
- Added deterministic risk gates for portfolio margin, portfolio margin
  fraction, portfolio notional, and same-direction notional.
- Preserved duplicate same-symbol same-direction rejection.
- Verified that the live runner no longer early-stops solely because an
  existing position is open when multi-position mode is enabled and capacity
  remains.
- Added candidate-queue evaluation: when the first hot symbol is skipped by AI
  pass or retryable symbol-level risk such as duplicate same-direction exposure,
  the runner can evaluate the next top-N candidate while still submitting at
  most one order per cycle.
- Extended risk-change readiness so a protected active position can be carried
  into a target multi-position profile when the active notional, initial margin,
  same-direction exposure, and position count fit that profile's caps.
- Added `30u_10x_multi_dynamic`, a confirmation-gated high-leverage
  two-position profile for preview/apply tooling.
- Extended `ops exposure-status` and docs/env examples with portfolio cap
  context.

## Evidence

- Focused local suite passed: 67 tests after target-profile readiness and
  candidate-queue coverage.
- Full local suite passed: 278 tests.
- `git diff --check` passed with Windows LF-to-CRLF warnings only.
- `python -m bfa.cli ops risk-profile-plan --profile 30u_10x_multi_dynamic`
  returns a confirmation-gated diff and token.

## Operational Result

The code can now support a more mature multi-position/high-leverage trial path:
existing HYPEUSDT no longer has to freeze all scanning when an approved
multi-position profile is active, and it no longer has to block a profile
switch solely because the protected active exposure can be carried into the new
portfolio caps. The live server env has not been changed by this phase.
