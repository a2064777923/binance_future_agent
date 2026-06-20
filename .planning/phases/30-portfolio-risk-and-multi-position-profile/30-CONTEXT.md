# Phase 30 Context: Portfolio Risk And Multi-Position Profile

## User Direction

The operator explicitly redirected the project away from waiting for the current
HYPEUSDT position to close. A mature crypto futures system should keep tracking
open positions while still scanning for new opportunities, especially when
market conditions change quickly.

## Strategy Translation

Public Lana / "大神" style claims are treated as inspiration, not proof. The
testable parts to translate are:

- hot-coin and narrative scanning should continue while a position is open;
- open positions need ongoing review rather than freezing the whole agent;
- the system should work from a queue of hot symbols, not one all-or-nothing
  candidate;
- higher leverage must be bounded by explicit capital, margin, notional, and
  concentration budgets;
- multi-position behavior must reject duplicate same-symbol same-direction
  exposure;
- any live profile switch must remain confirmation-gated.

## Current System

- Phase 28 added dynamic sizing and a basic multi-position switch.
- Phase 29 added confirmation-gated profile preview/apply.
- The live env remains unchanged at 30U/5x/12U/one-position while HYPEUSDT is
  open.
- The new work should add code and tests only; it must not silently switch the
  server live profile.

## Success Criteria

1. Existing HYPEUSDT-style active position no longer forces early-stop when
   multi-position mode has capacity.
2. Candidate evaluation can move past a duplicate or AI-pass first candidate to
   another top-N hot symbol while still submitting at most one order per cycle.
3. New entries are still blocked when portfolio margin, margin fraction,
   portfolio notional, same-direction notional, max positions, or duplicate
   exposure caps would be exceeded.
4. A `30u_10x_multi_dynamic` profile can be previewed and later applied only
   through the existing confirmation-gated path.
5. A protected active position can be carried into a target multi-position
   profile only when exchange protection and portfolio caps are both verified.
6. Exposure status explains portfolio budget context.
7. Full test suite passes.
