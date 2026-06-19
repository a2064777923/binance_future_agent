---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 8 — Isolated Server Deployment
status: executing
stopped_at: Phase 7 verified and completed
last_updated: "2026-06-19T17:09:09.494Z"
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 24
  completed_plans: 24
  percent: 88
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** 8 — Isolated Server Deployment
**Status:** Ready to execute
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
  slippage, and liquidation wicks.

- Server already hosts other projects, so deployment scripts must be narrowly
  scoped and reviewed before running.

- Secrets were provided out-of-band and must be rotated or handled carefully
  before production deployment.

## Next Command

```bash
$gsd-execute-phase 8
```

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** Phase 8 planned and ready to execute
**Resume file:** .planning/phases/08-isolated-server-deployment/08-01-PLAN.md
