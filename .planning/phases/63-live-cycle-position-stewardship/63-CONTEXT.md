# Phase 63: Live Cycle Position Stewardship - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD fallback; typed subagents were not spawned because
Codex requires explicit user authorization for subagent delegation.

<domain>
## Phase Boundary

Phase 63 makes every live cycle explicitly record active-position lifecycle
decisions before new-entry candidate generation and AI calls. The live runner
already builds a position-adjustment plan before scanning symbols; this phase
turns that preflight into a persisted lifecycle artifact and exposes the
diagnostics in the run summary.

Automatic position management should remain disabled unless an explicit env flag
is enabled. The server deployment must keep the flag disabled.
</domain>

<decisions>
## Implementation Decisions

### Lifecycle Recording
- Persist a `risk_state` artifact with `event_type=position_lifecycle_decision`
  before market snapshots, candidate generation, or AI decisions.
- Include Phase 61 diagnostics and Phase 62 plan/execution readiness fields in
  the artifact.
- Include the artifact event ID in `AgentRunResult.persisted` as
  `position_lifecycle`.

### Run Summary
- Extend `_position_adjustment_summary()` to include diagnostics, not only order
  plan candidates.
- Preserve existing `position_review` and `position_adjustment_plan` fields for
  compatibility.

### Auto-Management Gate
- Add env defaults for `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`.
- When disabled, record `auto_management.enabled=false` and do not execute.
- Do not enable auto-management on the server in this phase.

### the agent's Discretion
- Keep schema additive.
- Avoid new migrations by using the existing `risk_state` category.
- Add tests proving lifecycle artifacts are inserted before candidates/AI and
  manual positions are represented as `manual_hold`.
</decisions>

<code_context>
## Existing Code Insights

- `run_agent_once()` builds `_live_position_adjustment_plan()` before entry
  capacity checks and before `_agent_scan_symbols()`.
- The EventStore is opened later, before market snapshots and candidate
  generation.
- `AgentRunResult` already carries `position_review` and
  `position_adjustment_plan` summaries.
- `EventStore.insert_artifact()` can persist into the existing `risk_state`
  table with a custom `event_type`.
</code_context>

<specifics>
## Specific Evidence

- Phase 61 added `diagnostics` to `position-adjustment-plan`.
- Phase 62 hardened preview/operator execution but kept automatic execution off.
- Server live cycles currently print review and adjustment summaries, but not a
  persisted lifecycle artifact ID.
</specifics>

<deferred>
## Deferred Ideas

- Actually enabling deterministic auto-management in server env remains an
  operator decision after Phase 63 verification.
- Outcome reconciliation remains Phase 64.
</deferred>
