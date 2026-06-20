---
gsd_state_version: 1.0
milestone: v1.24
milestone_name: Server Readiness And Paper Promotion
current_phase: v1.24 — Server Readiness And Paper Promotion
current_phase_name: Milestone Archive
status: milestone_audit_passed_pending_archive
stopped_at: v1.24 milestone audit passed; archive pending.
last_updated: "2026-06-21T02:31:51+08:00"
last_activity: 2026-06-21
last_activity_desc: v1.24 milestone audit passed, archive pending
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 3
  completed_plans: 3
  percent: 100
---

# Project State: Binance Futures Agent

**Initialized:** 2026-06-19
**Current phase:** v1.24 — Server Readiness And Paper Promotion
**Status:** Milestone audit passed pending archive
**Last planned:** 2026-06-21
**Plan count:** 3

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-21)

**Core value:** Turn hot-coin narrative momentum into auditable, risk-capped
Binance futures signals and small live trades without contaminating existing
projects or losing control of downside.
**Current focus:** Archive v1.24 after the milestone audit passed. Live
automation remains paused because the current packet returns
`resolve_exposure`, not live eligibility.

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

- v1.22 direction: do not let one open HYPEUSDT position freeze the whole agent
  after an operator-approved multi-position profile is enabled. Continue hot
  coin scanning when capacity remains, evaluate the top-N hot-symbol queue
  instead of one all-or-nothing candidate, and reject new entries against
  portfolio-level margin, margin-fraction, notional, and same-direction caps.

- v1.23 direction: completed and archived. The system now has read-only
  strategy evidence, recalibration, matrix, post-change paper, and live-resume
  readiness gates. These gates do not authorize live resume by themselves.

- v1.24 direction: move the readiness workflow onto the isolated server, collect
  guarded post-change paper evidence, and produce an operator-facing resume
  decision packet before any separate live resume confirmation flow.

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

- Operator-opened ETH/ETHUSDT exposure is manual exposure. Readiness checks
  should mark it with `--manual-exposure-symbols ETHUSDT` and must not treat it
  as agent-managed strategy evidence.

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

- Latest HYPEUSDT hold/time-exit gate: at `2026-06-20T07:28:36Z` the position
  was still open and protected, but had reached about `122.48` minutes against
  the `120` minute AI hold window. `ops position-hold-check` returned
  `review_required` with `hold_time_expired`. `ops time-exit-plan` returned
  `exit_plan_ready` with a read-only close plan: `SELL MARKET 0.16`,
  `positionSide=LONG`, and `reduceOnly=false` in hedge mode. Reconcile preview
  still reports `open_or_partial`, and `risk-change-check --target-leverage 8`
  remains blocked by the active protected position plus missing closed outcome.

- `ops time-exit-execute` was run without a confirmation token only as a
  no-trade preview. It returned `confirmation_required`, `exit_executed=false`,
  and no execution payload. No live close has been approved or submitted.

- Latest read-only follow-up at `2026-06-20T07:39:05Z`: HYPEUSDT remained open
  as `0.16` LONG under the unchanged 30U/5x profile, with two protective algo
  orders, no normal open orders, and about `132.97` minutes elapsed against the
  `120` minute AI hold window. `ops position-hold-check` still returned
  `review_required` with `hold_time_expired`; `ops time-exit-plan` still
  returned `exit_plan_ready` with planned close `SELL MARKET 0.16`,
  `positionSide=LONG`, and `reduceOnly=false`. Reconcile preview still reported
  `open_or_partial` with only the entry fill, and
  `ops risk-change-check --target-leverage 8` still returned
  `keep_current_profile` because the active protected position and unreconciled
  submitted intent remain. The live service was inactive and the live timer was
  active; no close, env switch, or exchange mutation was performed.

- Phase 30 local implementation adds portfolio-level risk caps, active exposure
  notional/margin accounting, top-N candidate queue evaluation, a
  `30u_10x_multi_dynamic` preview profile, target-profile active-exposure
  readiness, and exposure-status portfolio context. It preserves
  confirmation-gated profile application and does not change the live server
  env. Full local test suite passed with `278` tests after the candidate queue
  and target-readiness additions.

- Phase 30 server deployment is complete under `/opt/binance-futures-agent/app`.
  The live timer was paused during deploy, the package was reinstalled editable
  in `/opt/binance-futures-agent/.venv`, focused server tests passed with `88`
  tests, the full server suite passed with `278` tests, and a secret-safe
  health check passed. The live timer was restored afterwards.

- Server read-only preview for `30u_10x_multi_dynamic` reports
  `ready_for_profile_switch`: current HYPEUSDT exposure is `0.16` LONG, active
  notional about `11.38` USDT, active initial margin about `2.28` USDT, two
  exchange-visible algo protection orders, no normal open orders, no AI
  backoff, and one unreconciled submitted intent that matches the active
  HYPEUSDT position. The target profile is 30U/10x, two positions, per-position
  notional cap 25 USDT, portfolio margin cap 5 USDT, portfolio notional cap 45
  USDT, same-direction notional cap 30 USDT, and dynamic sizing enabled.

- No live profile apply was run. The server env remains 30U/5x/12U/one-position,
  dynamic sizing disabled, multi-position disabled. After timer restore, the
  next live cycle exited successfully with `entry_capacity_blocked`,
  `submitted=false`, zero market/candidate/narrative records, and
  `risk_reasons=["multi_position_disabled","max_open_positions_reached"]`.

- Phase 31 local implementation adds read-only `ops position-review`. It reuses
  active exchange positions and matching submitted trade intents to report PnL
  percent, stop-risk R multiple, target progress, hold-time progress,
  protection count, and a deterministic recommendation: `hold`, `watch`,
  `trail_or_reduce`, or `close_review`. It does not place, cancel, or modify
  exchange orders.

- Server root SSH key access has been added for this workstation using
  `C:\Users\KingHong\.ssh\id_ed25519_bfa.pub`; password login was not disabled
  or modified. The previously stopped live timer was restored. Latest check:
  live service inactive, live timer active, next run scheduled, and the last
  live cycle exited with `entry_capacity_blocked` and no submission.

- Phase 32 local implementation adds `ops position-adjustment-plan` and
  `ops position-adjustment-execute`. It maps `trail_or_reduce` to partial
  take-profit reduce orders, maps `close_review` to full-close reduce orders,
  and requires live mode, inactive live service, and an exact confirmation token
  before submitting any live adjustment order. The live runner now includes
  position-review and adjustment-plan summaries in every live cycle result.

- Phase 32 server deployment is complete under
  `/opt/binance-futures-agent/app`. The live timer was paused during deploy,
  the package was reinstalled editable in `/opt/binance-futures-agent/.venv`,
  server focused tests passed with 72 tests, full server suite passed with 289
  tests, and the secret-safe health check passed with Binance public and
  DeepSeek API checks enabled. The live timer was restored after verification.

- Server read-only `ops position-adjustment-plan` preview currently reports
  `adjustment_plan_empty`: a new `SOLUSDT` LONG `0.16` position is open,
  protected by two algo orders, within its 15-minute hold window, and reviewed
  as `hold` with small unrealized profit. No adjustment execution was run.

- Post-deploy live cycle evidence: the scheduled run emitted
  `position_review.status=review_ok`,
  `position_review.positions[0].symbol=SOLUSDT`,
  `recommendation=hold`, `position_adjustment_plan.status=adjustment_plan_empty`,
  then exited `entry_capacity_blocked` with
  `risk_reasons=["multi_position_disabled","max_open_positions_reached"]` and
  `submitted=false`.

- Post-deploy reconciliation sweep persisted the closed HYPEUSDT outcome for
  submitted intent `182563`: entry fill at `70.266`, exit fill at `70.56`,
  gross realized PnL `0.04704` USDT, commission `0.01126608` USDT, net realized
  PnL `0.03577392` USDT, two fills inserted, and one closed outcome inserted.

- After HYPEUSDT reconciliation, server `ops exposure-status --target-profile
  30u_10x_multi_dynamic --allow-two-positions` reports
  `ready_for_profile_switch`. The active `SOLUSDT` LONG is protected, fits the
  target portfolio caps, and can be carried forward. The profile confirmation
  token is redacted from planning docs. No profile apply was run.

- Phase 33 local implementation makes active-position adjustment plans
  exchange-filter aware. Partial take-profit quantities can be rounded down to
  Binance step size and blocked when min quantity or min notional would fail;
  read-only actionable previews fail closed when symbol filters are missing;
  confirmed adjustment execution requires symbol filters before submitting a
  live reduce order. Focused local suites passed with 52 tests and the full
  local suite passed with 293 tests.

- Phase 33 server deployment is complete under
  `/opt/binance-futures-agent/app`. The live timer was paused during deploy,
  the package was reinstalled editable in `/opt/binance-futures-agent/.venv`,
  server focused tests passed with 52 tests, server full suite passed with 293
  tests, and the secret-safe health check passed with Binance public and
  DeepSeek API checks enabled.

- Server read-only `ops position-adjustment-plan` after Phase 33 deployment
  reported
  `adjustment_plan_ready` for the protected active `SOLUSDT` LONG `0.16`.
  The filter-aware close plan is `SELL MARKET 0.16`, `positionSide=LONG`,
  with `quantity_filter_checked`. The position was about 28.88 minutes into a
  15-minute hold window, review recommendation `close_review`, urgency `high`,
  and unrealized PnL about `0.06971011` USDT at the preview. No adjustment
  execution was run.

- Follow-up read-only SOLUSDT preview at `2026-06-20T11:55:29Z` still reports
  `adjustment_plan_ready`: active `SOLUSDT` LONG `0.16`, protected by two algo
  orders, no normal open orders, about 34.37 minutes into a 15-minute hold
  window, unrealized PnL about `0.0576` USDT, and the same filter-aware full
  close plan `SELL MARKET 0.16`, `positionSide=LONG`. The live timer is paused
  while the operator reviews the open position and profile sizing.

- Server `ops exposure-status --target-profile 30u_10x_multi_dynamic
  --allow-two-positions` still reports `ready_for_profile_switch` with a
  redacted confirmation token. No profile apply was run and the live env
  remains 30U/5x/12U/one-position.

- Phase 34 local implementation adds deterministic multi-factor trade setup
  generation before AI evaluation. Setup scoring separates momentum,
  liquidity, open interest, taker flow, funding, volatility, narrative quality,
  and pilot tradability; it outputs side, entry, stop, target, notional, hold
  time, confidence, reasons, and warnings. AI is now overlay/veto only: an
  accepted trade response must echo the deterministic setup side, prices,
  notional, and hold time exactly or validation rejects it.

- Phase 34 also adds read-only `ops trade-trace`, which reconstructs candidate,
  setup or legacy AI, risk/order intent, and exchange response evidence from
  the event store. It is backward-compatible with the existing live database
  that predates the `trade_setups` table.

- Phase 34 server deployment is complete under `/opt/binance-futures-agent/app`.
  Source and tests were synchronized without changing live env settings,
  without executing any live order, and without restoring the live timer.
  Server full suite passed with `299` tests; focused server trade-trace CLI
  test passed; live service and timer remained `inactive`.

- Server read-only `ops trade-trace --symbol SOLUSDT` returned `trace_ready`
  for the existing SOLUSDT live order. Because that order was submitted before
  Phase 34, it has no persisted `trade_setup`; the trace reconstructs the old
  path as candidate ranking, DeepSeek AI-generated point selection, risk/order
  intent, and exchange response. This confirms the operator concern that the
  old SOLUSDT order path was thinner than a mature deterministic quant setup.

- Phase 35 local implementation adds `quant_setup` as a built-in backtest
  variant. The backtest engine now can build deterministic setup candidates
  from completed kline windows, call the same `build_trade_setup` logic used by
  the live runner, and simulate long or short futures trades with setup-derived
  stop, target, notional, hold time, fees, slippage, and time exit. Legacy
  `strict`, `balanced`, and `aggressive` variants remain unchanged.

- Phase 35 verification is local/offline only so far. Focused backtest tests
  passed, full local suite passed with `303` tests, `git diff --check` passed,
  and manual CLI smoke showed `backtest run --variant quant_setup` and
  `backtest sweep --variants quant_setup` both produce reports. No live env,
  server service state, exchange order, or risk profile was changed.

- Phase 36 local implementation adds shared dependency-free indicator
  snapshots for kline-derived ATR, VWAP, EMA spread, RSI, support/resistance,
  momentum, and volume impulse. Live feature extraction and `quant_setup`
  backtests now use the same indicator helper where kline data is available.
  Deterministic setup scoring now includes trend structure, RSI regime, and
  volume impulse factors, and setup output includes a trace-visible
  `price_basis` explaining entry reference, stop anchor, target anchor, and
  risk/reward geometry. AI remains overlay/veto only and cannot rewrite setup
  prices.

- Phase 36 recent hot-symbol matrix evidence was negative. The report at
  `runtime/quant_setup_matrix_phase36.json` checked 8 hot Binance USD-M symbols
  (`REUSDT`, `SOLUSDT`, `HYPEUSDT`, `ZECUSDT`, `BICOUSDT`, `BTWUSDT`,
  `LABUSDT`, `BSBUSDT`) across `5m` and `15m`. `quant_setup` produced
  total net PnL `-5.10446676` USDT, worst drawdown `4.44266063` USDT, and
  promotion verdict `drawdown_exceeds_pilot_cap`.

- Phase 37 local implementation adds read-only
  `ops strategy-promotion-check --matrix-report ...`. It validates a matrix
  report and blocks promotion when the selected variant has non-positive total
  PnL, drawdown at/above the cap, non-promoted interval cells, insufficient
  trade count, low positive-window rate, or invalid/missing report evidence.
  Running it on `runtime/quant_setup_matrix_phase36.json` returned
  `status=keep_live_paused`, `promotion_allowed=false`, with both `5m` and
  `15m` cells failing PnL, positive-window-rate, and drawdown checks.

- Phase 38 local implementation adds explicit setup profiles for offline
  calibration while preserving the standard live default. Backtests now expose
  `quant_setup_selective` and `quant_setup_scalp` variants. Profiles can gate
  trades by edge, confidence, risk/reward, indicator sample size, trend
  alignment, RSI extremes, stop distance, and notional fraction.

- Phase 38 matrix evidence at `runtime/quant_setup_matrix_phase38.json`
  compared `quant_setup`, `quant_setup_selective`, and `quant_setup_scalp`
  across recent hot symbols on `5m` and `15m`. Baseline `quant_setup` worsened
  to total net PnL `-7.50008697` USDT. `quant_setup_selective` improved to
  total net PnL `0.2231175` USDT and passed the `5m` cell
  (`+1.62468567` USDT, positive-window-rate `1.0`, worst drawdown
  `1.27227818` USDT), but failed `15m` (`-1.40156817` USDT, worst drawdown
  `2.39698293` USDT). `quant_setup_scalp` passed `5m` but total PnL remained
  negative (`-0.69422935` USDT). Promotion checks for all three variants still
  returned `keep_live_paused`.

- Phase 39 local implementation adds interval-aware promotion scope to
  `ops strategy-promotion-check`. Default `all-intervals` behavior remains
  strict and continues to require the whole selected variant to pass. Explicit
  `--scope selected-intervals --intervals 5m` checks only the selected cell and
  can return `status=forward_paper_allowed`, but always reports
  `live_resume_allowed=false`.

- Running Phase 39 against `runtime/quant_setup_matrix_phase38.json` marks
  `quant_setup_selective` on `5m` as forward-paper allowed:
  `+1.62468567` USDT, `51` trades, positive-window-rate `1.0`, worst drawdown
  `1.27227818` USDT under a `1.5` USDT cap. The default all-interval check on
  the same variant still returns `keep_live_paused` because `15m` remains
  negative and over drawdown cap.

- Phase 40 local implementation adds read-only `ops forward-paper-run`. It
  fetches public klines, records calibrated quant setup `paper_signals`, settles
  existing open paper signals into `paper_outcomes` using later bars, and uses
  stop, target, time-exit, fees, and slippage. It writes no `order_intents`,
  does not use signed Binance endpoints, and does not modify live env, timer,
  positions, or risk profile.

- Phase 40 server deployment is complete under `/opt/binance-futures-agent/app`.
  The package was reinstalled editable in `/opt/binance-futures-agent/.venv`.
  Server focused tests passed with `10` tests, server full suite passed with
  `319` tests, and secret-safe health check passed with network checks skipped.
  The live service and live timer remained `inactive`.

- Server `ops forward-paper-run --symbols HYPEUSDT,SOLUSDT,ZECUSDT,WLDUSDT,
  XRPUSDT,AVAXUSDT,BNBUSDT,DOGEUSDT,NEARUSDT,ADAUSDT --interval 5m --variant
  quant_setup_selective --limit 36` completed with `generated_signals=0`,
  `skipped_signals=10`, and no paper outcomes. DB counts after the run were
  `paper_signals=0`, `paper_outcomes=0`, and existing `order_intents=18`,
  confirming no live/dry-run order intent was created.

- Phase 41 local implementation adds a paper-only systemd service and timer.
  The service runs `ops forward-paper-run` over the configured hot-symbol
  universe on `5m` with `quant_setup_selective`; it does not run
  `agent run-once`. The bootstrap installs the paper unit/timer but does not
  enable or start them. Full local suite passed with `319` tests.

- Phase 41 server deployment is complete under `/opt/binance-futures-agent/app`.
  Server deploy asset tests passed with `6` tests, server full suite passed
  with `319` tests, and secret-safe health-check passed with network checks
  skipped. `binance-futures-agent-paper.timer` is enabled and active; the first
  systemd-triggered paper run returned `paper_run_complete` with
  `generated_signals=0`, `skipped_signals=10`, `paper_signals=0`, and
  `paper_outcomes=0`. `binance-futures-agent-live.service` and
  `binance-futures-agent-live.timer` remain `inactive`.

- Follow-up Phase 41 fix separates paper observation universe from the live
  pilot allowlist. Live `BFA_MARKET_SYMBOLS` remains the controlled 10-symbol
  trading universe, while `ops forward-paper-run` can auto-select up to 40 hot
  USDT USD-M symbols from Binance 24h ticker data using quote-volume and
  absolute price-change filters before falling back to
  `BFA_FORWARD_PAPER_SYMBOLS` or `BFA_MARKET_SYMBOLS`.

- The follow-up Phase 41 fix is deployed. Server focused tests passed with
  `30` tests, server full suite passed with `322` tests, and health-check
  passed with network checks skipped. The deployed paper service ExecStart uses
  `--auto-hot-symbols --top-n 40`; the paper timer is active and the live
  service/timer remain inactive. A manual server paper run selected `40`
  symbols, generated `15` paper signals, skipped `25`, and created no
  `order_intents`; DB counts after timer/manual paper runs were
  `paper_signals=23`, `paper_outcomes=0`, `order_intents=18`.

- Phase 42 implementation is deployed. Read-only
  `ops forward-paper-performance-check` summarizes stored `paper_signals` and
  `paper_outcomes` by selected variant/interval, checks minimum outcome count,
  win rate, total net PnL, and worst drawdown, and keeps
  `live_resume_allowed=false` even when paper thresholds pass.

- Latest server Phase 42 gate evidence after deployment: focused tests passed
  with `5` tests, full suite passed with `327` tests, health-check passed with
  network checks skipped, paper timer is active, and live service/timer remain
  inactive. `ops forward-paper-performance-check --min-outcomes 20` returned
  `keep_live_paused` with `signal_count=57`, `outcome_count=35`,
  `open_signal_count=22`, `win_rate=0.34285714`,
  `total_net_pnl_usdt=-1.46500894`, `profit_factor=0.53973765`, and
  `worst_drawdown_usdt=1.60719683`. Reasons were
  `paper_total_net_pnl_not_above_min`, `paper_win_rate_below_min`, and
  `paper_worst_drawdown_exceeds_cap`. Python sqlite count check showed
  `paper_signals=57`, `paper_outcomes=35`, and `order_intents=18`.

- Phase 43 is deployed. Read-only `ops forward-paper-loss-attribution` joins
  settled paper outcomes to their originating signal setup payloads and ranks
  losing conditions by symbol, side, exit reason, setup reasons/warnings, and
  factor evidence before any filter or live-resume change.

- Latest server Phase 43 attribution evidence: focused tests passed with `3`
  tests, full suite passed with `330` tests, health-check passed with network
  checks skipped, paper timer is active, and live service/timer remain
  inactive. `ops forward-paper-loss-attribution --min-group-outcomes 1
  --worst-limit 5` returned `loss_attribution_ready` with `signal_count=74`,
  `outcome_count=49`, `matched_outcome_count=49`,
  `total_net_pnl_usdt=-0.93131071`, and `win_rate=0.36734694`. Worst groups:
  `BICOUSDT` (`3` outcomes, `-0.89590149` USDT, `0.0` win rate), `BEATUSDT`
  (`2`, `-0.47163963`), `SLXUSDT` (`2`, `-0.46805458`), short side (`34`,
  `-1.1316274`, win rate `0.32352941`), and stop-loss exits (`11`,
  `-2.99528982`, win rate `0.0`). Worst setup/factor associations include
  `rsi_bearish_momentum`, `taker_flow_acceleration`, `quant_short_setup`,
  `volume_neutral`, `ema_trend_down`, and `close_near_range_low`.

- Phase 44 is deployed. It added a paper/backtest-only
  `quant_setup_selective_guarded` variant with explicit side disabling and
  worst-symbol exclusion from Phase 43 attribution, without changing the
  default/live setup profile or restoring live automation. Server guarded
  matrix evidence reduced drawdown but kept total PnL negative, so the paper
  timer remains on the original `quant_setup_selective` variant.

- Phase 47 local implementation adds an adaptive forward-paper guard. It reads
  local `paper_signals` and `paper_outcomes`, returns `insufficient_evidence`
  when settled outcomes are below threshold, and otherwise can block losing
  symbols, sides, and factor reasons when group outcome count, net loss, and
  win-rate thresholds are all met. `agent run-once` now rejects guarded symbols
  before AI/execution and passes guard side/factor blocks into deterministic
  setup profiles. `ops forward-paper-run` now skips guarded symbols before new
  paper signal creation and reports guard status plus guarded symbols. Local
  focused tests passed and the full local suite passed with `339` tests. No
  live env, timer, risk profile, or exchange mutation was performed.

- Phase 47 server deployment is complete under
  `/opt/binance-futures-agent/app` from commit `e7edd86`. The paper timer was
  paused during deployment and restored afterwards. Server focused tests passed
  with `45` tests, the full server suite passed with `339` tests, and
  health-check passed with network checks skipped. A paper-only server
  `ops forward-paper-run --auto-hot-symbols --top-n 40 --interval 5m --variant
  quant_setup_selective --limit 36` reported `paper_guard.status=active`,
  `signal_count=201`, `outcome_count=170`, `win_rate=0.32352941`,
  `total_net_pnl_usdt=-5.78143363`, guarded symbols `BEATUSDT`, `BICOUSDT`,
  `BTWUSDT`, `GUAUSDT`, and `SLXUSDT`, short-side blocking, and factor blocks
  for `ema_trend_down` and `rsi_bearish_momentum`. After verification,
  `binance-futures-agent-paper.timer` was active and both
  `binance-futures-agent-live.timer` and
  `binance-futures-agent-live.service` were inactive.

## Next Command

Run `$gsd-complete-milestone v1.24` to archive v1.24. Keep live automation
disabled. Do not enable unattended live auto-hot, restore live automation,
execute adjustment orders, or apply `30u_10x_multi_dynamic` while the operator
packet remains `resolve_exposure`.

## Session

**Last session:** 2026-06-21T00:00:00+08:00
**Stopped at:** v1.24 requirements and roadmap initialized.
**Resume file:** .planning/REQUIREMENTS.md

## Current Position

Phase: v1.24 — Server Readiness And Paper Promotion
Plan: 3/3 complete
Status: Milestone audit passed pending archive
Last activity: 2026-06-21 — v1.24 milestone audit passed, archive pending

## Operator Next Steps

- Run `$gsd-complete-milestone v1.24`.
