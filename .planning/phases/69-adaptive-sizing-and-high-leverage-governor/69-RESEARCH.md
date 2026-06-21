---
phase: 69
name: Adaptive Sizing And High-Leverage Governor
status: researched
created: 2026-06-21
---

# Phase 69 Research

## Findings

- Binance USD-M leverage is symbol-level and adjusted with `POST /fapi/v1/leverage`.
  The local executor already sets initial leverage before live entries.
- Binance notional/leverage brackets are available from `GET /fapi/v1/leverageBracket`.
  This phase does not need bracket-specific live mutation; it should keep using
  configured caps and exchange filters.
- Position risk data comes from `GET /fapi/v3/positionRisk`; existing code reads
  it and can classify manual symbols before risk-state construction.
- Binance order-status uncertainty means live execution should not duplicate
  orders after ambiguous failures. This phase is pre-order sizing/risk only and
  should not alter order submission semantics.

## Code Approach

- Add a deterministic adaptive sizing governor after setup generation and before
  AI context creation.
- Extend `RiskState` with manual exposures and optional available balance.
- Add risk checks that include manual initial margin and available balance
  pressure without incrementing bot-managed `active_positions`.
- Add exposure-status fields so operators can see manual margin pressure and the
  effective dynamic notional cap.
- Preserve existing defaults and hard caps; no live server deploy in this phase.
