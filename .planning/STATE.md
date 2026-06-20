---
gsd_state_version: 1.0
milestone: v1.11
milestone_name: 30U Higher-Leverage Trial Profile
current_phase: Phase 19 - 30U Higher-Leverage Trial Profile
status: completed
stopped_at: Phase 19 verified; timer paused for open ZECUSDT position review
last_updated: "2026-06-20T11:13:00.000+08:00"
last_activity: 2026-06-20
last_activity_desc: 30U/5x server profile verified, live-status fixed, ZECUSDT protective orders confirmed
progress:
  total_phases: 11
  completed_phases: 11
  total_plans: 11
  completed_plans: 11
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 19 - 30U Higher-Leverage Trial Profile
**Status:** v1.11 complete; live timer paused while an open ZECUSDT position is reviewed
**Last planned:** 2026-06-20
**Plan count:** 5

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
- A real pre-switch ZECUSDT LONG position is open. It has stop-loss and
  take-profit algo orders, but automation is paused until the operator decides
  whether to resume scanning under the one-position cap.

## Next Command

Review the open ZECUSDT position. Re-enable
`binance-futures-agent-live.timer` only after the position closes, or after
explicit operator approval to resume cycles while `BFA_MAX_OPEN_POSITIONS=1`
blocks new entries.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 19 - 30U Higher-Leverage Trial Profile
Plan: 19-01 complete
Status: Server env on 30U/5x profile; live-status includes exchange positions
and algo orders; timer paused for open ZECUSDT review
Last activity: 2026-06-20 - Phase 19 verified

## Operator Next Steps

- Review or wait for the current ZECUSDT LONG to exit by stop-loss or
  take-profit.
- Keep timer paused until that review is complete, unless explicitly choosing to
  resume scanning while the one-position cap blocks fresh entries.
- Rerun staged matrix backtests before any further risk-limit increase.
- If resuming automation, observe the next live cycle and verify it reports the
  existing position instead of opening a second one.
