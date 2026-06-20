# Summary 28-01: Dynamic Sizing And Multi-Position Guard

## Completed

- Added dynamic sizing config keys while keeping fixed notional caps as the
  default behavior.
- Added `execution.sizing` to compute per-trade notional from account capital,
  available balance, leverage, max margin fraction, max margin per position,
  max effective notional, stop distance, and exchange minimum executable
  notional.
- Fed computed sizing into strategy candidate filtering, AI risk context, and
  final execution risk validation.
- Extended `RiskLimits` to include sizing evidence for model context and audit
  output.
- Added `RiskState.active_exposures` and multi-position guards.
- Kept multi-position disabled by default.
- Allowed multi-position only when `BFA_MULTI_POSITION_ENABLED=true`, while
  preserving `BFA_MAX_OPEN_POSITIONS` and rejecting same-symbol same-direction
  duplicate exposure.

## Evidence

- Focused local suite passed: 21 tests.
- Full local suite passed: 257 tests.
- Server focused suite passed: 21 tests.
- Server full suite passed: 257 tests.
- Server env readback confirms live profile remains `5x`, `12U` max notional,
  one open position, `BFA_DYNAMIC_POSITION_SIZING_ENABLED=false`, and
  `BFA_MULTI_POSITION_ENABLED=false`.

## Operational Result

The codebase can now support a later approved profile such as 30U/8x with
dynamic notional around 19.2U under an 8% margin fraction. The live server env
has not been changed, so current trading remains under the existing 5x/12U/one
position profile until a separate approved profile switch.
