---
phase: 21-closed-trade-outcome-reconciliation
verified: 2026-06-20T11:58:00+08:00
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
---

# Phase 21: Closed Trade Outcome Reconciliation Verification Report

**Phase Goal:** Reconstruct the first completed live trade from Binance fills
and persist net-of-commission outcome evidence.
**Verified:** 2026-06-20
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Signed client can call Binance `userTrades`. | VERIFIED | Local and server focused suites passed `tests.test_execution_binance_client`; client uses `GET /fapi/v1/userTrades` with signed params. |
| 2 | Outcome report computes gross PnL, commission, net PnL, net quantity, fill times, and closed status. | VERIFIED | Live ZECUSDT output reported `gross_realized_pnl_usdt=0.12288`, `commission_usdt=0.0150272`, `net_realized_pnl_usdt=0.1078528`, `net_quantity=0.0`, first fill `2026-06-20T02:49:22.837000Z`, last fill `2026-06-20T03:29:50.055000Z`, and `status=closed`. |
| 3 | `ops trade-outcome --persist` writes `fills` and `outcomes` artifacts. | VERIFIED | Server DB counts changed from `fills=0,outcomes=0` to `fills=2,outcomes=1`; latest outcome ref is `outcome:127052:closed`. |
| 4 | Re-running persistence is idempotent by Binance fill/outcome refs. | VERIFIED | Second server run returned `fills=0`, `fills_existing=2`, `outcome_inserted=0`, and existing outcome event `142596`; unit test covers the same behavior. |
| 5 | Server live run reconstructs ZECUSDT without modifying exchange state. | VERIFIED | Command only used read-only Binance trade history plus local SQLite writes. Post-run live-status still showed the existing BNBUSDT LONG with two protective algo orders, no normal open orders, timer active, and service inactive. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_execution_outcome tests.test_execution_binance_client tests.test_cli` | Passed locally, 35 tests |
| Same focused suite on `/opt/binance-futures-agent/app` | Passed on server, 35 tests |
| `ops trade-outcome --symbol ZECUSDT --persist` on server | Passed; found closed ZECUSDT outcome and inserted 2 fills plus 1 outcome |
| Repeated `ops trade-outcome --symbol ZECUSDT --persist` on server | Passed; inserted no duplicate fills/outcome |
| Server `ops live-status --check-binance` after reconciliation | Passed; BNBUSDT position remained protected by stop-loss and take-profit algo orders |

## Live Outcome Evidence

- Intent event: `127052`, ZECUSDT LONG, quantity `0.032`, local entry reference
  `468.09`, leverage `3`, occurred at `2026-06-20T02:49:17Z`.
- Entry fill: BUY `0.032` at `467.68`, quote `14.96576`, commission
  `0.00748288` USDT, trade id `1230037828`.
- Exit fill: SELL `0.032` at `471.52`, quote `15.08864`, realized PnL
  `0.12288` USDT, commission `0.00754432` USDT, trade id `1230090450`.
- Net result: gross realized PnL `0.12288` USDT, total commission `0.0150272`
  USDT, net realized PnL `0.1078528` USDT, net quantity `0.0`, `status=closed`.

## Current Live State Note

The timer resumed after Phase 20 and later opened a separate BNBUSDT LONG under
the 30U/5x profile. At Phase 21 verification time that BNBUSDT position was
still open with exchange-visible stop-loss and take-profit algo orders. Phase 21
did not cancel, close, or modify that position.

## Gaps Summary

No Phase 21 gaps found. Closed-trade accounting is now available for the first
completed live trade, and repeated reconciliation does not duplicate local
fill/outcome artifacts.
