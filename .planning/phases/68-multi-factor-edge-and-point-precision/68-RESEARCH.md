---
phase: 68
name: Multi-Factor Edge And Point Precision
status: research
created: 2026-06-21
mode: inline-fallback
requirements:
  - EDGE-01
  - EDGE-02
  - EDGE-03
  - EDGE-04
---

# Phase 68 Research: Multi-Factor Edge And Point Precision

## Research Mode

Automatic typed GSD subagent dispatch is unavailable in this Codex session
without explicit subagent authorization, so this research was performed inline
against the canonical files listed in `68-CONTEXT.md`. This is a fallback from
the full `gsd-phase-researcher` split, but it preserves the same artifact and
gate intent.

## Existing Assets

- `src/bfa/strategy/setup.py` already has a deterministic `TradeSetup` model,
  factor scores, profile rejections, setup reasons, entry/stop/target geometry,
  notional sizing, and `price_basis` persistence.
- `src/bfa/strategy/features.py` already extracts public-market and structure
  inputs from narrative and market snapshots: ticker momentum/liquidity,
  klines, support/resistance, VWAP, ATR, realized volatility, EMA spread, RSI,
  taker flow, funding, open interest, exchange filters, and min executable
  notional.
- `src/bfa/strategy/indicators.py` already provides the kline-derived market
  structure layer. Phase 68 should reuse it rather than adding a second
  indicator engine.
- `src/bfa/agent.py` already records `candidate_evaluations`, persists
  `trade_setups`, keeps deterministic setup before AI, and excludes configured
  manual symbols before candidate/execution flow.
- `src/bfa/ai/schema.py`, `src/bfa/ops/live_cycle_explainability.py`, and
  `src/bfa/ops/trade_trace.py` already consume `TradeSetup.to_dict()`, making
  setup payload enrichment the lowest-blast-radius integration point.
- `src/bfa/ops/live_outcome_ledger.py` and
  `src/bfa/strategy/paper_guard.py` already group negative evidence by symbol,
  side, setup reason, factor name/reason, exit reason, and holding bucket, but
  recency and decay are not explicit enough for Phase 68's guard-feedback
  requirement.

## Gaps To Close

- Factor output is present but not operator-shaped as a factor model. It lacks
  compact factor groups, missing-input coverage, threshold diagnostics, and
  side-specific contribution summaries that make it obvious why long or short
  won before AI.
- Open interest uses current notional/value but does not expose change or
  impulse when multiple OI snapshots are present. This weakens EDGE-01 and
  should be fixed in feature extraction and scoring.
- `price_basis` has anchors and some raw distances, but it does not yet explain
  raw versus capped distances, stop risk, risk/reward, min-notional pressure,
  leverage/liquidation buffer, exchange-filter pressure, and sizing-cap reasons
  in one stable diagnostics block.
- No-trade traces can show final setup reasons, but candidate diagnostics and
  ops reports should surface factor threshold failures and point-geometry
  blockers without forcing the operator to reconstruct them from raw factors.
- Guard feedback is recommendation-only, which is correct, but it needs explicit
  minimum-sample, recency, and decay annotations so repeated recent losses are
  ranked ahead of stale weak groups while insufficient samples stay advisory.

## Recommended Implementation Path

1. Enrich `FactorScore` and setup aggregation rather than replacing existing
   setup logic. Add compact factor summaries, groups, missing-input coverage,
   and factor threshold diagnostics to `TradeSetup.to_dict()`.
2. Add OI change extraction in `features.py` by comparing consecutive
   open-interest or open-interest-history snapshots where available, and expose
   it in AI compact candidate context.
3. Add structured geometry/sizing diagnostics to `price_basis`, including
   exchange filters, min executable notional, stop-risk notional, risk cap,
   max-position cap, profile fraction, raw/capped distances, risk/reward, and
   approximate liquidation-distance information from configured max leverage.
4. Reuse existing downstream payload consumers. Update AI context, live-cycle
   explainability, and trade trace only where compact fields are omitted or
   difficult to inspect.
5. Keep Phase 68 risk-reducing only. Do not raise leverage, notional caps,
   concurrency, live env settings, or server state. Phase 69 owns adaptive
   sizing and high-leverage governors; Phase 70 owns deployment.
6. Add focused tests around factor payload shape, OI change extraction, geometry
   diagnostics, candidate evaluation trace content, AI compact context, and
   recency/decay guard feedback.

## Non-Goals

- No server deployment, live env mutation, systemd changes, order placement, or
  exchange mutation.
- No hard-coding of the operator-widened live caps into local defaults.
- No auto-promotion of risk from paper/live outcomes.
- No management of `BTWUSDT` or any `BFA_MANUAL_POSITION_SYMBOLS`.
