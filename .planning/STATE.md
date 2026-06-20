---
gsd_state_version: 1.0
milestone: v1.20
milestone_name: Dynamic Sizing And Multi-Position Guard
current_phase: Phase 28 - Dynamic Sizing And Multi-Position Guard
status: completed
stopped_at: Phase 28 verified locally; server deployment pending non-trading tests
last_updated: "2026-06-20T13:55:00.000+08:00"
last_activity: 2026-06-20
last_activity_desc: Dynamic sizing and multi-position guards implemented locally
progress:
  total_phases: 20
  completed_phases: 20
  total_plans: 20
  completed_plans: 20
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 28 - Dynamic Sizing And Multi-Position Guard
**Status:** v1.20 complete locally; server non-trading verification pending
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
- `ops reconcile-outcomes --persist-closed` is deployed and verified on the
  server. It skipped already reconciled ZECUSDT, checked BNBUSDT, reported
  `open_or_partial`, and inserted no new fills or outcomes while BNBUSDT
  remains open.
- `ops position-hold-check` is deployed and verified on the server. It reports
  BNBUSDT as protected by two algo orders but past the AI decision's 60-minute
  hold window, returning `status=review_required`.
- `ops time-exit-plan` is deployed and verified on the server. It reports
  `exit_plan_ready` for BNBUSDT with planned close `SELL MARKET 0.01`,
  `positionSide=LONG`, and `reduceOnly=false`. It does not place the order.
- `ops time-exit-execute` is implemented locally. It re-runs signed live
  evidence and time-exit planning, refuses to execute without the exact
  plan-derived confirmation token, refuses when the live service is active,
  submits the close order only after confirmation, and cancels symbol algo
  orders only after a post-close position check reports zero size. No live
  close has been approved or submitted.
- Dynamic sizing is implemented locally and defaults off. It can compute a
  per-trade notional cap from capital, available balance, leverage, margin
  caps, stop-distance risk, and exchange min-notional pressure. Multi-position
  remains disabled by default and, when enabled, rejects same-symbol
  same-direction duplicate exposure.

## Next Command

Deploy Phase 28 code to the server and verify only non-trading behavior. Do not
change live env risk caps while HYPEUSDT remains open. After HYPEUSDT closes,
run `ops reconcile-outcomes --persist-closed`, then rerun
`ops risk-change-check --target-leverage 8` before changing the live profile.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 28 - Dynamic Sizing And Multi-Position Guard
Plan: 28-01 complete locally
Status: dynamic sizing and multi-position guards are implemented; HYPEUSDT
remains open and continues to block live risk-profile changes until closed and
reconciled
Last activity: 2026-06-20 - Phase 28 local verification passed

## Operator Next Steps

- Observe the current BNBUSDT live position and its protective orders.
- Use `ops position-hold-check` to monitor whether the current active position
  remains past its AI hold window.
- Use `ops time-exit-plan` to inspect the read-only close-order plan.
- Use `ops time-exit-execute` without `--confirm-token` to fetch the current
  confirmation token only; do not provide the token unless explicitly approving
  a live close.
- Run `ops reconcile-outcomes --persist-closed` after BNBUSDT closes.
- Rerun `ops risk-change-check --target-leverage 8` before any leverage change.
- Do not raise leverage/risk caps while a live position is open unless
  explicitly reviewed.
- Run `ops resume-check` before any future manual timer resume.
- Rerun staged matrix backtests before any further risk-limit increase.
