# Milestones

## v1.26 Live Position Management And Pilot Learning (Shipped: 2026-06-21)

**Phases completed:** 5 phases, 5 plans, 15 tasks

**Archived artifacts:**

- `.planning/milestones/v1.26-ROADMAP.md`
- `.planning/milestones/v1.26-REQUIREMENTS.md`
- `.planning/milestones/v1.26-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Repaired close-review diagnostics so agent-managed positions expose exact
  preconditions, exchange-filter state, urgency, and filter-aware close/reduce
  candidates while manual `BTWUSDT` remains non-actionable.

- Hardened operator-confirmed close/reduce execution with fresh plan tokens,
  live-service guards, post-action position checks, and protective-order cleanup
  deferral when cross-side algo orders make cleanup unsafe.

- Persisted active-position lifecycle decisions before every live new-entry
  scan and added dormant env-gated auto-management controls.

- Added live outcome ledger with optional idempotent reconciliation,
  attribution by symbol/side/setup/factor/exit/hold behavior, and
  recommendation-only guard feedback.

- Deployed the read-only pilot learning packet on the isolated server with
  lifecycle, cap, exit, ledger, trace, manual-symbol, and mutation-proof
  evidence.

**Known deferred items at close:**

- The pilot learning packet is an evidence bundle, not proof of strategy
  profitability; future risk increases still require repeated positive live
  outcomes, drawdown checks, and profit-factor gates.

- Automatic position management exists but remains env-disabled unless the
  operator explicitly enables it.

- Manual `BTWUSDT` remains excluded from bot-managed entry capacity and
  position-management actions.

---

## v1.25 Live Resume Clearance And Adaptive Pilot (Shipped: 2026-06-21)

**Phases completed:** 5 phases, 5 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.25-ROADMAP.md`
- `.planning/milestones/v1.25-REQUIREMENTS.md`
- `.planning/milestones/v1.25-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Added read-only exposure clearance and append-only manual loss intake so
  active exchange positions can be classified as agent-managed, manual,
  stale-attributed, or unknown before any resume decision.

- Made forward-paper observation diagnosable across broad auto-hot universes by
  persisting generated signals, skipped candidates, guard blocks, setup factors,
  and source-health summaries.

- Re-ran current strategy promotion evidence with explicit
  `collect_more_paper`, `forward_paper_allowed`, and `live_resume_eligible`
  stages while keeping public Lana/Square/X claims as design inputs only.

- Added a confirmation-gated live resume preview/apply path that refuses to
  mutate env, systemd, Binance state, or order intents unless the operator
  packet is eligible and the live-resume token matches.

- Deployed and verified server evidence for Phase 60, preserved `BTWUSDT` as a
  manual position, and widened the active live pilot profile to 10x, 6 open
  positions, 60 USDT per-position notional, 360 USDT portfolio notional, and
  300 USDT same-direction notional while keeping 0.4 USDT per-trade risk and
  1 USDT daily loss.

**Known deferred items at close:**

- `NEARUSDT` is agent-managed and currently needs active-position review
  follow-up because its hold window expired; no close was executed in v1.25.

- Formal live-resume apply remains blocked by current strategy/paper/exposure
  evidence, which is the intended fail-closed behavior.

---

## v1.24 Server Readiness And Paper Promotion (Shipped: 2026-06-21)

**Phases completed:** 3 phases, 3 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.24-ROADMAP.md`
- `.planning/milestones/v1.24-REQUIREMENTS.md`
- `.planning/milestones/v1.24-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Deployed and ran the read-only server readiness evidence path for
  `ops live-resume-readiness` without restoring live timers, applying risk
  profiles, editing env files, or placing/canceling Binance orders.

- Collected current guarded `quant_setup_selective_guarded` matrix and server
  paper evidence, compared it to Phase 50, and kept live resume fail-closed
  when the evidence weakened and generated no post-change paper signals.

- Added `ops operator-resume-decision`, a read-only packet that converts
  readiness JSON into one of `keep_live_paused`, `collect_more_paper`,
  `resolve_exposure`, or `eligible_for_operator_resume`.

- Preserved the separation between manual/unattributed exposure and
  agent-managed evidence; the current packet reports `ETHUSDT` and `BTWUSDT`
  as manual/unattributed blockers.

- Added v1.24 milestone audit and Nyquist validation coverage for Phases 53-55.

**Known deferred items at close:**

- Live automation remains paused; the current operator packet returns
  `resolve_exposure`, not live eligibility.

- Manual/unattributed `ETHUSDT` and `BTWUSDT` exposure must be resolved or
  classified before any future live resume confirmation flow.

- Guarded paper evidence is still insufficient; Phase 54 generated zero
  post-change signals for the guarded variant.

- Applying `30u_10x_multi_dynamic` remains outside this milestone and requires
  a separate confirmation-gated risk-profile path.

---

## v1.23 Strategy Evidence And Live Resume Readiness (Shipped: 2026-06-21)

**Phases completed:** 5 phases, 5 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.23-ROADMAP.md`
- `.planning/milestones/v1.23-REQUIREMENTS.md`
- `.planning/milestones/v1.23-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Added a compact read-only strategy evidence baseline that combines
  forward-paper performance, loss attribution, adaptive guards, server timer
  state, exchange/manual exposure, and explicit live-resume blockers.

- Added `quant_setup_loss_recalibrated` and stricter paper/backtest setup
  gates without changing live defaults.

- Added a multi-universe `backtest matrix-suite` across hot-symbol presets,
  intervals, and setup variants; the best candidate remains evidence-only and
  not live-ready.

- Added a forward-paper profit-factor gate and preserved post-change `since`
  filtering so new evidence can be evaluated separately from older losing
  samples.

- Added read-only `ops live-resume-readiness`, separating manual exposure from
  agent-managed exposure and proving that the command cannot restore timers,
  apply risk profiles, or place orders.

**Known deferred items at close:**

- Live automation remains paused because matrix and post-change forward-paper
  evidence are not yet strong enough for live resume.

- Phase 52 readiness command still needs server deployment/read-only execution
  before any separate operator-approved live-resume decision.

- Manual ETH/ETHUSDT exposure must be passed as manual exposure and must not be
  counted as agent strategy evidence.

- Runtime matrix evidence under `runtime/` is intentionally uncommitted and must
  be rerun before future live-resume decisions.

---

## v1.22 Portfolio Risk And Multi-Position (Shipped: 2026-06-20)

**Phases completed:** 18 phases, 18 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.22-ROADMAP.md`
- `.planning/milestones/v1.22-REQUIREMENTS.md`
- `.planning/milestones/v1.22-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Added portfolio-level margin, margin-fraction, total-notional, and
  same-direction exposure caps for controlled multi-position profiles.

- Added active-position review plus confirmation-gated adjustment planning so
  open positions are reviewed before new entries are scanned.

- Moved side, entry, stop, target, notional, hold time, and traceability into a
  deterministic multi-factor setup layer with AI as overlay/veto only.

- Added setup-driven backtesting, strategy promotion gates, calibrated variants,
  and interval-aware forward-paper gates.

- Deployed paper-only forward evidence collection with performance checks, loss
  attribution, guarded calibration, and adaptive paper guards.

- Added live auto-hot dry-run proof while keeping unattended live auto-hot and
  live service/timer disabled.

**Known deferred items at close:**

- Live automation remains inactive until all-interval strategy promotion and
  forward-paper performance evidence improve.

- `30u_10x_multi_dynamic` remains preview/confirmation-gated and was not
  applied.

- The adaptive paper guard reduces repeated losing samples but does not prove
  profitability.

---

## v1.21 Live Pilot Risk Controls (Shipped: 2026-06-20)

**Phases completed:** 21 phases, 21 plans, 0 tasks

**Archived artifacts:**

- `.planning/milestones/v1.21-ROADMAP.md`
- `.planning/milestones/v1.21-REQUIREMENTS.md`
- `.planning/milestones/v1.21-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Activated and monitored the live small-capital Binance USD-M pilot with
  protective-order evidence and AI timeout/backoff behavior.

- Added short-window backtesting, tradability filtering, and a controlled
  hot-coin symbol universe for small notional caps.

- Hardened live execution around margin mode, hedge position side, entry-order
  failures, and account-balance preflight checks.

- Switched live AI decisions to DeepSeek while preserving strict JSON schema
  validation and deterministic risk gates.

- Reconciled closed live trade outcomes from Binance fills and added sweep
  tooling for submitted live intents.

- Added resume, hold-time, time-exit, risk-change, dynamic sizing, and
  confirmation-gated profile switch controls.

**Known deferred items at close:**

- HYPEUSDT remains open and protected; the 8x/dynamic profile apply must wait
  until the position closes, closed outcome evidence is persisted, and
  `risk-change-check --target-leverage 8` returns allowed.

---

## v1.0 Dry-Run Binance Futures Agent (Shipped: 2026-06-19)

**Phases completed:** 8 phases, 28 plans

**Archived artifacts:**

- `.planning/milestones/v1.0-ROADMAP.md`
- `.planning/milestones/v1.0-REQUIREMENTS.md`
- `.planning/milestones/v1.0-MILESTONE-AUDIT.md`

**Key accomplishments:**

- Created an isolated Python project at `F:\binance_futures_agent` without
  coupling to the existing stock repository.

- Built Binance USD-M public market-data collectors, symbol filters, and
  normalized snapshot persistence.

- Added manual/export and RSS-style narrative ingestion for hot-coin signals.
- Implemented a SQLite event store, deterministic replay packets, and review
  metrics foundations.

- Added hot-coin candidate scoring, OpenAI structured decision validation, and
  secret-safe AI journaling.

- Built risk-gated dry-run/live execution helpers, server deployment assets, and
  isolated health checks under `/opt/binance-futures-agent`.

**Known deferred items at close:**

- Server OpenAI live health remains skipped until `OPENAI_API_KEY` is configured
  out of band.

- Live automated trading activation is tracked in v1.1 and remains disabled
  until the operator approves one-cycle live validation.

---
