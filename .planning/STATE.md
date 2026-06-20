---
gsd_state_version: 1.0
milestone: v1.10
milestone_name: DeepSeek Provider Switch
current_phase: Phase 18 - DeepSeek Provider Switch
status: completed
stopped_at: Phase 18 deployed; DeepSeek live cycles passed with no submission
last_updated: "2026-06-20T10:44:30.000+08:00"
last_activity: 2026-06-20
last_activity_desc: Phase 18 DeepSeek provider switch deployed and verified
progress:
  total_phases: 10
  completed_phases: 10
  total_plans: 10
  completed_plans: 10
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 18 - DeepSeek Provider Switch
**Status:** v1.10 complete and deployed; live timer active under pilot caps
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

- AI provider: DeepSeek is now selected for live use; OpenAI-compatible
  Responses API remains available as a fallback provider.
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

- The prior OpenAI-compatible endpoint was intermittent and returned invalid
  JSON; DeepSeek provider support now uses Chat Completions JSON mode and the
  same fail-closed decision validation.

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

- Cross margin mode is now explicit and validated via `BFA_MARGIN_MODE=cross`;
  it keeps the same notional/risk caps and protective-order requirement.

- Binance position-side mode expects explicit `positionSide`; execution must
  send hedge position sides when configured and fail closed on entry rejections.

- The current USD-M futures account has 0 available balance, so live execution
  must reject locally before margin setup or entry order placement until the
  account is funded.

## Next Command

Fund or transfer USDT into the Binance USD-M futures account before expecting a
real entry submission. With the current unfunded account, live order intents are
expected to reject or pass without submission; after the first submitted live
entry, verify protective stop-loss and take-profit evidence with
`ops live-status`.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 18 - DeepSeek Provider Switch
Plan: 18-01 complete locally
Status: DeepSeek provider support deployed; health checks passed; live timer active; latest cycles returned validated DeepSeek pass decisions and no submission
Last activity: 2026-06-20 — Phase 18 deployed and verified

## Operator Next Steps

- Keep 100 USDT pilot caps unchanged.
- Observe future cycles; if a trade submits, verify protective orders before any risk-limit change.
- Rerun staged matrix backtests before any risk-limit change.
- Observe future timer cycles; if the endpoint is down, expect
  `openai_backoff` and no order intent.

- If a future entry is submitted, verify protective stop-loss and take-profit
  exchange orders with `ops live-status` before changing risk limits.
- Fund or transfer USDT into the Binance USD-M futures account before expecting
  a real live entry submission.
