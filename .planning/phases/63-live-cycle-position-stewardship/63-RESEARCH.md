# Phase 63 Research: Live Cycle Position Stewardship

**Mode:** Inline fallback research. No subagent was spawned because this Codex
session requires explicit user authorization before delegation.

## Findings

1. The live runner already performs active-position review before scanning.
   - `_live_position_adjustment_plan()` is called immediately after signed
     position-risk preflight.
   - `_agent_scan_symbols()` and market collection happen later.

2. The missing behavior is persistence and richer summary.
   - Current run output includes a compact position review and adjustment plan.
   - It does not include Phase 61 diagnostics in `_position_adjustment_summary`.
   - It does not write a lifecycle event-store artifact.

3. Existing event-store tables are sufficient.
   - A custom `event_type=position_lifecycle_decision` can be stored under
     `risk_state` without a migration.

4. Auto-management should stay dormant by default.
   - Phase 62 made operator-confirmed execution safe.
   - Enabling automatic execution on the server should remain separate from code
     availability and require an explicit env change.

## Recommended Implementation

- Add config defaults:
  - `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`
  - `BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE=1`
- Add `_position_lifecycle_payload()` and `_persist_position_lifecycle()`.
- Persist lifecycle immediately after `EventStore(connection)` is created and
  before market snapshots are collected.
- Add diagnostics to `_position_adjustment_summary()`.
- Add tests that inspect DB event ordering and payload content.
