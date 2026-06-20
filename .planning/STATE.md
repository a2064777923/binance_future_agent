---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: Margin Setup Fail-Closed
current_phase: Phase 14 - Margin Setup Fail-Closed
status: completed
stopped_at: Phase 14 complete; timer stopped pending fail-closed deployment
last_updated: "2026-06-20T01:35:00.000Z"
last_activity: 2026-06-20
last_activity_desc: Phase 14 complete
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 6
  completed_plans: 6
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 14 - Margin Setup Fail-Closed
**Status:** v1.6 complete; live timer paused until deployment verification
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

- AI provider: OpenAI.
- Exchange: Binance USD-M futures.
- Pilot capital: 100 USDT.
- First strategy: hot coins from Binance Square and fallback narrative sources.
- Backtest discipline: use short-window staged sweeps with completed candles,
  next-candle entries, fees/slippage, and 100 USDT pilot caps before any scale-up.

- Project mode: horizontal layers.
- Workflow config: Standard granularity, parallel execution enabled, planning
  docs committed, research/check/verifier enabled.

## Open Risks

- Binance Square read access may require browser/export/manual collection or
  other adapters because stable official public read APIs are not guaranteed.

- Live futures trading with 100 USDT is highly sensitive to fees, spread,
  slippage, liquidation wicks, and API outages.

- Server already hosts other projects, so deployment scripts must be narrowly
  scoped and reviewed before running.

- Secrets were provided out-of-band and must be rotated or handled carefully
  before production deployment.

- OpenAI-compatible endpoint is configured on the server and is intermittent
  under the 5 second timeout. Candidate-driven cycles either receive an AI
  pass/no-trade decision or enter `openai_backoff` and skip trading.

- Historical Square/social narrative data is not yet complete, so the first
  backtest layer validates a market-heat proxy rather than claiming to reproduce
  a private Lana-style social alpha system.

- Current Binance filters can make BTCUSDT/ETHUSDT incompatible with a 20 USDT
  max-position-notional cap, so pilot tradability filtering must remain active
  until risk caps are explicitly changed.

- The pilot symbol universe is capped at 10 Binance USD-M symbols that currently
  fit the 20 USDT max-position-notional cap.

- Binance Multi-Assets mode rejects isolated-margin setup on the live account;
  execution must reject before entry submission when margin setup fails.

## Next Command

Deploy Phase 14, rerun health checks, resume the live timer, and observe that
margin setup failures become rejected evidence instead of service crashes.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 14 - Margin Setup Fail-Closed
Plan: 14-01 complete
Status: Margin setup errors are handled as rejected non-submitted execution results
Last activity: 2026-06-20 — Phase 14 complete

## Operator Next Steps

- Keep 100 USDT pilot caps unchanged.
- Confirm live cycles reject margin setup failures without entry submission or service crash.
- Rerun staged matrix backtests before any risk-limit change.
- Observe future timer cycles; if the endpoint is down, expect
  `openai_backoff` and no order intent.

- If a future entry is submitted, verify protective stop-loss and take-profit
  exchange orders with `ops live-status` before changing risk limits.
