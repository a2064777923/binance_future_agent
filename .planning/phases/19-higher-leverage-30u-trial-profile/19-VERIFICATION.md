---
phase: 19-higher-leverage-30u-trial-profile
verified: 2026-06-20T11:13:00+08:00
status: passed_with_timer_paused
score: 6/6 must-haves verified
behavior_unverified: 0
---

# Phase 19: 30U Higher-Leverage Trial Profile Verification Report

**Phase Goal:** Reconfigure the live pilot for a 30 USDT funded trial with a
5x leverage ceiling while keeping absolute downside tighter than the 100 USDT
profile.
**Verified:** 2026-06-20
**Status:** passed with timer paused for live-position review

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Server env changes only the active trial risk profile values. | VERIFIED | Redacted server env showed the 30U/5x profile while preserving live mode, DeepSeek, cross margin, hedge mode, protective orders, and isolated paths. |
| 2 | Trial profile is `30U capital`, `5x`, `12U notional`, `0.3U trade risk`, `1U daily loss`, and `1` open position. | VERIFIED | Server config validation reported exactly those cap values. |
| 3 | DeepSeek, Binance credentials, cross margin, hedge position mode, protective-order requirement, and isolated systemd paths remain unchanged. | VERIFIED | Redacted env and systemd checks preserved `/opt/binance-futures-agent`, `/etc/binance-futures-agent/env`, `BFA_AI_PROVIDER=deepseek`, `BFA_MARGIN_MODE=cross`, `BFA_POSITION_MODE=hedge`, and `BFA_REQUIRE_PROTECTIVE_ORDERS=true`. |
| 4 | Server health and focused tests pass after the profile switch. | VERIFIED | Local focused suite passed 34 tests; server focused suite passed 34 tests. Earlier Phase 19 health checks passed with 30U profile and DeepSeek API reachable. |
| 5 | Live-status shows accurate exchange state after the switch. | VERIFIED | After fixing list payload handling and adding algo-order evidence, server `ops live-status --check-binance` showed one ZECUSDT position, zero normal open orders, two open algo orders, `lva05_complete=true`, and `openai_backoff.active=false`. |
| 6 | Automation is not resumed blindly while a live position is open. | VERIFIED | `binance-futures-agent-live.timer` and service are inactive; this is intentional until the pre-switch ZECUSDT position is closed or explicitly reviewed for resume. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_execution_binance_client tests.test_ops_live_status tests.test_ops_live_status_binance tests.test_execution_reconcile tests.test_agent_runner tests.test_execution_risk tests.test_execution_executor` | Passed locally, 34 tests |
| Same focused suite on `/opt/binance-futures-agent/app` | Passed on server, 34 tests |
| Server `ops live-status --check-binance` | Passed; account around 29.96 USDT wallet, one ZECUSDT position, two open algo orders, no AI backoff |

## Live Exchange Evidence

- Pre-switch submitted intent: ZECUSDT LONG, quantity `0.032`, notional around
  15 USDT, leverage `3`, event `127052`.
- Entry order: Binance order `802424848050`, status `FILLED`, average price
  `467.68`.
- Position risk: ZECUSDT LONG `0.032`, cross margin, leverage `3`, notional
  around 15 USDT.
- Protective orders: stop-loss algo `3000001898656544` with trigger `466.35`,
  and take-profit algo `3000001898656545` with trigger `471.49`.
- Normal open orders: none.
- Open algo orders: two.

## Human Verification Required

The operator should review the open ZECUSDT position in Binance. The timer can be
re-enabled after the position closes, or earlier only with explicit approval to
let the agent continue scanning while `BFA_MAX_OPEN_POSITIONS=1` blocks new
entries.

## Gaps Summary

No Phase 19 configuration or monitoring gaps remain. The only outstanding action
is an operational decision about whether to keep the timer paused until the
current ZECUSDT position exits.
