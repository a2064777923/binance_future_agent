---
gsd_state_version: 1.0
milestone: v1.15
milestone_name: Closed Outcome Risk Change Strictness
current_phase: Phase 23 - Closed Outcome Risk Change Strictness
status: completed
stopped_at: Phase 23 verified; partial outcomes cannot unlock leverage/risk changes
last_updated: "2026-06-20T12:24:00.000+08:00"
last_activity: 2026-06-20
last_activity_desc: Closed-outcome strictness deployed and verified for risk-change readiness
progress:
  total_phases: 15
  completed_phases: 15
  total_plans: 15
  completed_plans: 15
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 23 - Closed Outcome Risk Change Strictness
**Status:** v1.15 complete; partial/open outcomes must not unlock
leverage/risk-cap profile changes
**Last planned:** 2026-06-20
**Plan count:** 1

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.

## Decisions

- New project directory: `F:\binance_futures_agent`.
- Deployment target: `64.83.34.222`, isolated under
  `/opt/binance-futures-agent`.
- AI provider: DeepSeek is selected for live use; OpenAI-compatible Responses
  API remains available as a fallback provider.
- Exchange: Binance USD-M futures.
- Active trial profile: 30 USDT account capital, 5x max leverage, 12 USDT max
  position notional, 0.3 USDT max per-trade risk, 1 USDT max daily loss, and
  1 open position.
- Timer resume must now be gated by read-only `ops resume-check`.
- First strategy: hot coins from Binance Square and fallback narrative sources.
- Backtest discipline: use short-window staged sweeps with completed candles,
  next-candle entries, fees/slippage, and small-capital caps before any scale-up.
- Project mode: horizontal layers.
- Workflow config: Standard granularity, parallel execution enabled, planning
  docs committed, research/check/verifier enabled.

## Open Risks

- Binance Square read access may require browser/export/manual collection or
  other adapters because stable official public read APIs are not guaranteed.
- Live futures trading with 30 USDT is highly sensitive to fees, spread,
  slippage, liquidation wicks, and API outages.
- Server already hosts other projects, so deployment scripts must be narrowly
  scoped and reviewed before running.
- Secrets were provided out-of-band and must be rotated or handled carefully
  before production deployment.
- Historical Square/social narrative data is not yet complete, so the first
  backtest layer validates a market-heat proxy rather than claiming to reproduce
  a private Lana-style social alpha system.
- Current Binance filters can make large-cap symbols incompatible with small
  max-position-notional caps, so pilot tradability filtering must remain active
  until risk caps are explicitly changed.
- Cross margin mode is explicit via `BFA_MARGIN_MODE=cross`; account-level
  collateral behavior still requires conservative absolute notional and loss
  caps.
- Binance hedge position mode is explicit via `BFA_POSITION_MODE=hedge`; entry,
  protective, and emergency orders must keep sending `positionSide`.
- The pre-switch ZECUSDT LONG has cleared. The resume gate permitted timer
  resume because there were no active positions, no normal open orders, no open
  algo orders, and no active AI backoff.
- The first two resumed timer cycles exited 0 with `submitted=false` and
  `risk_reasons=["ai_decision_pass"]`.
- A later timer cycle opened a BNBUSDT LONG under the 30U/5x profile; live-status
  shows the position has exchange-visible stop-loss and take-profit algo orders.
- The first closed live ZECUSDT trade is reconciled from Binance fills:
  gross PnL `0.12288` USDT, commission `0.0150272` USDT, net PnL
  `0.1078528` USDT, and `status=closed`.
- `ops risk-change-check --target-leverage 8` currently returns
  `keep_current_profile` because BNBUSDT is still open, protected by two algo
  orders, and its submitted intent event `138150` has no persisted outcome yet.

## Next Command

After BNBUSDT closes, run `ops trade-outcome --symbol BNBUSDT --persist`, then
rerun `ops risk-change-check --target-leverage 8` before changing the live
profile.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 23 - Closed Outcome Risk Change Strictness
Plan: 23-01 complete
Status: risk-change gate now requires `closed` outcomes before submitted
intents are considered reconciled for profile changes
Last activity: 2026-06-20 - Phase 23 verified

## Operator Next Steps

- Observe the current BNBUSDT live position and its protective orders.
- Run `ops trade-outcome --symbol BNBUSDT --persist` after BNBUSDT closes.
- Rerun `ops risk-change-check --target-leverage 8` before any leverage change.
- Do not raise leverage/risk caps while a live position is open unless
  explicitly reviewed.
- Run `ops resume-check` before any future manual timer resume.
- Rerun staged matrix backtests before any further risk-limit increase.
