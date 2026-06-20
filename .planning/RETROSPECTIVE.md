# Retrospective

## Milestone: v1.0 — Dry-Run Binance Futures Agent

**Shipped:** 2026-06-19
**Phases:** 8
**Plans:** 28

### What Was Built

- Independent crypto futures repo, config contract, secret hygiene, and dry-run
  diagnostics.
- Binance USD-M public market-data access, narrative ingestion, event store,
  replay packet generation, and review metrics.
- Hot-coin candidate ranking, OpenAI structured decision validation, and
  secret-safe decision journaling.
- Risk-gated Binance execution helpers, server deployment assets, and isolated
  health checks.

### What Worked

- Building horizontal layers made each high-risk component testable before
  connecting it to live trading.
- Keeping execution deterministic made it possible to add live automation later
  without giving the LLM direct control over safety gates.
- Isolated deployment paths prevented the new project from touching the existing
  stock system.

### What Was Inefficient

- The first milestone closed as dry-run even though the real product goal is
  live automated trading, so v1.1 now exists specifically to finish live
  activation.
- GSD milestone archival was started before live activation planning was
  explicit, leaving a short cleanup pass necessary.

### Patterns Established

- LLM is slow-path analyst/veto only; order placement, protective orders, and
  kill switch stay deterministic.
- Server timers should remain disabled until one manual service cycle is
  reviewed.
- Credentials are configured out of band and never emitted in repo output.

### Key Lessons

- Futures automation needs protective orders in the same execution path as live
  entries, not just a separate risk document.
- AI latency must fail closed; timeout is a risk control, not only a performance
  tweak.
- GSD state should distinguish "dry-run deployed" from "live pilot activated" so
  progress is honest.

## Milestone: v1.21 — Live Pilot Risk Controls

**Shipped:** 2026-06-20
**Phases:** 21
**Plans:** 21

### What Was Built

- Live small-capital Binance USD-M pilot activation with protective-order
  evidence, AI timeout/backoff behavior, and server systemd timer controls.
- Short-window backtesting, pilot tradability filtering, and a cap-compatible
  hot-coin universe for small notional caps.
- Fail-closed execution hardening for margin mode, hedge position side, entry
  order failures, and account-balance preflight.
- DeepSeek provider support behind the same strict JSON decision validation and
  deterministic risk gates.
- Closed-trade outcome reconciliation, submitted-intent sweeps, hold-time
  checks, time-exit planning, and confirmation-gated time-exit execution.
- Dynamic sizing, bounded multi-position guards, and confirmation-gated
  risk-profile preview/apply tooling for a future 30U/8x profile.

### What Worked

- The server stayed isolated under `/opt/binance-futures-agent`, and the live
  profile changes stayed narrowly scoped to this project.
- Separating read-only checks from execution-capable commands made it possible
  to verify live state without accidentally mutating Binance positions.
- Confirmation tokens gave risky operator actions a clean two-step workflow:
  preview first, execute only with the exact current token.
- Treating notional, margin, stop-risk, and exchange minimums as separate
  quantities prevented a small-margin futures UI from hiding real exposure.

### What Was Inefficient

- Several phases existed because live Binance account settings surfaced one at
  a time: Multi-Assets cross margin, hedge position side, and tiny-account
  balance checks.
- Early milestone docs carried historical BNBUSDT state forward after the
  active live position changed to HYPEUSDT, so archive closeout needed a
  cleanup pass to separate history from current operator instructions.
- The Square/narrative layer still relies on fallback market-heat signals more
  than a complete external narrative dataset.

### Patterns Established

- LLM decisions remain a slow-path structured filter; final order permission
  stays in deterministic validation and risk gates.
- Higher leverage is not a manual env edit: it requires clear exchange state,
  final closed outcome evidence, risk-change readiness, and a confirmation
  token.
- Live time exits are operator-approved and evidence-backed, not automatic.
- Dynamic sizing is enabled only by explicit profile switch and still bounded by
  margin fraction, margin cap, risk per trade, max open positions, and duplicate
  exposure checks.

### Key Lessons

- Small futures accounts need sizing math that talks in both contract notional
  and estimated initial margin, otherwise the numbers look inconsistent.
- A profitable-looking or operationally tempting risk increase should wait
  until the current protected position is closed and reconciled.
- Backtests help select parameter ranges, but live pilot controls need their own
  gates because fees, filters, funding, and account modes dominate tiny orders.
- Archive docs must preserve historical live symbols while keeping current
  operator next steps pointed at the actual active position.

## Milestone: v1.22 — Portfolio Risk And Multi-Position

**Shipped:** 2026-06-20
**Phases:** 18
**Plans:** 18

### What Was Built

- Portfolio-level risk caps, candidate-queue evaluation, and a confirmation-gated
  30U/10x/two-position preview profile.
- Read-only active-position review plus confirmation-gated adjustment planning
  and Binance filter-aware reduce-order checks.
- Deterministic multi-factor setup generation, setup-driven backtesting, and
  traceable AI overlay/veto behavior.
- Strategy promotion gates, calibrated setup variants, and interval-aware
  forward-paper admission.
- Paper-only evidence collection, scheduling, performance checks, loss
  attribution, guarded calibration, and adaptive candidate guards.
- Live auto-hot scanner plumbing proven through dry-run while unattended live
  auto-hot stayed disabled.

### What Worked

- Separating live authority from paper evidence let the system improve selection
  discipline without opening new live risk.
- Deterministic setup ownership made the old thin AI-only decision path
  auditable and much easier to challenge.
- Server deployment stayed isolated under `/opt/binance-futures-agent`; paper
  timer active and live service/timer inactive is now a repeatable state.

### What Was Inefficient

- Several early v1.22 phases were missing verification reports, so the milestone
  close required retroactive verification for Phases 30-32.
- The system accumulated evidence mechanisms faster than profitable evidence;
  paper performance remains negative and live resume stays blocked.

### Patterns Established

- AI is overlay/veto only; deterministic setup owns side, point, stop, target,
  notional, and hold time.
- Wider candidate breadth is acceptable only when order authority remains behind
  setup, AI/quant fallback policy, and risk gates.
- Paper loss evidence can feed back into symbol, side, and factor guards before
  live promotion is considered.

### Key Lessons

- A wider hot-symbol universe can collect better evidence, but it also exposes
  more bad symbols; adaptive guardrails are mandatory.
- Passing one selected interval is not live evidence; all-interval and
  forward-paper gates need to remain separate.
- Social proof from public traders is useful for architecture ideas, not for
  promotion decisions.

## Milestone: v1.23 — Strategy Evidence And Live Resume Readiness

**Shipped:** 2026-06-21
**Phases:** 5
**Plans:** 5

### What Was Built

- Compact read-only strategy evidence baseline with forward-paper performance,
  loss attribution, adaptive guards, server timer state, exposure state, and
  grouped live-resume blockers.
- Loss-driven setup recalibration profiles and a stricter
  `quant_setup_loss_recalibrated` paper/backtest variant.
- Multi-universe `backtest matrix-suite` across hot-symbol presets, intervals,
  and setup variants.
- Profit-factor aware post-change forward-paper gates.
- Single read-only `ops live-resume-readiness` command that separates manual
  exposure from agent-managed exposure and refuses to mutate live state.

### What Worked

- The readiness command made the live-resume decision auditable in one place
  instead of spreading it across paper reports, server state, and exchange
  checks.
- Treating manual ETH/ETHUSDT exposure as manual exposure prevents operator
  trades from contaminating strategy evidence.
- Keeping all v1.23 commands read-only let the project advance without
  accidentally restoring live automation.

### What Was Inefficient

- The earlier strategy surface was too thin, so v1.23 had to add several
  evidence layers before it could honestly answer whether live resume is ready.
- Runtime matrix evidence is intentionally uncommitted, which means future
  live-resume reviews must rerun it rather than relying on the archived report
  alone.

### Patterns Established

- Live resume is a gate, not a side effect of passing one metric.
- Matrix, post-change paper evidence, server timers, exchange/manual exposure,
  and profile confirmation all need to agree before unattended live trading is
  considered.
- AI and public social-trader inspiration can inform the workflow, but local
  evidence decides promotion.

### Key Lessons

- A mature futures bot needs to track active and manual exposure continuously;
  otherwise it will mistake account state for strategy state.
- Profit factor matters because win rate and net PnL alone can hide unstable
  payoff geometry.
- Faster live progress still needs a hard distinction between paper evidence,
  preview commands, and execution authority.

## Milestone: v1.24 — Server Readiness And Paper Promotion

**Shipped:** 2026-06-21
**Phases:** 3
**Plans:** 3

### What Was Built

- Server readiness helper and evidence path for `ops live-resume-readiness`
  under the isolated deployment.
- Guarded `quant_setup_selective_guarded` matrix and server paper evidence
  collection, with a clear post-change timestamp boundary.
- Read-only `ops operator-resume-decision` packet that converts readiness JSON
  into one next-action status.
- Milestone audit and Nyquist validation coverage for Phases 53-55.

### What Worked

- The server stayed fail-closed while evidence was gathered; live timer/service
  remained inactive and no profile/order mutation was performed.
- The operator packet made the current state unambiguous:
  `resolve_exposure`, not "almost ready".
- Feeding the Phase 54 readiness artifact into the Phase 55 packet gave a cheap
  end-to-end smoke test without touching Binance again.

### What Was Inefficient

- Phase 54 generated no guarded paper signals, so evidence collection proved
  safety but did not improve promotion confidence.
- GSD milestone tooling used UTC dates during archive, requiring a local-date
  cleanup pass.
- The validation/audit artifacts had to be added retroactively for Phases 53-55
  to satisfy the active Nyquist workflow.

### Patterns Established

- A live-resume workflow should end in an operator decision packet, not a raw
  readiness JSON file.
- Manual/unattributed exchange exposure has priority over paper evidence when
  deciding the next operational action.
- "No signal" is evidence too; it must fail closed instead of being treated as
  harmless silence.

### Key Lessons

- The bot should not resume live just because the code path is safe; it also
  needs fresh, positive strategy evidence.
- Operator-opened positions need explicit classification, otherwise the system
  cannot distinguish account risk from bot risk.
- Archive tooling should be checked for timezone drift before final milestone
  commits.

## Milestone: v1.25 — Live Resume Clearance And Adaptive Pilot

**Shipped:** 2026-06-21
**Phases:** 5
**Plans:** 5

### What Was Built

- Read-only exposure clearance and append-only manual loss intake so manual,
  unknown, stale-attributed, and agent-managed exchange exposure can be
  separated before resume decisions.
- Forward-paper observations for generated and rejected hot-symbol candidates,
  including guard blocks, skip reasons, setup factors, and source health.
- Promotion-stage reporting plus manual loss review, keeping public Lana/Square/X
  claims as design inputs rather than promotion proof.
- Confirmation-gated `ops live-resume-plan` and `ops live-resume-apply`.
- Server Phase 60 evidence artifacts and a widened active pilot profile:
  10x, 6 open positions, 60 USDT per-position notional, 360 USDT portfolio
  notional, 300 USDT same-direction notional, 0.4 USDT per-trade risk, and
  1 USDT daily loss.

### What Worked

- Manual `BTWUSDT` classification kept operator exposure out of bot-managed
  adjustment logic.
- Server artifacts made the state legible: entry capacity is available, but
  formal live-resume apply remains blocked by current evidence.
- Tight env-key allowlists let caps be widened without touching credentials or
  unrelated server projects.

### What Was Inefficient

- The user needed live to run while iteration continued, so the workflow had to
  support safe server changes around active timers instead of a clean paused
  lab environment.
- GSD archive tooling again used UTC and broad phase counts, requiring manual
  correction for local date and v1.25-only stats.
- Nyquist validation files had to be backfilled before the milestone audit could
  pass cleanly.

### Patterns Established

- Live pilot caps can be adjusted in narrow, auditable steps while preserving
  per-trade and daily-loss limits.
- Manual positions must be listed in config and respected by hot-symbol,
  position-review, and adjustment-plan flows.
- "Resume workflow eligibility" and "operator-started live pilot is active" are
  separate states; the former can remain fail-closed while the latter runs.

### Key Lessons

- Active-position handling is now the next bottleneck: `NEARUSDT` reached
  `close_review`, but execution remains confirmation-gated/blocked.
- Wider notional caps only matter if dynamic sizing fractions also allow larger
  effective sizing.
- The system should make trade-management decisions explicit enough that the
  operator can audit why a position is held, reviewed, reduced, or closed.

## Milestone: v1.26 — Live Position Management And Pilot Learning

**Shipped:** 2026-06-21
**Phases:** 5
**Plans:** 5

### What Was Built

- Close-review diagnostics and filter-aware close/reduce plan candidates for
  agent-managed positions, while manual `BTWUSDT` stays non-actionable.
- Guarded `ops position-adjustment-execute` behavior with fresh tokens,
  live-service blocks, post-action size checks, and protective cleanup
  deferral.
- Live-cycle lifecycle persistence before new-entry scanning, plus dormant
  env-gated auto-management controls.
- `ops live-outcome-ledger` with attribution and recommendation-only guard
  feedback.
- Read-only `ops pilot-learning-packet` deployed to the isolated server with
  lifecycle, cap, exit, ledger, trace, manual-symbol, and mutation-proof
  evidence.

### What Worked

- The manual-position boundary held across lifecycle, entry-capacity, exit-plan,
  execution-preview, and server packet flows.
- The packet gave one operator-readable view of the live pilot without placing
  orders, writing env files, changing systemd state, or applying guard/risk
  changes.
- Outcome attribution became useful enough to inform next-milestone scope
  without pretending five closed outcomes prove profitability.

### What Was Inefficient

- Milestone archival tooling mis-counted all historical phases and plans during
  the first close attempt, so v1.26 required a manual correction pass.
- Several server evidence artifacts live under runtime paths and must be
  regenerated when the current account state changes.
- Auto-management is intentionally dormant, so the operator still needs a
  separate decision before exits become unattended.

### Patterns Established

- Position stewardship must happen before entry generation in every live cycle.
- Learning artifacts should include explicit mutation proof, not just "read-only"
  prose.
- Guard feedback should recommend changes but never apply strategy/risk changes
  by itself.

### Key Lessons

- A readable active-position lifecycle is as important as a readable entry
  decision for high-leverage futures.
- Scaling caps because the bot can open more trades is different from proving
  the strategy deserves more risk.
- Archive tooling output must be checked against the milestone scope before it
  becomes project history.

## Cross-Milestone Trends

| Trend | Evidence | Next Action |
|-------|----------|-------------|
| Safety gates are moving from docs into code | Protective orders, kill switch, AI timeout, resume/risk-change/time-exit gates | Keep new live actions behind read-only preview plus confirmation |
| External credentials are configured out of band | Binance and AI credentials are present on the server without being committed | Continue treating env files and keys as non-repo secrets |
| Risk increases require evidence, not enthusiasm | HYPEUSDT/manual exposure and negative paper evidence block formal live resume; v1.25/v1.26 caps were widened only within absolute portfolio/risk gates | Use live outcomes, packet evidence, paper evidence, drawdown, and profit factor before further scale-up |
| Tiny-account futures constraints shape the product | Binance filters, notional-vs-margin, spread, and fees drive sizing | Keep tradability filters and staged backtests before further scaling |
| Live resume needs a single decision surface | v1.23 combines matrix, paper, server, exchange/manual exposure, profile, and confirmation gates; v1.24 adds the operator decision packet; v1.25 adds the confirmation-gated resume plan/apply path; v1.26 adds the pilot learning packet | Use operator packets and pilot learning packets before formal profile/risk changes, even when the live timer is already running |
| Manual positions need first-class isolation | ETH/ETHUSDT, BTWUSDT, and NEARUSDT evidence showed how quickly manual and bot exposure can mix | Keep manual symbols explicit and exclude them from bot-managed reduction/entry decisions; verify every packet still classifies `BTWUSDT` as manual |
