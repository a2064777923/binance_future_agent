---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 4 — Event Store And Replay Foundation
status: executing
stopped_at: Phase 3 verified and completed
last_updated: "2026-06-19T16:00:14.963Z"
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 12
  completed_plans: 12
  percent: 38
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** 4 — Event Store And Replay Foundation
**Status:** Ready to execute
**Last planned:** 2026-06-19
**Plan count:** 0

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
$gsd-discuss-phase 4
```

## Session

**Last session:** 2026-06-19T15:56:54.417Z
**Stopped at:** Phase 3 verified and completed
**Resume file:** .planning/phases/03-narrative-and-hot-coin-collection-layer/03-VERIFICATION.md
