# Phase 58: Promotion Matrix And Loss Review - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD; `gsd-tools` roadmap discovery was stale, so
`.planning/ROADMAP.md` and `.planning/STATE.md` are the authoritative phase
sources for this context.

<domain>
## Phase Boundary

Phase 58 re-checks strategy promotion evidence and reviews manual loss
incidents against deterministic rules. It does not authorize live scaling by
itself, and it does not mutate Binance, systemd, server env, or open
positions. The deliverable is auditable evidence: current matrix/promotion
classification, manual loss guard comparison, and an explicit boundary that
public Lana/Square/X claims are design inspiration only.

</domain>

<decisions>
## Implementation Decisions

### Evidence Classification
- Promotion reports must distinguish at least three operator states:
  collect more paper evidence, forward-paper candidate, and live-resume
  eligible evidence. Existing status fields may remain backward-compatible, but
  the new stage must be explicit.
- Current-data matrix execution remains a CLI/report workflow using completed
  candles, next-candle entries, fees, slippage, and small-account caps already
  implemented in the backtest engine.

### Manual Loss Review
- Manual loss incidents recorded by Phase 56 remain append-only evidence.
- The review must be read-only and compare each incident against current
  deterministic risk rules: max leverage, missing/unreliable stop-loss,
  liquidation proximity, and adaptive paper-guard symbol/side blocks where
  evidence exists.
- The report should clearly say whether a manual incident would have been
  blocked, warned/reduced, or not caught by the current deterministic rules.

### Public Claims Boundary
- Lana/Square/X public claims may influence factor ideas and data-source
  selection, but they cannot count as promotion proof or unlock live risk.
- Promotion proof must come from local backtest matrix, forward-paper outcomes,
  exchange evidence, and reconciled live outcomes.

### the agent's Discretion
- Choose compact JSON field names and tests consistent with existing ops
  reports.
- Add only focused implementation needed for Phase 58; leave live resume
  mutation paths to Phase 59.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bfa/backtest/matrix.py` already runs hot-universe matrix and suite
  reports.
- `src/bfa/ops/strategy_promotion.py` already validates matrix reports and
  supports all-intervals vs selected-intervals promotion checks.
- `src/bfa/ops/manual_loss.py` records secret-safe manual loss incidents in
  the `risk_state` category with event type `manual_loss_incident`.
- `src/bfa/strategy/paper_guard.py` already derives symbol, side, and factor
  blocks from forward-paper outcomes.

### Established Patterns
- Ops reports are dataclasses with `to_dict()` and are exposed through
  `python -m bfa.cli ops ...`.
- Read-only review commands return JSON and avoid signed exchange mutations.
- Tests cover both direct report builders and CLI routes.

### Integration Points
- Add manual loss review under `src/bfa/ops/` and route it from `src/bfa/cli.py`.
- Extend `StrategyPromotionCheckReport` with explicit stage/evidence-boundary
  fields while preserving existing status behavior for compatibility.
- Add focused unit tests plus CLI coverage.

</code_context>

<specifics>
## Specific Ideas

The immediate live pilot is already active by operator override, but this phase
still treats promotion evidence conservatively. Current live capacity and
manual-held `BTWUSDT` are operational context, not proof of strategy quality.

</specifics>

<deferred>
## Deferred Ideas

- Confirmation-gated live resume mutation path belongs to Phase 59.
- Server evidence packet and final v1.25 resume packet belong to Phase 60.

</deferred>
