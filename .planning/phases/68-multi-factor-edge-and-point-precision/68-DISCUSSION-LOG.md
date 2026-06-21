---
phase: 68
name: Multi-Factor Edge And Point Precision
status: discussion-log
created: 2026-06-21
mode: auto
---

# Phase 68: Multi-Factor Edge And Point Precision - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 68-multi-factor-edge-and-point-precision
**Areas discussed:** Multi-factor edge model, Entry/stop/target geometry, Trade/no-trade trace, Outcome guard feedback, Manual boundary and runtime caps

---

## Multi-Factor Edge Model

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic setup first | Expand quant setup factors before AI; AI reviews a proposal but cannot invent missing evidence. | x |
| AI-led interpretation | Let the model infer the factor weighting from raw context. | |
| Backtest-only factor tuning | Defer richer live setup payloads and tune only matrix variants. | |

**User's choice:** Auto-selected deterministic setup first.
**Notes:** Matches the operator's concern that previous logic looked too thin.

---

## Entry/Stop/Target Geometry

| Option | Description | Selected |
|--------|-------------|----------|
| Structure-aware geometry | Use support/resistance, VWAP, ATR, volatility, exchange filters, and min-notional pressure. | x |
| Simple percentage offsets | Keep fixed stop/target distances around reference price. | |
| AI-generated points | Ask the AI to provide entry/stop/target without deterministic geometry. | |

**User's choice:** Auto-selected structure-aware geometry.
**Notes:** Phase 68 should report liquidation-distance diagnostics conservatively but leave high-leverage governors to Phase 69.

---

## Trade/No-Trade Trace

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing setup/report payloads | Enrich `TradeSetup.to_dict()`, AI context, `candidate_evaluations`, and ops reports. | x |
| Add a separate trace table | Persist a new trace model independent of current setup/candidate artifacts. | |
| CLI-only explanation | Keep runner payloads thin and explain only through a later command. | |

**User's choice:** Auto-selected reuse existing setup/report payloads.
**Notes:** Reduces parallel systems and keeps Phase 66/67 explainability surfaces coherent.

---

## Outcome Guard Feedback

| Option | Description | Selected |
|--------|-------------|----------|
| Recommendation-only recency/decay | Improve weak-factor feedback with sample counts, recency, and decay without raising risk. | x |
| Immediate guard application | Automatically apply new factor blocks from live outcomes. | |
| Ignore live outcomes here | Leave all outcome learning to a later phase. | |

**User's choice:** Auto-selected recommendation-only recency/decay.
**Notes:** Preserves the evidence-gated promotion policy.

---

## Manual Boundary And Runtime Caps

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve manual boundary | Keep `BTWUSDT` visible only in manual diagnostics and read caps from config. | x |
| Treat manual exposure as strategy evidence | Fold manual symbols into factor/guard learning automatically. | |
| Hard-code widened caps | Bake the current server trial values into defaults. | |

**User's choice:** Auto-selected preserve manual boundary.
**Notes:** Maintains prior decisions from Phases 65-67.

## the agent's Discretion

- Planner/executor may introduce small helper dataclasses or functions for setup diagnostics, point geometry, liquidation-distance approximation, and recency-weighted guard summaries.
- Exact factor weights can be adjusted conservatively if tests verify the operator-visible reasons and risk-reducing behavior.

## Deferred Ideas

- Adaptive sizing, higher leverage, and cap raises remain Phase 69.
- Server deployment and manual-boundary canary remain Phase 70.
