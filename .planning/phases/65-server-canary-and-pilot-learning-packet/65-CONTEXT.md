# Phase 65: Server Canary And Pilot Learning Packet - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD fallback.

<domain>
## Phase Boundary

Phase 65 closes v1.26 by deploying the current live-position management and
learning stack to the isolated server, then producing one current pilot learning
packet from server evidence. The packet must be safe to rerun, secret-safe, and
read-only against Binance unless an existing command is explicitly asked to
perform idempotent outcome reconciliation.

The server target remains isolated to `/opt/binance-futures-agent` and
`/etc/binance-futures-agent`. Deployment may pause the project live/paper
timers, but must restore them and must not modify unrelated server services or
the source repository at `F:\stock`.
</domain>

<decisions>
## Implementation Decisions

### Packet Command
- Add `ops pilot-learning-packet` as a read-only operator command.
- It should compose existing evidence from `ops exposure-status`,
  `ops position-review`, `ops time-exit-plan`, `ops live-outcome-ledger`, and
  recent `ops trade-trace` records instead of duplicating their logic.
- It must emit `schema=bfa_pilot_learning_packet_v1`.

### Required Evidence
- Include lifecycle decisions for active positions, including
  `manual_hold` rows for `BFA_MANUAL_POSITION_SYMBOLS` such as `BTWUSDT`.
- Include cap usage from exposure status: current profile, sizing,
  entry-capacity state, active bot exposure, manual exposure, and portfolio cap
  utilization.
- Include exit-plan status and reasons from time-exit planning.
- Include entry and exit trace IDs where available: order intent, trade setup,
  AI decision, exchange response, and outcome event IDs.
- Include live outcome summary and recommendation-only guard feedback from the
  live outcome ledger.

### Non-Mutation Contract
- The packet command must not place orders, cancel orders, write env files,
  change systemd state, raise risk, apply guard changes, or persist outcomes.
- Server deployment may pause/restore only the BFA timers when necessary.
</decisions>

<canonical_refs>
## Canonical References

### Planning
- `.planning/ROADMAP.md` — Phase 65 goal, requirements, and success criteria.
- `.planning/REQUIREMENTS.md` — OPS-01 and OPS-02 definitions.
- `.planning/phases/64-live-outcome-ledger-and-guard-feedback/64-01-SUMMARY.md` — latest live outcome ledger behavior and server evidence.

### Code
- `src/bfa/ops/live_outcome_ledger.py` — closed live outcome summary and guard feedback.
- `src/bfa/ops/exposure_status.py` — cap usage, manual exposure, and entry capacity.
- `src/bfa/ops/position_review.py` — lifecycle decisions and manual-symbol handling.
- `src/bfa/ops/position_hold_check.py` — time-exit planning source.
- `src/bfa/ops/trade_trace.py` — trace reconstruction for submitted entries.
- `src/bfa/cli.py` — ops command registration and JSON output behavior.
- `scripts/deploy-server.ps1` — existing scoped server deployment helper.
</canonical_refs>

<specifics>
## Specific Ideas

- Prefer a compact packet with full nested source reports plus a small
  `learning_summary` distilled from them.
- Server smoke should write JSON artifacts under
  `/opt/binance-futures-agent/app/runtime/phase65-*`.
- The packet must classify `BTWUSDT` as manual when it exists and must not treat
  it as agent-managed performance evidence.
- Because the operator recently widened live caps out of band, the packet
  should report current server env values as evidence rather than assuming the
  older `30u_10x_multi_dynamic` defaults.
</specifics>

<deferred>
## Deferred Ideas

- Automatically applying guard recommendations remains out of scope.
- Raising leverage above 10x remains out of scope.
- Managing manual `BTWUSDT` remains out of scope unless the operator explicitly
  transfers it to the agent in a future phase.
</deferred>
