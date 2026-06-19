# Research: Pitfalls

**Date:** 2026-06-19

## Strategy Pitfalls

- Public screenshots of extreme compounding are not a reproducible strategy.
  Treat them as inspiration for signal families, not as expected returns.
- Hot coins can pump before the collector sees them. Late entries need strict
  invalidation and time stops.
- Binance Square/social data can be manipulated, botted, delayed, or API-limited.
- Low-cap futures pairs have slippage, thin books, liquidation wicks, and sudden
  funding changes.
- Open interest increases can mean aggressive longs or shorts; pair with price
  movement, taker flow, funding, and liquidation context.

## Execution Pitfalls

- A 100 USDT account has very little room for fees, funding, spread, and
  slippage. High leverage can wipe out the pilot quickly.
- Binance futures filters, min notional, tick size, step size, and leverage
  brackets must be enforced before order placement.
- Stop orders can fail or be rejected if price/filter logic is wrong.
- User-data stream disconnects can leave local state stale; reconcile account
  state through REST.
- Live mode must never be the default.

## Data Pitfalls

- Binance Square reading may not have a stable official public read API.
  Browser/export/manual ingestion must be first-class, not a hack.
- Social API credentials and cookies are secrets; never log them.
- Time synchronization matters for kline/event alignment.
- Duplicate posts and symbol aliases can inflate narrative scores.

## Deployment Pitfalls

- The target server already has projects. Deployment must use a dedicated
  directory, unit name, env file, and log paths.
- Running as root is operationally simple but high blast radius. The unit should
  eventually move to a dedicated user if possible.
- Never put exchange keys into shell history, command arguments, git, or systemd
  unit files. Use an env file with restrictive permissions.

## Mitigations For V1

- Start with dry-run and connectivity checks.
- Require explicit `BFA_MODE=live` for live orders.
- Keep default leverage at max 3x.
- Cap each position at 20 USDT notional and 1 USDT intended risk.
- Stop trading after 3 USDT daily realized/unrealized loss.
- Require a kill switch file check before every order.
- Persist all model decisions and risk-gate decisions before execution.
