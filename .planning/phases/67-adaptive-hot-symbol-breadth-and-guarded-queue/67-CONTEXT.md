---
phase: 67
name: Adaptive Hot-Symbol Breadth And Guarded Queue
status: context
created: 2026-06-21
requirements:
  - SCAN-01
  - SCAN-02
  - SCAN-03
  - SCAN-04
---

# Phase 67: Adaptive Hot-Symbol Breadth And Guarded Queue - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous GSD discuss fallback (`--auto` decisions captured inline).

<domain>
## Phase Boundary

Phase 67 broadens the live candidate observation surface and improves queue
behavior before deeper setup-point work. The live runner should be able to
observe at least 80 current Binance USD-M USDT symbols when auto-hot selection
is enabled, report which public and narrative sources were available for that
cycle, avoid repeating symbols/sides/factor patterns with weak recent evidence,
and keep trying later candidates after retryable skips.

This phase is local strategy/runner/reporting work. It must not deploy to the
server, apply risk profiles, raise leverage, place extra live orders outside the
existing one-order-per-cycle default, or manage manual positions. Server canary
and manual-boundary verification remain Phase 70.

</domain>

<decisions>
## Implementation Decisions

### Hot-Symbol Breadth
- **D-01:** Default live auto-hot scanning should support at least 80 Binance
  USD-M USDT symbols, still controlled by `BFA_LIVE_AUTO_HOT_TOP_N` and
  existing volume/change filters.
- **D-02:** The broader universe must still exclude configured manual symbols
  before market collection, candidate generation, AI decisions, and execution.
- **D-03:** Broader observation is not a risk increase by itself. It only
  creates more candidates for the existing deterministic gates and one-order
  submission limit.

### Source Health
- **D-04:** Live cycle output should include candidate source health for
  Binance 24h ticker selection, collected klines, open interest,
  open-interest history, funding, taker buy/sell flow, manual Square exports,
  RSS feeds, and market-heat fallback records where available.
- **D-05:** Source health should report counts/status and configured inputs
  without leaking secrets or dumping credentials. Missing optional narrative
  sources should be visible as `not_configured` or equivalent, not treated as a
  runtime failure.
- **D-06:** Reuse the source-health shape already used by forward-paper symbol
  selection where possible so operator packets and tests stay consistent.

### Weak-Evidence Guard
- **D-07:** Existing forward-paper guard behavior remains risk-reducing only:
  it may block symbols, sides, or factor reasons from candidate/setup paths, but
  it must not raise size, leverage, or allowed concurrency.
- **D-08:** Guard diagnostics should explain whether a candidate was suppressed
  by symbol block, side block, or factor block, and should include enough guard
  summary counts to show whether the evidence is active or insufficient.
- **D-09:** Operator reset/override is out of scope for automatic risk
  increases. Phase 67 may expose the guard state and respect existing config
  thresholds, but promotion remains evidence-gated.

### Guarded Candidate Queue
- **D-10:** The live runner should continue evaluating later candidates after
  retryable setup, AI, exchange-filter, and symbol-level risk skips. Retryable
  skips include AI pass, quant/setup pass, duplicate same-symbol-direction
  exposure, missing filters, min-notional/quantity filter failures, and guarded
  symbol/factor suppression.
- **D-11:** The default live cycle still submits at most one order. A submitted
  or non-retryable rejected candidate ends the cycle as today.
- **D-12:** The final run result and persisted traces should show both the
  selected/final symbol and the full evaluated-symbol path, so Phase 66
  explainability can describe why earlier symbols were skipped.

### Manual Boundary
- **D-13:** `BTWUSDT` and any `BFA_MANUAL_POSITION_SYMBOLS` entries remain
  operator-owned. They should be visible in lifecycle diagnostics but excluded
  from bot-managed entry capacity, auto-management, close/reduce execution, and
  broadened candidate selection.
- **D-14:** The current server env may be wider than committed defaults because
  the operator requested live capacity adjustments while iteration continued.
  Planning should treat runtime caps as configuration readback, not hard-coded
  constants.

### The agent's Discretion
- The implementation may introduce small helper dataclasses/functions for live
  source-health reporting if reusing CLI-only helpers would create circular
  imports.
- Tests should focus on behavior: 80-symbol scan support, manual-symbol
  exclusion, source-health payloads, retryable queue continuation, and guard
  skip traceability.

</decisions>

<canonical_refs>
## Canonical References

Downstream agents MUST read these before planning or implementing.

### Planning
- `.planning/ROADMAP.md` - Phase 67 goal and success criteria.
- `.planning/REQUIREMENTS.md` - SCAN-01 through SCAN-04 and v1.27 boundaries.
- `.planning/PROJECT.md` - project isolation, live-pilot intent, Lana/public
  claims policy, and evidence-first promotion decisions.
- `.planning/STATE.md` - latest live/server/manual-symbol operational state.
- `.planning/phases/66-live-cycle-explainability-and-ledger-cadence/66-CONTEXT.md`
  - explainability-first boundary and non-mutation constraints.
- `.planning/phases/65-server-canary-and-pilot-learning-packet/65-CONTEXT.md`
  - server canary boundary and manual `BTWUSDT` packet treatment.
- `.planning/phases/64-live-outcome-ledger-and-guard-feedback/64-CONTEXT.md`
  - recommendation-only guard feedback boundary.

### Code
- `src/bfa/agent.py` - live runner, auto-hot symbol scan, candidate queue,
  position lifecycle, manual-symbol exclusion, and result payload.
- `src/bfa/strategy/candidates.py` - deterministic candidate scoring,
  rejection reasons, tradability cap filtering, and paper-guard symbol blocks.
- `src/bfa/strategy/paper_guard.py` - weak-evidence symbol/side/factor guard
  construction and setup-profile overrides.
- `src/bfa/backtest/matrix.py` - `HotUniverseConfig` and
  `select_hot_usdt_symbols()` ranking/filtering.
- `src/bfa/cli.py` - forward-paper source-health shape and ops command output
  patterns.
- `src/bfa/market/collector.py` - market snapshot collection for klines,
  funding, open interest, open-interest history, and taker flow.
- `src/bfa/strategy/features.py` - extraction of source/factor inputs from
  replay packets.
- `src/bfa/strategy/setup.py` - quant setup decisions, factor blocks, side
  blocks, and trade/no-trade reasons.
- `tests/test_agent_runner.py` - live runner coverage for auto-hot, manual
  symbols, paper guard, and queue behavior.
- `tests/test_ops_forward_paper.py` - source-health and guard-reporting
  examples.
- `tests/test_strategy_candidates.py` and `tests/test_strategy_paper_guard.py`
  - candidate and guard unit-test patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `select_hot_usdt_symbols()` already ranks Binance USD-M USDT rows by
  configured top-N, quote volume, and absolute price change while excluding
  stable bases.
- `_agent_scan_symbols()` already supports `BFA_LIVE_AUTO_HOT_SYMBOLS`,
  `BFA_LIVE_AUTO_HOT_TOP_N`, quote-volume/change floors, fallback symbols, and
  manual-symbol exclusion.
- `_evaluate_candidate_queue()` already loops through candidates, records
  `evaluated_symbols`, persists setup/AI evidence, and continues after selected
  retryable risk reasons.
- `build_forward_paper_guard()` already produces active/insufficient guard
  summaries and symbol/side/factor blocks from stored paper evidence.
- `_forward_paper_source_health()` already has a source-health payload shape
  for symbol selection and narrative-source configuration.

### Established Patterns
- Runner results are dataclasses with `to_dict()` payloads, and tests assert the
  exact operator-visible JSON fields.
- Candidate generation remains deterministic and precedes AI. AI may approve or
  pass, but deterministic setup/risk/execution gates retain final authority.
- Manual-symbol handling is hard exclusion for bot actions while remaining
  visible in diagnostics.
- Guards and feedback may reduce risk or suppress weak candidates, but local
  evidence and explicit operator approval are required before any risk increase.

### Integration Points
- Add live source-health data near `_agent_scan_symbols()`, market collection,
  narrative collection, and candidate generation in `src/bfa/agent.py`.
- Extend `AgentRunResult` so the live cycle output includes source health and
  guarded skip evidence in no-candidate, ai-pass, quant-pass, rejected, and
  submitted paths.
- Extend `_should_try_next_candidate()` or nearby queue logic so retryable setup
  and guard reasons continue to later candidates without relaxing non-retryable
  risk blocks.
- Reuse `StrategyConfig.paper_guard`, `merge_guard_profile()`, and setup
  rejection reasons rather than creating a separate guard system.

</code_context>

<specifics>
## Specific Ideas

- The operator wants the system to stop feeling like it only checks a tiny hot
  list and asks AI. Phase 67 should make the breadth and source evidence visible
  enough that the next live-cycle explanation can show what was scanned and why
  later candidates were or were not reached.
- The currently deployed server env was manually widened after Phase 66:
  `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT`, multi-position enabled, live timers
  active, and wider capacity values confirmed by config readback. Do not bake
  those numbers into code; read config at runtime.
- Keep public Lana/Square/X claims as inspiration only. This phase improves
  observation and guards; it does not claim a profitable copied strategy.

</specifics>

<deferred>
## Deferred Ideas

- Full multi-factor edge scoring and entry/stop/target point precision belong
  to Phase 68.
- Adaptive sizing and high-leverage governors belong to Phase 69.
- Server deployment, timer canary, sensitive-artifact scan, and final manual
  boundary proof belong to Phase 70.
- Full external social/news adapter expansion belongs to v1.28+ unless an
  already available manual/RSS source is being reported.

</deferred>

---

*Phase: 67-Adaptive Hot-Symbol Breadth And Guarded Queue*
*Context gathered: 2026-06-21*
