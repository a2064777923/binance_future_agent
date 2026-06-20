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

## Cross-Milestone Trends

| Trend | Evidence | Next Action |
|-------|----------|-------------|
| Safety gates are moving from docs into code | Protective orders, kill switch, AI timeout, resume/risk-change/time-exit gates | Keep new live actions behind read-only preview plus confirmation |
| External credentials are configured out of band | Binance and AI credentials are present on the server without being committed | Continue treating env files and keys as non-repo secrets |
| Risk increases require evidence, not enthusiasm | HYPEUSDT blocks the 8x/dynamic profile until closed and reconciled | Reconcile HYPEUSDT after close, then rerun `risk-change-check --target-leverage 8` |
| Tiny-account futures constraints shape the product | Binance filters, notional-vs-margin, spread, and fees drive sizing | Keep tradability filters and staged backtests before further scaling |
