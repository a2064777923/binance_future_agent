---
phase: 68
name: Multi-Factor Edge And Point Precision
status: context
created: 2026-06-21
requirements:
  - EDGE-01
  - EDGE-02
  - EDGE-03
  - EDGE-04
---

# Phase 68: Multi-Factor Edge And Point Precision - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous GSD discuss (`--auto` decisions captured inline).

<domain>
## Phase Boundary

Phase 68 upgrades deterministic trade setup quality before the AI overlay. The
runner should no longer look like it only combines hot-symbol rank with an AI
yes/no. It should build an auditable multi-factor proposal containing trend,
momentum, volume impulse, taker flow, open-interest, funding, volatility,
liquidity, tradability, entry, stop, target, and no-trade reasons before any AI
decision is requested.

This phase is local strategy, trace, and test work. It must not deploy to the
server, mutate `/etc/binance-futures-agent/env`, raise leverage, increase
position caps, place extra orders, or manage manual symbols. Adaptive sizing
and high-leverage governors remain Phase 69. Server canary verification remains
Phase 70.

</domain>

<decisions>
## Implementation Decisions

### Multi-Factor Edge Model
- **D-01:** Deterministic setup scoring should remain the first authority. AI
  may review or veto a well-formed setup, but it must not invent missing factor
  evidence or bypass deterministic setup, sizing, exchange-filter, or risk
  gates.
- **D-02:** The factor model should explicitly expose contributions for
  trend/momentum, volume impulse, taker flow, open-interest change/value,
  funding, volatility/range, liquidity, tradability, and narrative heat. Missing
  data should reduce confidence or add warnings rather than silently disappear.
- **D-03:** Factor output should include directional polarity, weighted score,
  reasons, raw value, and a compact summary suitable for `candidate_evaluations`,
  trade setup persistence, AI context, and live-cycle explainability.
- **D-04:** The default setup profile may be tightened only as a risk-reducing
  no-trade filter. Phase 68 must not increase size, leverage, concurrency, or
  risk caps.

### Entry, Stop, Target, And Geometry
- **D-05:** Entry, stop, and target should be derived from market structure
  rather than fixed intuition: reference price, recent support/resistance, VWAP,
  ATR/realized volatility, close-position-in-range, and exchange filters should
  all be considered where available.
- **D-06:** The setup payload should include a `price_basis` or equivalent
  diagnostics block with anchors, raw distances, capped distances, risk/reward,
  stop risk, min executable notional, exchange quantization pressure, and any
  missing inputs.
- **D-07:** Liquidation-distance diagnostics should be estimated for the active
  configured leverage where possible, but Phase 68 should report/block weak
  geometry conservatively rather than trying to optimize high leverage. The
  broader leverage governor belongs to Phase 69.
- **D-08:** Small notional decisions must be explainable through stop distance,
  risk cap, min-notional pressure, profile fraction, and configured max
  position notional; do not hide this behind a final notional number.

### Trade/No-Trade Trace
- **D-09:** Every candidate evaluation should expose why it traded or passed:
  factor threshold failures, profile blocks, missing feature coverage, point
  geometry failures, min-notional pressure, guard factor blocks, and AI pass
  reasons.
- **D-10:** Existing Phase 66/67 explainability surfaces should be reused.
  Prefer enriching `TradeSetup.to_dict()`, AI context compact setup, persisted
  trade setup payloads, `candidate_evaluations`, and ops reports over creating
  a separate parallel trace system.
- **D-11:** The final result should stay operator-readable and secret-safe. It
  can include factor values, scores, source counts, exchange filters, and
  sizing/geometry diagnostics, but must not include API keys, tokens, raw
  credentials, or server passwords.

### Outcome-Driven Guard Feedback
- **D-12:** Live/paper outcome feedback remains recommendation-only unless an
  existing guard path already consumes it as risk-reducing suppression. Phase
  68 may improve the quality of factor guard evidence, but it must not
  automatically promote risk.
- **D-13:** Guard feedback should account for minimum sample counts, recency, and
  decay when ranking weak factor patterns. Recent repeated losses should matter
  more than stale isolated losses, but insufficient samples should remain
  advisory.
- **D-14:** Outcome grouping should continue to distinguish symbol, side, setup
  reason, factor reason/name, exit reason, and hold bucket so weak patterns can
  suppress or warn at the narrowest useful level.

### Manual Boundary And Runtime Caps
- **D-15:** `BTWUSDT` and all `BFA_MANUAL_POSITION_SYMBOLS` remain operator-owned.
  They may appear in lifecycle/manual diagnostics, but Phase 68 must not add any
  path that lets setup scoring, traces, guard feedback, or exits manage them as
  bot positions.
- **D-16:** Runtime caps must be read from config and from current risk-state
  inputs. Do not hard-code the manually widened server caps into local code or
  tests.

### the agent's Discretion
- The implementation may add small dataclasses/helpers for setup diagnostics,
  point geometry, liquidation-distance approximation, or recency-weighted guard
  summaries when that keeps `setup.py` and ops reports readable.
- Tests should focus on behavior and payload shape rather than exact private
  strategy weights, unless a threshold directly enforces a requirement.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning And Prior Decisions
- `.planning/ROADMAP.md` - Phase 68 goal and success criteria.
- `.planning/REQUIREMENTS.md` - EDGE-01 through EDGE-04 and v1.27 boundaries.
- `.planning/PROJECT.md` - project isolation, live-pilot intent, public Lana
  claims policy, and evidence-first promotion decisions.
- `.planning/STATE.md` - current phase, active live/manual-symbol boundaries,
  and latest operational state.
- `.planning/phases/67-adaptive-hot-symbol-breadth-and-guarded-queue/67-CONTEXT.md`
  - broad scan, source-health, candidate queue, and manual-boundary decisions.
- `.planning/phases/66-live-cycle-explainability-and-ledger-cadence/66-CONTEXT.md`
  - explainability and non-mutation requirements.
- `.planning/phases/65-server-canary-and-pilot-learning-packet/65-CONTEXT.md`
  - server isolation and manual `BTWUSDT` packet treatment.

### Strategy And Feature Code
- `src/bfa/strategy/setup.py` - deterministic factor scoring, setup profiles,
  entry/stop/target generation, price basis, and persisted setup payloads.
- `src/bfa/strategy/features.py` - extracted symbol features from narratives,
  market snapshots, indicators, and exchange filters.
- `src/bfa/strategy/indicators.py` - support/resistance, VWAP, ATR,
  volatility, EMA, RSI, and kline-derived indicator snapshot logic.
- `src/bfa/strategy/candidates.py` - candidate ranking, rejection reasons,
  tradability cap filtering, and paper-guard symbol blocks.
- `src/bfa/strategy/paper_guard.py` - weak-evidence symbol/side/factor guard
  construction and setup-profile overrides.
- `src/bfa/agent.py` - live runner, candidate queue, `candidate_evaluations`,
  source-health output, risk-state handling, and manual-symbol exclusion.
- `src/bfa/ai/schema.py` - compact candidate/setup context sent to the AI
  overlay and validation fields.

### Ops, Ledger, And Tests
- `src/bfa/ops/live_cycle_explainability.py` - recent cycle grouping and
  operator-facing trade/no-trade report shape.
- `src/bfa/ops/trade_trace.py` - submitted trade trace reconstruction and setup
  factor/price-basis output.
- `src/bfa/ops/live_outcome_ledger.py` - live outcome grouping and
  recommendation-only guard feedback.
- `src/bfa/backtest/engine.py` and `src/bfa/backtest/models.py` - strategy
  variant/backtest use of `build_trade_setup()`.
- `tests/test_strategy_setup.py` - setup factor/point behavior patterns.
- `tests/test_strategy_features.py` and `tests/test_strategy_indicators.py` -
  feature and indicator extraction coverage.
- `tests/test_agent_runner.py` - live queue and candidate diagnostics coverage.
- `tests/test_ops_live_cycle_explainability.py`,
  `tests/test_ops_live_outcome_ledger.py`, and `tests/test_ops_pilot_learning_packet.py`
  - operator report and guard feedback test patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TradeSetup`, `FactorScore`, and `TradeSetupProfile` already provide a compact
  setup model with factor scores, directional scores, risk/reward, point
  distances, `price_basis`, profile blocks, and warnings.
- `SymbolFeatures` already carries public-market and structure inputs:
  momentum, taker flow, funding, open interest, quote volume, kline volume
  impulse, support/resistance, VWAP, ATR, EMA spread, RSI, reference price, and
  min executable notional.
- `compute_indicator_snapshot()` already produces indicator data from kline
  points; Phase 68 should reuse it instead of inventing a separate indicator
  stack.
- `candidate_evaluations` from Phase 67 is the right place to surface
  per-candidate setup/AI/risk path diagnostics.
- `live_outcome_ledger` already groups losses by symbol, side, setup reason,
  factor reason/name, exit reason, and hold bucket; it can be enriched with
  recency/decay summaries.

### Established Patterns
- Deterministic setup precedes AI. AI context includes compact candidate and
  quant setup data; AI validation checks geometry and risk limits.
- Guard feedback is recommendation-only or risk-reducing. It cannot raise risk
  without explicit operator approval.
- Manual symbols are excluded from bot action while remaining visible in
  lifecycle diagnostics.
- Tests assert JSON payload shapes for operator-facing outputs.

### Integration Points
- Enrich `src/bfa/strategy/setup.py` first; downstream AI context,
  `candidate_evaluations`, trade traces, and reports already consume
  `setup.to_dict()`.
- Update `src/bfa/ai/schema.py` only if compact AI context needs new safe
  diagnostic fields.
- Update ops reports only where existing output omits new setup diagnostics.
- Extend tests in strategy, agent runner, and ops report suites before or with
  behavior changes.

</code_context>

<specifics>
## Specific Ideas

- The operator wants a mature quant system, not a thin hotness rank plus AI
  approval. Make deterministic setup evidence rich enough that an opened or
  skipped trade can be explained without trusting model prose.
- Public Lana/Square/X claims remain inspiration only. Phase 68 should not
  claim copied profitability; it should improve local evidence quality and
  traceability.
- Use current config/risk limits for all sizing and geometry. Do not encode the
  server's temporarily widened live caps as defaults.

</specifics>

<deferred>
## Deferred Ideas

- Adaptive position sizing increases, high-leverage liquidation governors, and
  dynamic cap raises belong to Phase 69.
- Server deployment and live canary evidence belong to Phase 70.
- New external social/news adapters belong to v1.28+ unless an existing source
  is simply being summarized.

</deferred>

---

*Phase: 68-Multi-Factor Edge And Point Precision*
*Context gathered: 2026-06-21*
