---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 2 — Binance Futures Market Data Layer
status: planning
stopped_at: Completed 01-04-PLAN.md
last_updated: "2026-06-19T10:29:09.865Z"
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 13
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** 2 — Binance Futures Market Data Layer
**Status:** Ready to plan
**Last planned:** 2026-06-19
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
$gsd-plan-phase 2
```

## Session

**Last session:** 2026-06-19T10:25:24.812Z
**Stopped at:** Completed Phase 01
**Resume file:** None
