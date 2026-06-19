# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 1 - Isolated Project Foundation
**Status:** Ready to execute
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
$gsd-execute-phase 1
```
