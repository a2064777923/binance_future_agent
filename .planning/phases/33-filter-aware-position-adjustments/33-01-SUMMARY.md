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

## Operational Result

Small-account staged exits are now less likely to produce Binance-rejected
reduce orders, especially when a half-position take-profit would be below the
symbol minimum notional. Confirmed live adjustment execution still requires the
fresh plan-derived token and was not run.
