---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Dry-Run Binance Futures Agent
current_phase: Phase 9 - Live Activation Readiness
status: in_progress
stopped_at: waiting for live OpenAI endpoint verification
last_updated: "2026-06-19T17:34:23.945Z"
last_activity: 2026-06-19
last_activity_desc: Milestone v1.0 completed and archived
progress:
  total_phases: 8
  completed_phases: 8
  total_plans: 28
  completed_plans: 28
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 9 - Live Activation Readiness
**Status:** v1.1 live activation in progress
**Last planned:** 2026-06-20
**Plan count:** 4

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

- OpenAI-compatible endpoint availability must be verified on the server. If it
  is down, the agent should enter `openai_backoff` and skip trading until the
  retry interval expires.

## Next Command

```bash
$gsd-plan-phase 9
```

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 9 - Live Activation Readiness
Plan: Pending
Status: Configure OpenAI-compatible endpoint, verify server health, then run one live cycle
Last activity: 2026-06-20 — v1.1 live activation requirements drafted

## Operator Next Steps

- Configure OpenAI-compatible endpoint/key out of band on the server.
- Verify `ops health-check --check-binance --check-openai`.
- Run one manual `binance-futures-agent-live.service` cycle before enabling the timer.
