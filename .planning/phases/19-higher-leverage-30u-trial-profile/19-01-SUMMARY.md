# Summary 19-01: 30U Higher-Leverage Trial Profile

## Completed

- Switched the server live profile to the requested 30 USDT trial caps:
  `BFA_ACCOUNT_CAPITAL_USDT=30`, `BFA_MAX_LEVERAGE=5`,
  `BFA_MAX_POSITION_NOTIONAL_USDT=12`,
  `BFA_MAX_RISK_PER_TRADE_USDT=0.3`,
  `BFA_MAX_DAILY_LOSS_USDT=1`, and `BFA_MAX_OPEN_POSITIONS=1`.
- Preserved live mode, DeepSeek provider selection, Binance credentials, cross
  margin, hedge position mode, protective-order requirement, and isolated
  deployment paths.
- Fixed signed Binance client list-payload handling so `positionRisk`,
  `openOrders`, and related read-only calls are not wrapped as a fake object.
- Added `openAlgoOrders` to live status so conditional TP/SL protective orders
  are visible in exchange evidence.

## Evidence

- Local focused tests passed: 34 tests across signed Binance client,
  live-status, reconciliation, agent runner, risk, and execution.
- Server focused tests passed: 34 tests.
- Server env validation passed in live mode with redacted 30U/5x profile values.
- Server DeepSeek health check had already passed after Phase 18 and remained
  configured as `BFA_AI_PROVIDER=deepseek`.
- Server live-status with Binance read-only checks reported:
  - Wallet balance around 29.96 USDT and available balance around 25.00 USDT.
  - One active ZECUSDT LONG position, quantity `0.032`, entry `467.68`, notional
    around 15 USDT, leverage `3`.
  - Zero normal open orders.
  - Two open algo orders for the ZECUSDT stop-loss and take-profit.
  - `lva05_complete=true` and `openai_backoff.active=false`.
- `binance-futures-agent-live.timer` and service were left inactive for safety
  while the pre-switch ZECUSDT position remains open.

## Live Caveat

A real ZECUSDT order was submitted before or during the profile change window
under the prior 100U/3x profile. The entry filled at `467.68`, and protective
algo orders exist with stop trigger `466.35` and take-profit trigger `471.49`.
Because this is a live position, automation remains paused until the position is
closed or the operator explicitly chooses to resume timer-based cycles while
`BFA_MAX_OPEN_POSITIONS=1` is active.
