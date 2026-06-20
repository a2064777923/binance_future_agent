# Phase 59: Confirmation-Gated Live Resume Path - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD; current `.planning/ROADMAP.md` and
`.planning/STATE.md` are authoritative.

<domain>
## Phase Boundary

Phase 59 builds the explicit mutation path for live resume/profile/timer
changes, but keeps it locked behind existing readiness and operator-decision
evidence. It must let the operator preview the exact action plan, confirmation
token, risk-profile target, timer/service changes, and non-mutation proof
without changing env files, systemd, Binance state, or local order intents.

Confirmed apply may change only server env/systemd state described by the
resume plan, and only when the operator decision packet status is
`eligible_for_operator_resume` and the confirmation token matches. Current
Phase 58 evidence remains `collect_more_paper`, so the expected real-world
behavior is fail-closed.

</domain>

<decisions>
## Implementation Decisions

### Preview Contract
- The preview report must be a dedicated ops report, not an implicit side
  effect of `risk-profile-plan`.
- Preview includes the target risk profile, env diff, current/target live and
  paper timer/service state, operator decision status, readiness artifact path
  when provided, confirmation token, and explicit non-mutation proof.
- Preview can consume either an existing operator decision JSON artifact or a
  supplied packet object in tests; default CLI behavior may build the packet
  from existing readiness inputs.
- Preview always returns `applies_changes=false` and read-only booleans for env,
  systemd, Binance state, order intents, and orders.

### Confirmed Apply Gate
- Confirmed apply refuses to mutate when the decision packet is anything other
  than `eligible_for_operator_resume`.
- Confirmed apply also refuses when the confirmation token is missing,
  mismatched, or derived from different action-plan content.
- Apply is scoped to profile/env and live timer/service changes only. It must
  not place or cancel Binance orders, create order intents, or close positions.
- If live service is currently active, apply blocks rather than racing systemd
  state.

### Risk Boundary
- `30u_10x_multi_dynamic` remains the target profile and must stay bounded by
  account capital, available balance, per-position notional, per-trade risk,
  daily loss, portfolio margin, portfolio notional, and same-direction caps.
- The plan report should surface those bounded target values in one place so
  the operator can see why higher leverage is still constrained.
- Existing `risk_profile.apply_risk_profile` and `risk_change_check` remain the
  source of truth for env writes and risk-change permission; Phase 59 wraps
  them with the operator-packet gate instead of replacing them.

### the agent's Discretion
- Choose compact dataclass names and CLI flag names consistent with existing
  ops commands.
- Systemd mutation may be implemented behind injectable callbacks/command
  runners so unit tests prove behavior without touching the host.
- Server deployment should remain code-only unless a confirmed eligible packet
  and token are explicitly supplied later.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bfa/ops/operator_resume_decision.py` already turns readiness evidence
  into an operator packet with statuses including
  `eligible_for_operator_resume`.
- `src/bfa/ops/live_resume_readiness.py` already joins strategy matrix,
  forward-paper, exchange, server, and risk profile gates.
- `src/bfa/ops/risk_profile.py` already plans/applies the
  `30u_10x_multi_dynamic` profile with a confirmation token and env backups.
- `src/bfa/ops/exposure_status.py` and `src/bfa/ops/risk_change_check.py`
  already account for portfolio notional, margin, same-direction concentration,
  active positions, and protected exposure.

### Established Patterns
- Ops reports are frozen dataclasses with `to_dict()` and CLI JSON output.
- Mutating ops commands require explicit confirmation tokens and inactive live
  service checks.
- Tests cover direct report builders plus CLI routes and use fake clients or
  injected status providers to avoid real systemd/Binance mutation.

### Integration Points
- Add a new `src/bfa/ops/live_resume_plan.py` module for preview/apply planning.
- Add CLI routes under `python -m bfa.cli ops` for preview and confirmed apply.
- Reuse `risk_profile.build_risk_profile_plan` and `apply_risk_profile`; do not
  duplicate env-writing logic.
- Add focused tests in `tests/test_ops_live_resume_plan.py` and CLI coverage in
  `tests/test_cli.py`.

</code_context>

<specifics>
## Specific Ideas

The live pilot is already running by operator override with 10x/5-position/50U
caps, while Phase 58 still says `collect_more_paper`. This phase should make
the separate "resume/profile mutation" path auditable and fail-closed; it does
not need to stop the currently active override unless the operator asks.

</specifics>

<deferred>
## Deferred Ideas

- Server evidence packaging and final v1.25 pilot resume packet belong to
  Phase 60.
- Strategy expansion beyond the current quant setup variants belongs to v1.26+.

</deferred>
