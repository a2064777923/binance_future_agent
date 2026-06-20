# Summary 29-01: Confirmation-Gated Risk Profile Switch

## Completed

- Added `ops risk-profile-plan` to preview a named risk profile env diff.
- Added `ops risk-profile-apply` with confirmation-token gating.
- Added named profile `30u_8x_dynamic`.
- Added optional `--allow-two-positions` preview/apply mode.
- Apply refuses to write when the live service is active, confirmation is
  missing, or `ops risk-change-check` does not allow the target leverage.
- Apply writes only approved non-secret BFA risk/profile keys and creates a
  timestamped env backup.
- Added unit and CLI tests for plan diff, token mismatch, risk-change blocking,
  backup creation, and secret preservation.

## Evidence

- Focused local suite passed: 13 tests.
- Full local suite passed: 264 tests.
- Server focused suite passed: 13 tests.
- Server full suite passed: 264 tests.
- Server `risk-profile-plan` returned the 8x dynamic diff and token.
- Server apply without token returned `confirmation_required`.
- Server apply with token returned `apply_blocked` because HYPEUSDT is still
  open and unreconciled.
- Server env remained `BFA_MAX_LEVERAGE=5`,
  `BFA_MAX_POSITION_NOTIONAL_USDT=12`, and `BFA_MAX_OPEN_POSITIONS=1`.

## Operational Result

The system now has a safe switch mechanism for later moving from the current
5x/12U/one-position profile to the 30U/8x dynamic profile. The live server env
has not been changed and must not be changed while HYPEUSDT remains open.
