---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Live Activation
current_phase: Phase 9 - Live Activation Readiness
status: in_progress
stopped_at: live timer active; candidate-driven live cycle observed with no submission
last_updated: "2026-06-19T18:33:28.000Z"
last_activity: 2026-06-20
last_activity_desc: Market-heat fallback deployed; live candidate cycle observed
progress:
  total_phases: 9
  completed_phases: 9
  total_plans: 29
  completed_plans: 29
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 9 - Live Activation Readiness
**Status:** v1.1 live timer active; candidate-driven live cycle observed; OpenAI timeout backoff verified
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

## Next Command

Monitor live timer evidence before changing risk limits.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 9 - Live Activation Readiness
Plan: 09-01
Status: Timer active; candidate-driven live cycle passed with no submission
Last activity: 2026-06-20 — market-heat fallback deployed and live candidate cycle observed

## Operator Next Steps

- Keep 100 USDT pilot caps unchanged.
- Observe future timer cycles; if the endpoint is down, expect
  `openai_backoff` and no order intent.
- If a future entry is submitted, verify protective stop-loss and take-profit
  exchange orders before changing risk limits.
