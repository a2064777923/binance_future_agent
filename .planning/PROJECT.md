# Binance Futures Agent

## What This Is

Binance Futures Agent is an isolated crypto futures trading system for Binance
USD-M contracts. It watches hot coins from Binance Square and other narrative
sources, confirms them with futures-market anomalies, asks a configured AI
provider for structured trade decisions, and can run a tightly capped small-USDT
live pilot on a dedicated server.

This project is separate from the existing HK/US stock repository. It may borrow
ideas such as config-driven runtime, JSONL event records, replay, and explicit
execution modes, but it must not import, mutate, or deploy the stock codebase.

## Core Value

Turn hot-coin narrative momentum into auditable, risk-capped Binance futures
signals and small live trades without contaminating existing projects or losing
control of downside.

## Business Context

- **Customer**: The user running a personal trading experiment.
- **Revenue model**: Personal trading performance, not a SaaS product.
- **Success metric**: Positive risk-adjusted pilot results with bounded maximum
  drawdown, measured from recorded decisions and fills.
- **Strategy notes**: Inspired by the Lana / "棍哥" public claims around
  Binance Square hot coins, AI-agent iteration, and small-capital futures
  compounding, but implemented as a testable system rather than copied as lore.

## Requirements

### Validated

- Phase 1 validated the isolated repository at `F:\binance_futures_agent`.
- Phase 1 validated git hygiene for env files, credentials, runtime data, logs,
  local databases, and raw exports.
- Phase 1 validated the dry-run/testnet/live config contract, secret redaction,
  and `python -m bfa.cli config-check` diagnostics.
- Phase 1 documented future server isolation under `/opt/binance-futures-agent`,
  `/etc/binance-futures-agent/env`, and `binance-futures-agent.service`.
- Phase 2 validated official Binance USD-M futures public market metadata,
  REST metrics, WebSocket message parsing, normalized market snapshots, JSONL
  output, selected-symbol collection, and market-data CLI smoke commands.
- Phase 3 validated manual/export Binance Square-style narrative ingestion,
  RSS/Atom fallback ingestion, normalized narrative records, conservative symbol
  extraction, deterministic deduplication, JSONL output, and narrative CLI
  smoke commands.
- Phase 4 validated the SQLite event-store schema, append-only replay events,
  typed narrative and market snapshot persistence, generic future artifact
  persistence, deterministic replay packets, review metrics, and event-store
  CLI smoke commands.
- Phase 5 validated deterministic hot-coin candidate generation from replay
  packets, narrative/market feature extraction, conservative rejection gates,
  reason codes, data-quality notes, candidate persistence, and CLI smoke
  commands.
- Phase 6 validated compact AI decision context packets, strict structured
  JSON decision parsing, deterministic local risk validation, redacted
  request/response journaling, `ai_decisions` persistence, and AI CLI smoke
  commands with fake transports.
- Phase 7 validated dry-run order intents, Binance symbol-filter quantization,
  deterministic risk gates, signed Binance USD-M Futures order helpers,
  explicit live execution gating, event-store execution artifacts, CLI
  execution smoke commands, and read-only exchange reconciliation.
- Phase 9 validated live timer activation under 100 USDT pilot caps, market-heat
  fallback candidates, OpenAI timeout/backoff, and secret-safe live-status
  evidence.
- Phase 10 validated a local short-window backtest harness and hot matrix
  reporting before any live risk-limit increase.
- Phase 11 validated reference-price AI context, complete trade-geometry
  prompting, and deterministic rejection of entry prices too far from market.
- Phase 12 validated pilot tradability filtering: Binance execution filters are
  converted into `min_executable_notional`, cap-incompatible hot symbols are
  rejected before AI calls, and AI notional below executable minimum fails
  closed.
- Phase 13 validated a controlled 10-symbol pilot universe whose current Binance
  minimum executable notionals fit the 20 USDT max-position-notional cap.
- Phase 14 validated fail-closed handling for Binance margin setup errors, after
  live evidence showed Multi-Assets mode rejects isolated-margin changes.
- Phase 15 added explicit configurable margin mode so the server can use cross
  margin with the current Multi-Assets account while preserving pilot caps.
- Phase 16 added explicit position mode and entry-order fail-closed handling
  after live evidence showed the account expects Binance `positionSide`.
- Phase 17 added a live account-balance preflight so an unfunded USD-M futures
  account rejects locally before margin setup or entry order placement.
- Phase 18 adds DeepSeek provider support using Chat Completions JSON mode after
  the previous OpenAI-compatible endpoint produced invalid JSON/timeouts.
- Phase 19 switches the active trial profile from 100 USDT/3x to a tighter 30
  USDT/5x trial with lower absolute notional, trade-risk, daily-loss, and
  concurrency caps.
- Phase 20 adds a read-only timer resume gate so automation resumes only after
  exchange positions, normal orders, algo orders, and AI backoff are clear.
- Phase 21 adds closed-trade outcome reconciliation from Binance fills and
  persists net-of-commission fill/outcome evidence idempotently.
- Phase 22 adds a read-only readiness gate before any leverage or risk-cap
  profile change.
- Phase 23 tightens that readiness gate so only final closed outcomes satisfy
  submitted-trade reconciliation.
- Phase 24 adds a sweep command that scans submitted live intents, skips
  already closed outcomes, and persists only final closed results.
- Phase 25 adds a read-only active-position hold-time check.
- Phase 26 adds a read-only time-exit order plan for overdue protected
  positions.
- Phase 27 adds confirmation-gated operator time-exit execution with
  post-close algo-order cleanup.
- Phase 28 adds dynamic position sizing and bounded multi-position guards while
  keeping both disabled by default for live.
- Phase 29 adds a confirmation-gated risk-profile switch mechanism for future
  8x/dynamic profile changes.
- Phase 30 adds portfolio-level caps, candidate-queue evaluation, and a
  confirmation-gated 30U/10x/two-position profile path that can carry a
  protected active position only when the target caps can absorb it.
- Phase 48 adds a compact read-only strategy evidence baseline that combines
  forward-paper performance, loss attribution, adaptive guard output, server
  timer/service state, exchange/manual exposure state, confirmation blockers,
  and explicit non-mutation guarantees.
- Phase 49 adds a paper/backtest-only `quant_setup_loss_recalibrated` variant
  and setup profile gates for blocked setup reasons, blocked negative factor
  names, missing open interest, thin liquidity, weak momentum, and weak volume
  impulse while leaving live defaults unchanged.
- Phase 50 adds `backtest matrix-suite`, which runs multiple hot-universe
  presets across `5m`/`15m` and baseline/recalibrated quant setup variants.
  The Phase 50 public-data report marks `quant_setup_selective_guarded` as a
  forward-paper candidate but keeps the overall verdict at
  `mixed_candidate_collect_more_data`.
- Phase 51 adds an explicit `min_profit_factor` gate to forward-paper
  performance checks while preserving post-change `since` filtering and keeping
  `live_resume_allowed=false`.
- Phase 52 adds a single read-only `ops live-resume-readiness` command that
  combines matrix, paper, server, exchange/manual exposure, risk-profile, and
  confirmation gates without restoring timers, applying profiles, or placing
  orders.
- Phase 53 deploys that readiness command to the isolated server and captures a
  secret-safe server artifact showing `keep_live_paused`, live timer/service
  inactive, paper timer active, and manual ETHUSDT classified outside
  agent-managed evidence.
- Phase 54 collects guarded `quant_setup_selective_guarded` evidence and keeps
  the system fail-closed: the current matrix is weaker than Phase 50, server
  guarded paper generated no post-change signals, and readiness remained
  `keep_live_paused` with manual/unattributed exposure blockers.
- Phase 55 adds a read-only operator resume decision packet that returns one of
  `keep_live_paused`, `collect_more_paper`, `resolve_exposure`, or
  `eligible_for_operator_resume` and requires a separate confirmation flow
  before any live resume.

### Active

- [x] Collect Binance USD-M futures market data needed for hot-coin filtering.
- [x] Collect narrative and hotness signals from Binance Square plus fallback
  social/news sources where access is allowed.
- [x] Record every candidate, AI decision, order intent, exchange response,
  fill, and outcome in a replayable local event store.
- [x] Rank candidate symbols by narrative heat, liquidity, price momentum, open
  interest change, taker flow, funding state, and volatility.
- [x] Use a configured AI provider to produce structured trade decisions with
  entry, invalidation, stop, target, time limit, and confidence.
- [x] Implement risk-capped Binance live execution for a small-USDT pilot account.
- [x] Deploy on server `64.83.34.222` under a project-isolated directory and
  systemd unit without modifying existing services.
- [x] Improve live AI decision quality so `trade` decisions include executable
  entry, stop, and target prices derived from market reference data.
- [x] Avoid spending AI/live execution cycles on hot symbols whose Binance
  minimum executable notional exceeds the active pilot position cap.
- [x] Use a controlled pilot symbol universe that is compatible with current
  Binance filters under small max-position-notional caps.
- [x] Fail closed when Binance margin/leverage setup cannot be applied before
  entry order submission.
- [x] Support explicit cross margin setup for the current Binance Multi-Assets
  account without increasing pilot caps.
- [x] Support explicit hedge position-side setup for the current Binance account
  without increasing pilot caps.
- [x] Reject live order intents before exchange order calls when Binance USD-M
  futures available balance is below estimated initial margin.
- [x] Switch server runtime caps to the approved 30 USDT/5x trial profile and
  verify health/live-status evidence.
- [x] Capture LVA-05 protective-order evidence after the first submitted live
  entry, or prove the fail-closed emergency path if protective orders fail.
- [x] Gate future timer resume with read-only exchange and AI-backoff checks.
- [x] Persist closed live trade fill/outcome evidence with gross PnL,
  commission, net PnL, and closed/open status.
- [x] Gate leverage/risk-cap profile changes on clear exchange state and
  reconciled submitted-trade outcomes.
- [x] Sweep submitted live trade intents and persist only final closed outcomes
  from Binance fill history.
- [x] Report whether active live positions have exceeded the AI decision's
  suggested hold window without modifying exchange state.
- [x] Produce a read-only close-order plan for overdue protected positions
  without placing orders.
- [x] Add an operator-approved time-exit execution command that refuses to run
  without a fresh confirmation token.
- [x] Add dynamic position sizing and an explicit multi-position guard for a
  later approved risk-profile increase.
- [x] Add a confirmation-gated risk-profile preview/apply tool so future live
  profile changes do not require manual env editing.
- [x] Add portfolio-level risk caps and a 30U/10x/two-position profile preview
  so higher leverage is bounded by total margin, total notional, and
  same-direction concentration.
- [x] Continue evaluating top-N hot symbols when the first candidate is skipped
  by AI pass or retryable symbol-level risk.
- [x] Allow protected active positions to be carried into a target
  multi-position profile only when exchange protection and target portfolio caps
  are both verified.
- [x] Deploy and run the Phase 52 live-resume readiness command on the server
  as a read-only check, with manual ETH/ETHUSDT exposure classified separately.
- [x] Collect post-change paper evidence for the selected guarded setup variant
  without creating live order intents or restoring live automation; Phase 54
  collected the evidence and did not promote it because samples were missing
  and readiness stayed fail-closed.
- [x] Produce a single operator-facing resume decision packet that separates
  "collect more paper evidence" from "eligible for separately confirmed live
  resume".
- [ ] Resolve or explicitly classify manual/unattributed exchange exposure so
  live-resume readiness no longer mixes operator trades with agent evidence.
- [ ] Make guarded paper evidence productive again by broadening observation,
  exposing skip reasons, and supporting paper-only exploration when strict
  guards generate zero signals.
- [ ] Re-run current-data matrix and forward-paper promotion gates before any
  live resume, using completed candles, fees, slippage, small-account caps, and
  post-change evidence boundaries.
- [ ] Capture user/manual liquidation incidents as structured learning input
  and compare them with deterministic setup and risk guards.
- [ ] Add a separate confirmation-gated live resume path that can only enable
  the target profile/timer after exposure, strategy, paper, server, and
  operator-confirmation gates pass.
- [ ] Keep Lana/public hot-coin claims as design inspiration only; all promotion
  and sizing decisions must come from local backtest, paper, exchange, and live
  outcome evidence.

### Out of Scope

- Full Hermes-style review workflow - too heavy for this faster crypto pilot.
- Real-money scaling above the active trial capital - requires separate evidence and
  explicit approval.
- Cross-exchange arbitrage - defer until Binance-only behavior is understood.
- Fully autonomous model self-modification - the system may learn from journals,
  but code/config promotion must remain explicit.
- Guaranteed imitation of any public trader's private strategy - public posts
  are incomplete and may be exaggerated.

## Context

The existing stock repository demonstrates useful operational patterns:
config-driven scripts, JSON/JSONL evidence files, dry-run/live separation,
event-store thinking, replay reports, and fail-closed execution. This project
keeps those useful patterns but deliberately stays lighter: no Hermes packet
layer, no Feishu notification dependency, no broad data-health ceremony before
every trade.

The user's chosen direction:

- New isolated directory: `F:\binance_futures_agent`.
- Deployment target: server `64.83.34.222`, root user, isolated path
  `/opt/binance-futures-agent`.
- Trading venue: Binance USD-M futures.
- Current trial capital: 30 USDT, after starting from an initial 100 USDT planning profile.
- Execution intent: live small-capital pilot, not only paper trading.
- First strategy focus: hot coins, especially Binance Square narratives.
- AI provider: DeepSeek for live use, with OpenAI Responses provider still
  available for fallback.
- Data-source preference: as many useful and allowed sources as possible.
- Binance API credentials are provided out of band; contents must be handled as
  secrets and never committed.

## Constraints

- **Isolation**: The project must not modify `F:\stock` or server-side existing
  services. Use its own repo, virtualenv, systemd unit, data directory, logs,
  and runtime files.
- **Capital**: Current trial capital is 30 USDT, so the live risk model
  must assume very small orders and high sensitivity to fees/slippage.
- **Execution**: Live mode is allowed, but default code paths must start in
  dry-run/test mode and require explicit environment configuration for live.
- **Risk**: Current trial defaults are max 5x leverage, max 12 USDT
  contract notional per position, max 0.3 USDT risk per trade, max 1 USDT
  daily loss, and max one concurrent position. Contract notional is not the
  same as initial margin; approximate margin is `notional / leverage`.
- **Exchange API**: Use official Binance USD-M futures APIs for market data,
  account state, and order placement.
- **Narrative APIs**: Binance Square reading may require browser automation,
  exports, or unofficial endpoints; implement this behind a replaceable
  collector interface and respect access limits.
- **AI**: AI provider calls must use structured JSON outputs and deterministic
  validation before a decision can become an order intent.
- **Secrets**: Store Binance, AI provider, cookie, and server credentials only
  in environment files or secret stores. Never write values to git or planning
  docs.
- **Deployment**: Server deployment must use a dedicated directory such as
  `/opt/binance-futures-agent`, a dedicated systemd unit, and gitignored runtime
  data under that directory.

## Current State

Milestones v1.0, v1.21, v1.22, v1.23, and v1.24 are archived. Phases 1 through
55 are complete, and the current server deployment is installed under the isolated
`/opt/binance-futures-agent` path. The project is installable as an isolated
Python package, has a safe environment contract, official Binance USD-M public
market-data access, narrative/manual/RSS ingestion, normalized JSONL evidence
output, a local SQLite event store, deterministic replay/report foundations,
hot-coin candidate scoring, structured AI decision validation, redacted AI
journaling, dry-run/live risk-gated execution, signed Binance execution
helpers, reconciliation reports, deployment health checks, CLI smoke commands,
automated one-cycle trading runner, live systemd timer assets, exchange-side
protective order submission, AI provider selection, AI timeout/backoff
behavior, market-heat fallback narratives, pilot tradability filtering, a
cap-compatible pilot universe, fail-closed margin setup handling, explicit
configurable margin mode, explicit position mode, account-balance preflight,
DeepSeek support, 30U/5x trial runtime caps, portfolio-level risk caps,
candidate-queue evaluation, and a confirmation-gated 30U/10x/two-position
profile preview. It also has read-only strategy evidence, loss-driven
recalibration variants, multi-universe matrix reporting, post-change
forward-paper gates, a combined live-resume readiness report, and server-side
readiness evidence from Phase 53.
Phase 20 adds a read-only resume gate for timer reactivation. Phase 21 adds
closed-trade outcome reconciliation and persisted fill/outcome accounting.
Phase 22 adds a stricter gate for leverage/risk-cap changes. Phase 23 tightens
that gate to require final closed outcomes. Phase 24 adds
`ops reconcile-outcomes` so submitted live trades can be swept and closed
outcomes persisted without symbol-by-symbol manual commands. Phase 25 adds
`ops position-hold-check` so active positions past their AI hold window are
visible before any future time-exit automation is considered. Phase 26 adds
`ops time-exit-plan` so the exact close-order shape can be inspected before any
operator-approved execution phase. Phase 27 adds `ops time-exit-execute`, which
re-runs signed live evidence and the time-exit plan, requires the exact
plan-derived confirmation token, blocks while the live service is active,
submits the planned close only after confirmation, and cancels symbol algo
orders only after a post-close position check reports zero size. Phase 28 adds
dynamic sizing that can compute notional caps from capital, available balance,
leverage, margin fraction, margin cap, stop distance, and exchange
min-notional pressure; it also adds explicit multi-position guards. Both remain
inactive in live until env settings are deliberately changed.
Phase 29 adds a `30u_8x_dynamic` profile preview/apply tool that writes only
approved non-secret risk keys, requires risk-change readiness and confirmation,
and backs up the env file before any write. The profile switch has been tested
and intentionally blocked on the server while HYPEUSDT remains open.
Phase 30 adds `30u_10x_multi_dynamic`, portfolio margin/notional/concentration
caps, live runner candidate-queue evaluation, exposure-status portfolio context,
and target-profile readiness checks that can carry a protected active position
only when active exposure fits the target profile caps. The live server env has
not been changed by Phase 30.
Post-archive hotfix `8fa704e` is also deployed on the server: AI confidence
values returned in percent form are normalized into the expected `0..1` range
with an audit warning, and server focused tests, the full 266-test suite, and a
secret-safe health check passed after deployment.

The server deployment is installed under `/opt/binance-futures-agent` with a
dedicated env file and systemd units. Binance and AI credentials are configured
out of band. The active trial profile is 30 USDT account capital, 5x max
leverage, 12 USDT max position notional, 0.3 USDT max per-trade risk, 1 USDT max
daily loss, and 1 open position.

A real ZECUSDT LONG was submitted before or during the Phase 19 profile-change
window under the prior 3x settings. It filled at `467.68` for quantity `0.032`
and later exited at `471.52`. Phase 21 reconciled that closed trade from
Binance fills and persisted a net result of `0.1078528` USDT after commission.
The ZECUSDT position cleared, `ops resume-check` returned `resume_allowed`, and
the live timer was re-enabled. The first resumed cycles submitted no order, then
a later timer cycle opened a separate BNBUSDT LONG under the 30U/5x profile.
Current live-status shows that BNBUSDT position has exchange-visible stop-loss
and take-profit algo orders; it has not yet been outcome-reconciled because it
is still open. Phase 24 server verification swept submitted outcomes, skipped
the already reconciled ZECUSDT trade, reported BNBUSDT as `open_or_partial`,
and inserted no new fills or outcomes. Phase 25 server verification reported
BNBUSDT as protected by two algo orders but past its 60-minute AI hold window,
with `status=review_required`.
Phase 26 server verification produced an `exit_plan_ready` read-only close plan:
`SELL MARKET 0.01` with `positionSide=LONG` and no `reduceOnly` flag because
the account uses hedge mode. Phase 27 adds the manual execution path, but no
confirmed live close has been approved or submitted.

Recent live and public Binance filter checks showed that BTCUSDT and ETHUSDT can
be cap-incompatible under very small max-position-notional settings, while
several hot-coin symbols can currently fit. Candidate generation rejects
cap-incompatible symbols before AI calls instead of relying only on later
order-intent rejection. The default pilot universe uses: HYPEUSDT, SOLUSDT,
ZECUSDT, WLDUSDT, XRPUSDT, AVAXUSDT, BNBUSDT, DOGEUSDT, NEARUSDT, and ADAUSDT.
The latest server forward-paper evidence is still negative: 212 paper signals,
204 settled outcomes, win rate about `0.299`, total net PnL about `-7.245`
USDT, and worst drawdown about `7.531` USDT for `quant_setup_selective` on
`5m`. The paper timer remains active; live timer/service remain inactive.
Phase 53 redeployed the current code to the isolated server and ran
`ops live-resume-readiness` read-only. The server result is
`status=keep_live_paused`, `live_resume_allowed=false`,
`paper.timer=active`, `live.timer=inactive`, `live.service=inactive`,
manual/unattributed symbols `ETHUSDT`, agent-managed symbols none, and all
read-only mutation flags false.
Phase 54 reran the guarded matrix and server guarded-paper path. The Phase 54
matrix for `quant_setup_selective_guarded` had `candidate_matrix_count=0`,
total net PnL `1.33136338` USDT, and worst drawdown `1.3130757` USDT, weaker
than Phase 50's `candidate_matrix_count=2`, total net PnL `7.1058786` USDT,
and worst drawdown `0.92783188` USDT. The server guarded paper run generated
`0` signals, the post-change performance check returned `no_paper_evidence`,
and readiness remained `keep_live_paused` with manual/unattributed `ETHUSDT`
and `BTWUSDT` exposure blockers.
Phase 55 added `ops operator-resume-decision`. Running it against the Phase 54
readiness artifact returns `status=resolve_exposure`, not live eligibility,
with grouped strategy, paper, exchange/manual exposure, risk-profile, and
confirmation blockers. It is read-only and cannot restore timers, apply
profiles, create order intents, or place/cancel Binance orders.

## Current Milestone: v1.25 Live Resume Clearance And Adaptive Pilot

**Goal:** Clear the current live-resume blockers, make paper evidence generate
useful post-change samples again, and prepare a separately confirmed small live
pilot resume path only after the evidence gates pass.

**Target features:**
- Classify current exchange/manual/unattributed exposure into an operator-facing
  clearance packet without placing or canceling orders.
- Broaden and instrument forward-paper collection so hot-symbol exploration
  records signals, skips, guard blocks, and outcomes across a larger universe.
- Recalibrate promotion evidence from current matrix and post-change
  forward-paper runs before any live timer/profile change.
- Capture manual failure cases, including liquidation, as structured incidents
  for strategy/risk review.
- Add a confirmation-gated live resume command/runbook that refuses to mutate
  server timers, env, or Binance state unless the operator decision is eligible.
- Deploy and collect server evidence while preserving isolation under
  `/opt/binance-futures-agent` and keeping `F:\stock` untouched.

## Previous Milestone: v1.8 Position Mode And Entry Fail-Closed

**Goal:** Match the current Binance account position-side mode explicitly while
preserving the same small-capital risk limits.

**Target features:**
- Validate `BFA_POSITION_MODE` as `one_way` or `hedge`.
- Send Binance `positionSide` values in hedge mode.
- Persist entry-order failures as rejected, non-submitted evidence.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Previous Milestone: v1.9 Balance Preflight Gate

**Goal:** Avoid repeated live order attempts when the Binance USD-M futures
account has less available balance than the order intent's estimated initial
margin.

**Target features:**
- Read account `availableBalance` before margin setup or entry order placement.
- Reject insufficient available balance with `insufficient_available_balance`.
- Reject account balance read errors before entry order placement.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Previous Milestone: v1.10 DeepSeek Provider Switch

**Goal:** Switch live AI decisions to DeepSeek while preserving strict JSON
validation and all pilot risk caps.

**Target features:**
- Select AI provider with `BFA_AI_PROVIDER`.
- Use DeepSeek Chat Completions JSON mode.
- Extract fenced/prefixed JSON before schema validation.
- Preserve 100 USDT pilot caps and unchanged execution risk gates.

## Previous Milestone: v1.11 30U Higher-Leverage Trial Profile

**Goal:** Configure the live system for a 30 USDT funded trial with a modest 5x
leverage ceiling while lowering absolute exposure.

**Target profile:**
- Account capital: 30 USDT.
- Max leverage: 5x.
- Max position notional: 12 USDT.
- Max risk per trade: 0.3 USDT.
- Max daily loss: 1 USDT.
- Max open positions: 1.

**Status:** Complete. Server caps are verified, live-status shows the current
ZECUSDT position and two protective algo orders, and the live timer is paused
for open-position review.

## Previous Milestone: v1.12 Timer Resume Gate

**Goal:** Make timer resume decisions auditable with a read-only gate.

**Target features:**
- Add `ops resume-check`.
- Return `resume_allowed` only for clear exchange/backoff state.
- Return `keep_paused` for protected active positions.
- Return `urgent_attention` for unprotected active positions or orphan orders.

**Status:** Complete. Server resume check first returned `keep_paused` for the
protected ZECUSDT position, then returned `resume_allowed` after the position
and algo orders cleared. The timer was re-enabled, and the first resumed cycle
plus the next scheduled cycle submitted no order.

## Previous Milestone: v1.13 Closed Trade Outcome Reconciliation

**Goal:** Turn completed live trades into replayable fill/outcome records with
net PnL after commission.

**Target features:**
- Add signed `userTrades` account-trade reads.
- Reconstruct latest submitted local trade intent from Binance fills.
- Report gross PnL, commission, net PnL, net quantity, fill times, and status.
- Persist fills and outcomes idempotently into the event store.

**Status:** Complete. The closed ZECUSDT trade is persisted with 2 fills and 1
outcome, net realized PnL `0.1078528` USDT, and repeat reconciliation inserts
no duplicates. The current BNBUSDT live position remains protected and should be
reconciled after it closes.

## Previous Milestone: v1.14 Risk Change Readiness Gate

**Goal:** Prevent leverage or risk-cap changes unless the exchange state is
clear and submitted live trades have outcome evidence.

**Target features:**
- Add `ops risk-change-check`.
- Block profile changes when positions, normal orders, algo orders, AI backoff,
  or missing exchange evidence are present.
- Block profile changes when submitted order intents lack persisted outcomes.
- Preserve read-only behavior; do not mutate env or exchange state.

**Status:** Complete. Current live BNBUSDT position does cause the gate to
return `keep_current_profile` for an 8x target.

## Previous Milestone: v1.15 Closed Outcome Risk Change Strictness

**Goal:** Ensure partial/open outcome artifacts cannot unlock leverage or
risk-cap profile changes.

**Target features:**
- Require `outcome:{event_id}:closed` for submitted-intent reconciliation.
- Keep `open_or_partial` outcomes blocking for risk-change readiness.
- Preserve read-only checks and unchanged execution behavior.

**Status:** Complete. Partial/open outcome artifacts remain blocking; submitted
intents require a final `closed` outcome before risk profile changes are
allowed.

## Previous Milestone: v1.16 Outcome Reconciliation Sweep

**Goal:** Make submitted-trade outcome cleanup a one-shot sweep instead of a
manual symbol-by-symbol operation.

**Target features:**
- Add `ops reconcile-outcomes`.
- Skip submitted intents that already have a final closed outcome.
- Persist only `closed` outcomes when `--persist-closed` is used.
- Keep open/partial outcomes report-only by default.

**Status:** Complete. Server sweep shows ZECUSDT already reconciled and
BNBUSDT still open/partial, with no new local fills or outcomes inserted.

## Previous Milestone: v1.17 Position Hold-Time Check

**Goal:** Make active-position hold-time overruns visible without adding
automatic exits.

**Target features:**
- Add `ops position-hold-check`.
- Match active positions to unclosed submitted intents.
- Report elapsed minutes, AI hold-time minutes, overdue status, unrealized PnL,
  and protective algo-order count.
- Keep the command read-only.

**Status:** Complete. Server check reports BNBUSDT as protected but past the
AI-provided 60-minute hold window.

## Previous Milestone: v1.18 Time Exit Plan

**Goal:** Make the overdue-position close order shape auditable before any
execution-capable time-exit work.

**Target features:**
- Add `ops time-exit-plan`.
- Require hold-time expiry and confirmed protection before a plan is ready.
- Emit side, order type, quantity, position side, reduce-only flag, and
  supporting hold-check evidence.
- Keep the command read-only.

**Status:** Complete. Server plan for BNBUSDT is ready and remains read-only.

## Previous Milestone: v1.19 Operator-Approved Time Exit Execution

**Goal:** Make manual time exits executable only through an auditable
confirmation gate.

**Target features:**
- Add `ops time-exit-execute`.
- Re-run live signed evidence and the Phase 26 plan before execution.
- Emit a confirmation token and place no order without it.
- Close using the planned market order only when the token matches.
- Cancel remaining symbol algo orders only after the position is confirmed
  flat.
- Persist time-exit execution evidence.

**Status:** Complete and deployed. Live execution remains confirmation-gated
and no close order is submitted unless the operator explicitly approves the
fresh token.

## Previous Milestone: v1.20 Dynamic Sizing And Multi-Position Guard

**Goal:** Let a later approved profile use larger, account-aware position sizes
and optionally more than one open position without losing deterministic risk
control.

**Target features:**
- Add dynamic position sizing config and calculations.
- Feed computed notional caps into candidate filtering, AI context, and final
  execution risk.
- Keep fixed 12U/one-position behavior unless live env explicitly enables the
  new controls.
- Add multi-position guard with same-symbol same-direction duplicate rejection.

**Status:** Complete and deployed. Server tests passed, and live env remains
5x/12U/one-position with dynamic sizing and multi-position disabled while
HYPEUSDT is open.

## Shipped Milestone: v1.21 Confirmation-Gated Risk Profile Switch

**Goal:** Make future live profile changes auditable, previewable, and
confirmation-gated.

**Target features:**
- Add `ops risk-profile-plan`.
- Add `ops risk-profile-apply`.
- Support a `30u_8x_dynamic` profile and optional two-position mode.
- Require risk-change readiness plus confirmation token before writing env.
- Back up the env and preserve credentials/provider/margin/position-mode keys.

**Status:** Complete and deployed. Server plan and blocked-apply verification
passed; live env remains 5x/12U/one-position while HYPEUSDT is open.

## Shipped Milestone: v1.23 Strategy Evidence And Live Resume Readiness

**Goal:** Turn the negative forward-paper evidence into a tighter,
evidence-backed strategy workflow and define the exact gates required before
any small live automation can be resumed.

**Target features:**

- Produce a compact evidence baseline from current paper performance, loss
  attribution, adaptive guard output, and server timer/env state.
- Recalibrate deterministic setup profiles from loss attribution, especially
  stop-loss geometry, time-exit behavior, weak symbols, sides, and factors.
- Run refreshed multi-window hot-symbol backtests and forward-paper checks so
  promotion is based on repeated evidence rather than one selected interval.
- Keep live auto-hot and higher-risk profiles disabled until read-only dry-run
  and readiness gates pass.
- Add a single live-resume readiness report that separates strategy evidence,
  server state, exchange/manual exposure, and operator confirmation.

**Status:** Complete and archived. This milestone created the decision surface
for future live resume, but it did not authorize live timer restore, higher-risk
profile apply, or order submission.

## Shipped Milestone: v1.24 Server Readiness And Paper Promotion

**Goal:** Move the v1.23 readiness work from local proof to server evidence,
then collect guarded post-change paper evidence before any separately approved
live resume.

**Target features:**

- Deploy or verify `ops live-resume-readiness` on the isolated server path and
  run it read-only with manual ETH/ETHUSDT exposure marked as manual.
- Keep live timer/service disabled while server readiness reports explain
  strategy, paper, exchange, manual exposure, profile, and confirmation
  blockers.
- Run current-data matrix and guarded forward-paper evidence for
  `quant_setup_selective_guarded`, with a clear post-change evidence boundary.
- Produce a resume decision packet that says whether to keep collecting paper,
  investigate exchange/manual exposure, or prepare a separate operator-confirmed
  live resume.

**Status:** Complete and archived. Phases 53-55 are complete. No server live
automation, risk profile, or Binance order state was changed for this
milestone. The archived operator decision is `resolve_exposure`, so live
remains paused.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Create `F:\binance_futures_agent` | Keeps crypto futures work separate from the stock system. | Phase 1 complete |
| Use Python first | Binance/OpenAI clients, data processing, CLI tooling, and tests are straightforward in Python. | Phase 1 scaffold complete |
| Use Binance USD-M futures official APIs | The pilot trades USDT-margined contracts and needs supported market/order endpoints. | Phase 2 public market data complete |
| Start with hot-coin strategy | The user wants a controlled imitation of the Square/narrative-driven approach. | Phase 3 narrative collection complete |
| Use local event store before strategy assembly | Replayability and auditability are required before candidate scoring and live trading. | Phase 4 event store complete |
| Generate candidates before AI decisions | Deterministic scoring should filter and explain candidates before model evaluation. | Phase 5 candidate strategy complete |
| Use OpenAI for structured decisions, not direct raw orders | Keeps AI reasoning auditable and lets deterministic risk code retain final control. | Phase 6 complete |
| Keep deterministic risk/execution code in final control | Live mode must be explicit, risk-capped, persisted, and reconcilable before touching Binance. | Phase 7 complete |
| Deploy dry-run-first | Server deployment should prove isolation and health before any live trading mode is enabled. | Phase 8 complete |
| Keep LLM slow-path with backoff | API outages or slow responses should skip trading rather than block deterministic safety logic. | Phase 9 complete for activation |
| Track margin vs notional explicitly | Futures UI can show small margin such as 1 USDT, while Binance order filters validate contract notional and quantity. | Phase 9 follow-up |
| Require market reference price for AI trade geometry | The model should not invent executable prices from summaries alone. | Phase 11 complete |
| Filter for pilot tradability before AI | Hot symbols that cannot fit Binance minimum executable notional under the pilot cap should not consume AI/execution cycles. | Phase 12 complete |
| Use cap-compatible pilot universe | BTC/ETH can be impossible under a 20 USDT notional cap; the pilot needs tradable high-liquidity symbols without raising caps. | Phase 13 complete |
| Fail closed on margin setup errors | Binance account mode can reject isolated-margin setup; no entry should be submitted unless pre-entry setup succeeds. | Phase 14 complete |
| Make margin mode explicit | The live account is Multi-Assets/cross; using cross must be deliberate, validated, and still capped. | Phase 15 complete |
| Make position mode explicit | The live account can require hedge `positionSide`; using it must be deliberate, validated, and still capped. | Phase 16 complete |
| Add balance preflight before live orders | The live account can be unfunded even when order geometry is valid; avoid repeated exchange-side insufficient-margin errors. | Phase 17 complete |
| Add DeepSeek provider support | The previous OpenAI-compatible endpoint was intermittent and returned invalid JSON; DeepSeek can use Chat Completions JSON mode behind the same validation gates. | Phase 18 complete and deployed |
| Switch to 30U/5x trial profile | User wants to fund 30 USDT for a first live trial; higher leverage is allowed only with tighter absolute notional/loss/concurrency caps. | Phase 19 complete; timer paused for open-position review |
| Gate timer resume with exchange state | Timer resume should be a read-only decision based on live positions, open orders, algo orders, and AI backoff rather than manual JSON interpretation. | Phase 20 complete |
| Persist closed-trade outcomes | Live strategy changes need net-of-fee realized PnL evidence, not only submitted order records. | Phase 21 complete |
| Gate risk profile changes | Higher leverage should require clear exchange state and reconciled trade outcomes, not just operator intent. | Phase 22 complete |
| Require closed outcomes before risk changes | Partial/open accounting should not unlock higher leverage. | Phase 23 complete |
| Sweep submitted outcomes before risk changes | Operators should not need symbol-specific one-off commands to clear closed outcome evidence after positions exit. | Phase 24 complete |
| Check active position hold time | Positions that exceed AI hold guidance should be visible before adding any automated time-exit behavior. | Phase 25 complete |
| Plan time exits before execution | The system should show exact close-order parameters before any automated or operator-approved time exit is built. | Phase 26 complete |
| Confirm before time-exit execution | Manual time exits should be possible, but only through a fresh confirmation token and post-close cleanup checks. | Phase 27 complete locally |
| Size dynamically before increasing risk | Higher leverage should scale through explicit margin/risk formulas, not ad hoc env edits. | Phase 28 complete locally |
| Profile switches need confirmation | Moving to 8x/dynamic sizing should be a token-confirmed env diff, not a manual edit. | Phase 29 complete and deployed |
| Open positions should not freeze scanning | A mature hot-coin system must keep evaluating new candidates while active exposure is protected and capacity remains. | Phase 30 complete locally |
| High leverage needs portfolio caps | 10x on 30 USDT is possible only when total margin, total notional, and same-direction concentration are bounded. | Phase 30 complete locally |
| Protected active positions may be carried forward | Profile changes can accept existing exposure only if exchange protection is present, unreconciled intents match active positions, and target caps absorb the exposure. | Phase 30 complete |
| Manage active positions before new entries | Each live cycle should inspect active positions and expose deterministic adjustment plans before scanning for new trades. | Phase 32 complete locally |
| Filter reduce orders before confirmation | Tiny-account partial exits must satisfy Binance quantity and notional filters before the system exposes an executable token. | Phase 33 complete and deployed |
| Public Lana claims are inspiration, not proof | Screenshots and social posts inform architecture ideas but do not verify profitability. | Phase 30 complete locally |
| Evidence before live resume | The latest paper evidence is negative, so v1.23 prioritizes strategy evidence, recalibration, and explicit readiness gates over restoring unattended live automation. | v1.23 complete |
| Baseline before recalibration | Weak setup changes should be driven by one compact current evidence report before profiles or live-readiness gates are changed. | Phase 48 complete |
| Recalibration stays paper-first | Loss-driven filters should be explicit backtest/paper variants until repeated matrix and forward-paper evidence pass. | Phase 49 complete |
| Matrix before forward-paper promotion | Backtest evidence must cover multiple hot universes and intervals before any post-change forward-paper gate can be trusted. | Phase 50 complete |
| Paper promotion needs profit factor | Post-change forward-paper evidence must pass PnL, win-rate, profit-factor, and drawdown gates before readiness reporting can consider it. | Phase 51 complete |
| Live resume requires a single read-only readiness report | Restoring live automation should depend on matrix, paper, server, exchange/manual exposure, risk-profile, and confirmation gates, not scattered command interpretation. | Phase 52 complete; v1.23 archived |
| Server evidence before resume | Local readiness is not enough; the isolated server must run the same read-only command against current timers, env, exchange, and manual exposure. | Phase 53 complete |
| Guarded paper before live | The Phase 50 guarded variant needs post-change server paper evidence before any live timer restore discussion. | Phase 54 complete; evidence not promoted |
| Operator packet before live | Readiness JSON needs one operator-facing next action before any separate live resume confirmation flow is prepared. | Phase 55 complete; current packet says `resolve_exposure` |
| Public hot-coin claims require local proof | Lana/Square/X screenshots can inspire data and factor design, but cannot promote live risk without local matrix, paper, and live outcome evidence. | v1.25 active |
| Live resume is a separate mutation | Readiness can only produce eligibility; profile/timer changes need a fresh confirmation command and token. | v1.25 active |
| Horizontal layer roadmap | User chose to build infrastructure layers before full assembly. | - Pending |
| Live small-capital pilot allowed | User explicitly chose live small本金 over testnet-only; current trial target is 30 USDT. | Phase 19 complete |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. "What This Is" still accurate? Update if drifted.

**After each milestone**:
1. Full review of all sections.
2. Core Value check - still the right priority?
3. Business Context check - customer, revenue model, and success metric still
   accurate?
4. Audit Out of Scope - reasons still valid?
5. Update Context with current state.

---
*Last updated: 2026-06-21 after starting v1.25 milestone.*
