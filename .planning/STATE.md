---
gsd_state_version: 1.0
milestone: v1.12
milestone_name: Timer Resume Gate
current_phase: Phase 20 - Timer Resume Gate
status: completed
stopped_at: Phase 20 verified; timer resumed and two cycles submitted no order
last_updated: "2026-06-20T11:39:00.000+08:00"
last_activity: 2026-06-20
last_activity_desc: Timer resumed after resume_allowed; two resumed cycles submitted no order
progress:
  total_phases: 12
  completed_phases: 12
  total_plans: 12
  completed_plans: 12
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 20 - Timer Resume Gate
**Status:** v1.12 complete; live timer active after `ops resume-check` returned
`resume_allowed`
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

## Next Command

Continue observing live timer cycles under the 30U profile. Before any future
manual timer resume, run `ops resume-check` and resume only if the gate returns
`resume_allowed`.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 20 - Timer Resume Gate
Plan: 20-01 complete
Status: `ops resume-check` deployed; timer active; two resumed cycles selected
ZECUSDT then HYPEUSDT, AI passed both, and no order was submitted
Last activity: 2026-06-20 - Phase 20 verified

## Operator Next Steps

- Observe the next live cycles and confirm no unexpected order submission.
- Run `ops resume-check` before any future manual timer resume.
- Rerun staged matrix backtests before any further risk-limit increase.
