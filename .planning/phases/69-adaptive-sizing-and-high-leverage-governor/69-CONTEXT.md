---
phase: 69
name: Adaptive Sizing And High-Leverage Governor
status: context
created: 2026-06-21
---

# Phase 69 Context

<domain>
This phase turns the Phase 68 multi-factor setup diagnostics into an execution
sizing governor. It decides how much of the configured absolute capacity a
candidate may use, and when high-leverage conditions should downsize or block a
setup before AI or live execution can submit an order.
</domain>

<decisions>

## D-01 Adaptive Sizing Contract
- Dynamic sizing may raise or lower contract notional only inside existing hard
  caps: per-position notional, effective notional, stop-risk, leverage, available
  balance, portfolio margin, portfolio notional, and same-direction notional.
- Signal quality comes from the deterministic setup: edge score, confidence,
  factor coverage, group totals, liquidity, open interest, taker flow,
  volatility, and exchange min-notional pressure.
- The governor must emit diagnostics explaining base cap, multipliers, floors,
  final notional, and all downsize/block reasons.

## D-02 High-Leverage Safety
- At high leverage, a setup is not accepted solely because notional fits.
  Liquidation distance, stop distance, volatility/range, liquidity, and slippage
  proxies must stay within configured floors.
- Unsafe high-leverage setups should be blocked when geometry is structurally
  bad; softer concerns should downsize the final notional.

## D-03 Manual Position Boundary
- `BTWUSDT` and configured manual symbols remain visible in diagnostics but are
  not bot-managed positions, not exit candidates, and not counted against
  bot-managed position slots.
- Manual-position margin is still risk pressure. Portfolio and account checks
  must include manual initial margin and available balance so manual exposure can
  constrain new bot entries without being managed by the bot.

## D-04 Evidence And Risk Increase Gate
- Guard/outcome feedback may only reduce or block risk automatically.
- Any capacity increase needs preview evidence and a rollback path. This phase
  can implement local preview/reporting and diagnostics, but live deployment and
  server canary remain Phase 70.

</decisions>

<code_context>
- `src/bfa/execution/sizing.py` owns dynamic sizing inputs/results and is the
  right home for an additive adaptive governor.
- `src/bfa/execution/risk.py` owns deterministic risk acceptance and should
  include manual-margin and available-balance pressure.
- `src/bfa/agent.py` builds a `TradeSetup` before AI; this is the right point to
  apply the governor so AI must echo the final deterministic plan.
- `src/bfa/strategy/setup.py` already exposes `factor_summary`, `price_basis`,
  `sizing_diagnostics`, and `liquidation_diagnostics`.
- `src/bfa/ops/exposure_status.py` already separates manual exposure from active
  bot exposure and can expose new pressure fields.
</code_context>

<canonical_refs>
- `.planning/ROADMAP.md` Phase 69 section
- `.planning/REQUIREMENTS.md` SIZE-01, SIZE-02, SIZE-03, SIZE-04
- `src/bfa/execution/sizing.py`
- `src/bfa/execution/risk.py`
- `src/bfa/agent.py`
- `src/bfa/strategy/setup.py`
- `src/bfa/ops/exposure_status.py`
</canonical_refs>

<out_of_scope>
- Deploying new code or changing server systemd state; Phase 70 owns server
  canary and manual-boundary verification.
- Letting AI override deterministic sizing, stops, targets, or risk gates.
- Automatically managing manual `BTWUSDT` or any other configured manual symbol.
</out_of_scope>
