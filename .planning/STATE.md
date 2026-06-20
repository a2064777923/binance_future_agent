---
gsd_state_version: 1.0
milestone: v1.21
milestone_name: Live Pilot Risk Controls
current_phase: Milestone v1.21 archived
status: completed
stopped_at: HYPEUSDT open/protected and within hold window; 8x/dynamic profile still blocked
last_updated: "2026-06-20T15:11:00+08:00"
last_activity: 2026-06-20
last_activity_desc: Live full-position early stop deployed and timer verified
progress:
  total_phases: 21
  completed_phases: 21
  total_plans: 21
  completed_plans: 21
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** Milestone v1.21 archived
**Status:** v1.21 milestone complete; awaiting next milestone while HYPEUSDT
continues to block any 8x/dynamic profile apply
**Last planned:** 2026-06-20
**Plan count:** 1

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.
**Current focus:** Observe HYPEUSDT under the unchanged 5x/12U/one-position
profile, reconcile after it closes, then re-check risk-change readiness before
any profile switch.

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

- A later timer cycle opened a BNBUSDT LONG under the 30U/5x profile; live-status
  shows the position has exchange-visible stop-loss and take-profit algo orders.

- The first closed live ZECUSDT trade is reconciled from Binance fills:
  gross PnL `0.12288` USDT, commission `0.0150272` USDT, net PnL
  `0.1078528` USDT, and `status=closed`.

- `ops risk-change-check --target-leverage 8` currently returns
  `keep_current_profile` because BNBUSDT is still open, protected by two algo
  orders, and its submitted intent event `138150` has no persisted outcome yet.

- `ops reconcile-outcomes --persist-closed` is deployed and verified on the
  server. It skipped already reconciled ZECUSDT, checked BNBUSDT, reported
  `open_or_partial`, and inserted no new fills or outcomes while BNBUSDT
  remains open.

- `ops position-hold-check` is deployed and verified on the server. It reports
  BNBUSDT as protected by two algo orders but past the AI decision's 60-minute
  hold window, returning `status=review_required`.

- `ops time-exit-plan` is deployed and verified on the server. It reports
  `exit_plan_ready` for BNBUSDT with planned close `SELL MARKET 0.01`,
  `positionSide=LONG`, and `reduceOnly=false`. It does not place the order.

- `ops time-exit-execute` is implemented and deployed. It re-runs signed live
  evidence and time-exit planning, refuses to execute without the exact
  plan-derived confirmation token, refuses when the live service is active,
  submits the close order only after confirmation, and cancels symbol algo
  orders only after a post-close position check reports zero size. No live
  close has been approved or submitted.

- Dynamic sizing is implemented locally and defaults off. It can compute a
  per-trade notional cap from capital, available balance, leverage, margin
  caps, stop-distance risk, and exchange min-notional pressure. Multi-position
  remains disabled by default and, when enabled, rejects same-symbol
  same-direction duplicate exposure.

- Confirmation-gated risk-profile switching is implemented and deployed. The
  `30u_8x_dynamic` profile can be previewed as a redacted env diff and later
  applied only when `risk-change-check` allows it and a matching confirmation
  token is supplied. No live env switch has been applied.

- Post-archive hotfix `8fa704e` is deployed on the server. It normalizes AI
  confidence values in percent form, for example `70.0` to `0.70`, with a
  `confidence_percent_normalized` warning while still rejecting values above
  `100`. Server focused tests, full suite (`266` tests), and secret-safe
  health-check passed after deployment. The live timer was paused during the
  code-only deploy, then restored; the next live cycle submitted no order.

- Latest read-only live check: HYPEUSDT remains open as `0.16` LONG under 5x,
  with two exchange-visible protective algo orders and no normal open orders.
  At the check it was about `70.8` minutes into a `120` minute AI hold window,
  so `ops position-hold-check` returned `within_hold_window` and
  `ops time-exit-plan` returned `exit_plan_blocked` with
  `hold_time_not_expired`. `ops reconcile-outcomes --symbol HYPEUSDT` fetched
  the entry fill only and reported `open_or_partial`; it inserted no fills or
  outcomes. `ops risk-change-check --target-leverage 8` still returned
  `keep_current_profile` because an active protected position and unreconciled
  submitted intent remain.

- Post-archive ops enhancement `d7f7277` is deployed on the server. It adds
  read-only `ops exposure-status`, which explains current sizing, long/short
  entry support, entry-capacity blockers, and the `30u_8x_dynamic` preview
  without modifying env or exchange state. Local tests passed (`269` tests);
  server focused tests passed (`3` tests), server full suite passed (`269`
  tests), and server secret-safe health-check passed after deployment. The live
  timer was paused during the code-only deploy and restored afterwards.

- Latest exposure-status check after restore: HYPEUSDT remains a `0.16` LONG,
  protected by two algo orders. The current profile is still 30U/5x with fixed
  `12` USDT max notional, dynamic sizing disabled, one max open position, and
  multi-position disabled. The command reports both long and short entries as
  supported by strategy/execution plumbing (`BUY`/`LONG` and `SELL`/`SHORT` in
  hedge mode), but a new hypothetical HYPEUSDT long is blocked by
  `multi_position_disabled`, `max_open_positions_reached`, and
  `duplicate_symbol_direction_exposure`. The 8x dynamic preview remains only a
  preview: target sizing would currently cap around `17.85` USDT notional from
  available balance and the 8% margin fraction, while `risk-change-check` still
  blocks the profile switch because the active protected HYPEUSDT position and
  unreconciled submitted intent remain.

- Post-restore live timer evidence: the next scheduled live cycle ran at
  `2026-06-20T06:59:42Z`, selected `ZECUSDT`, returned
  `execution_status=rejected`, `submitted=false`, and
  `risk_reasons=["ai_decision_pass"]`. The live service deactivated
  successfully afterwards and the timer remains active.

- Post-archive live-runner hotfix `40d4a95` is deployed on the server. It adds
  a live-only read-only entry-capacity preflight before market collection,
  candidate generation, or AI calls. When the active profile is already full,
  the automated runner returns `entry_capacity_blocked` instead of spending API
  cycles and then being rejected by the later execution risk gate. Local tests
  passed (`270` tests), server focused tests passed (`7` tests), server full
  suite passed (`270` tests), and server secret-safe health-check passed after
  deployment.

- Post-deploy live evidence: a manual live cycle at `2026-06-20T07:05:32Z`
  returned `status=entry_capacity_blocked`, `submitted=false`,
  `risk_reasons=["multi_position_disabled","max_open_positions_reached"]`,
  and zero market snapshots/candidates/narratives persisted. After the live
  timer was restored, the scheduled `2026-06-20T07:09:59Z` cycle returned the
  same early-stop status with `market_snapshot_count=0`, `candidate_count=0`,
  `narrative_record_count=0`, `ai_accepted=false`, and `submitted=false`; the
  service deactivated successfully and the timer remains active. A follow-up
  hold check still showed HYPEUSDT open/protected, about `104.47` minutes into
  the `120` minute hold window, so no time-exit action was taken.

## Next Command

Observe HYPEUSDT until it closes or reaches a reviewed time-exit condition. Do
not change live env risk caps while HYPEUSDT remains open. After HYPEUSDT closes, run
`ops reconcile-outcomes --persist-closed`, then rerun
`ops risk-change-check --target-leverage 8` before applying any profile switch.

## Session

**Last session:** 2026-06-20T01:05:00+08:00
**Stopped at:** HYPEUSDT open/protected and within hold window; risk-profile escalation blocked
**Resume file:** .planning/milestones/v1.21-MILESTONE-AUDIT.md

## Current Position

Phase: Milestone v1.21 complete
Plan: —
Status: Awaiting next milestone; current live profile remains 5x/12U/one-position
Last activity: 2026-06-20 — Live full-position early stop deployed and timer verified

## Operator Next Steps

- Observe the current HYPEUSDT live position and its protective orders.
- Use `ops position-hold-check` to monitor whether the active position remains
  inside or past its AI hold window.
- Use `ops time-exit-plan` to inspect the read-only close-order plan if review
  is needed.
- Use `ops time-exit-execute` without `--confirm-token` only to fetch the
  current confirmation token; do not provide the token unless explicitly
  approving a live close.
- Use `ops exposure-status --hypothetical-symbol HYPEUSDT --hypothetical-side
  long` to explain current sizing, direction support, and why new entries are
  blocked or allowed.
- Run `ops reconcile-outcomes --persist-closed` after HYPEUSDT closes.
- Rerun `ops risk-change-check --target-leverage 8` before any leverage or
  dynamic-sizing profile change.
- Apply `30u_8x_dynamic` only if risk-change readiness allows it and the
  operator supplies the exact confirmation token.
- Start the next milestone with `$gsd-new-milestone`.
