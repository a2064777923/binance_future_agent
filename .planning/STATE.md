---
gsd_state_version: 1.0
milestone: v1.10
milestone_name: DeepSeek Provider Switch
current_phase: Phase 18 - DeepSeek Provider Switch
status: in_progress
stopped_at: Phase 18 local implementation complete; deployment verification pending
last_updated: "2026-06-20T10:45:00.000+08:00"
last_activity: 2026-06-20
last_activity_desc: Phase 18 DeepSeek provider switch implemented locally
progress:
  total_phases: 10
  completed_phases: 9
  total_plans: 10
  completed_plans: 10
  percent: 90
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Phase 18 - DeepSeek Provider Switch
**Status:** v1.10 implementation complete locally; deployment verification pending
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

Deploy Phase 18 to the server, update `/etc/binance-futures-agent/env` to
`BFA_AI_PROVIDER=deepseek` with the DeepSeek key, then run server health checks
and one timer cycle. Funding the USD-M futures account is still required before
expecting a real entry submission.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** v1.0 dry-run server deployment verified
**Resume file:** .planning/phases/08-isolated-server-deployment/08-VERIFICATION.md

## Current Position

Phase: Phase 18 - DeepSeek Provider Switch
Plan: 18-01 complete locally
Status: DeepSeek provider support implemented locally; server deployment pending
Last activity: 2026-06-20 — Phase 18 implementation complete locally

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
