# Summary 33-01: Filter-Aware Position Adjustments

## Completed

- Adjustment planning now can load Binance exchangeInfo and build
  `SymbolExecutionFilters` for active-position symbols.
- Partial take-profit quantities are rounded down to step size.
- Partial take-profit plans are blocked when quantity or notional would fail
  exchange filters.
- Read-only adjustment previews now fail closed for actionable plans when
  symbol filters are missing.
- Confirmed adjustment execution requires exchange filters before any live
  reduce order is submitted.

## Evidence

- Focused local suites passed: position adjustment, CLI, and agent runner
  (`52` tests).
- Full local suite passed: `293` tests.
- Server focused suite passed: `52` tests.
- Server full suite passed: `293` tests.
- Server secret-safe health check passed with Binance public and DeepSeek API
  checks enabled.
- Server read-only `ops position-adjustment-plan` preview returned
  `adjustment_plan_ready` for protected `SOLUSDT` LONG `0.16`; the filter-aware
  close plan is `SELL MARKET 0.16`, `positionSide=LONG`, with
  `quantity_filter_checked`.
- Follow-up read-only preview at `2026-06-20T11:55:29Z` still reported
  `adjustment_plan_ready` for protected `SOLUSDT` LONG `0.16`, about 34.37
  minutes into a 15-minute hold window. The live timer is paused while the
  operator reviews this open position and the sizing/profile question.
- Server `ops exposure-status --target-profile 30u_10x_multi_dynamic
  --allow-two-positions` still reports `ready_for_profile_switch`; no profile
  apply was run.

## Operational Result

Small-account staged exits are now less likely to produce Binance-rejected
reduce orders, especially when a half-position take-profit would be below the
symbol minimum notional. Confirmed live adjustment execution still requires the
fresh plan-derived token and was not run.
