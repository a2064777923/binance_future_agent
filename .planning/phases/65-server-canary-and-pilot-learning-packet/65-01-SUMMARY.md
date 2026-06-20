---
phase: 65-server-canary-and-pilot-learning-packet
plan: 01
subsystem: ops
tags: [binance, server-canary, pilot-learning, lifecycle, live-outcomes]
requires:
  - phase: 64-live-outcome-ledger-and-guard-feedback
    provides: live outcome ledger, trace IDs, and recommendation-only guard feedback
provides:
  - read-only ops pilot-learning-packet command
  - server pilot learning packet artifact with lifecycle, caps, exit, ledger, and trace evidence
  - Phase 65 server canary evidence with timers restored
affects: [live-ops, pilot-learning, server-evidence, milestone-closeout]
tech-stack:
  added: []
  patterns: [read-only ops report composition, server canary artifact, mutation proof]
key-files:
  created:
    - src/bfa/ops/pilot_learning_packet.py
    - tests/test_ops_pilot_learning_packet.py
  modified:
    - src/bfa/cli.py
    - tests/test_cli.py
    - README.md
key-decisions:
  - "Pilot learning packet composes existing read-only reports instead of duplicating Binance order or risk logic."
  - "Live outcome ledger is consumed with reconcile=false and persist_closed=false, so packet generation cannot write fills or outcomes."
  - "BTWUSDT remains a manual symbol and appears as manual_hold/manual_position_ignored in the packet."
patterns-established:
  - "Server canary packets should include an explicit mutation_proof block for every live-ops evidence bundle."
  - "Trace evidence is bounded by latest_traces and indexed by event IDs instead of embedding unbounded history."
requirements-completed: [OPS-01, OPS-02]
duration: 25 min
completed: 2026-06-21
status: complete
---

# Phase 65 Plan 01: Server Canary And Pilot Learning Packet Summary

**Read-only pilot learning packet deployed on the isolated server with lifecycle, cap, exit, ledger, and trace evidence**

## Performance

- **Duration:** 25 min
- **Started:** 2026-06-20T23:00:00Z
- **Completed:** 2026-06-20T23:25:25Z
- **Tasks:** 8
- **Files modified:** 8 implementation/test/docs/planning files

## Accomplishments

- Added `ops pilot-learning-packet`, a read-only packet that composes exposure capacity, manual exclusions, position lifecycle decisions, time-exit status, live outcome ledger data, recommendation-only guard feedback, and bounded trade traces.
- Deployed commit `5aeabb4` to `/opt/binance-futures-agent/app` using the existing isolated bootstrap path.
- Generated `/opt/binance-futures-agent/app/runtime/phase65-pilot-learning-packet.json` on the server.
- Verified the packet reports `BTWUSDT` as manual-only, bot-managed exposure count `0`, entry capacity available, `outcome_count=5`, `trace_count=11`, and all mutation flags false.
- Restored live and paper timers after deployment and artifact generation.

## Task Commits

1. **Tasks 1-6: Packet module, CLI, docs, tests, and local verification** - `5aeabb4` (`feat(65-01): add pilot learning packet`)

**Plan metadata:** pending in closeout commit.

## Files Created/Modified

- `src/bfa/ops/pilot_learning_packet.py` - Builds the read-only learning packet by composing exposure, lifecycle, time-exit, ledger, and trace reports.
- `src/bfa/cli.py` - Adds `ops pilot-learning-packet` with `--env-file`, `--db`, `--now`, `--latest-traces`, and `--skip-binance`.
- `tests/test_ops_pilot_learning_packet.py` - Covers manual exposure, cap usage, lifecycle, exit status, live ledger, traces, and mutation proof.
- `tests/test_cli.py` - Covers CLI JSON shape for the new ops command.
- `README.md` - Adds packet usage and non-mutation documentation.

## Decisions Made

- The packet command reuses existing report builders and does not contain exchange mutation logic.
- `latest_traces` bounds trace collection so the canary artifact remains finite.
- Server artifacts are written under `/opt/binance-futures-agent/app/runtime` for Phase 65 evidence, while durable runtime/data/log paths remain isolated under `/opt/binance-futures-agent`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The deployed source archive did not contain an empty `app/runtime` directory, so the first health artifact redirect failed after tests had passed. Timers were restored by trap, then `app/runtime` was created and health/packet artifacts were generated successfully.

## Verification

- Local focused: `python -m unittest tests.test_ops_pilot_learning_packet tests.test_cli` -> 58 tests OK.
- Local full: `python -m unittest discover -s tests` -> 405 tests OK.
- Local lint: `git diff --check` -> no whitespace errors; CRLF warnings only.
- Server focused: `/opt/binance-futures-agent/.venv/bin/python -m unittest tests.test_ops_pilot_learning_packet tests.test_cli` -> 58 tests OK.
- Server full: `/opt/binance-futures-agent/.venv/bin/python -m unittest discover -s tests` -> 405 tests OK.
- Server health: `/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite --skip-network` -> `ok=true`.
- Server packet: `schema=bfa_pilot_learning_packet_v1`, `status=packet_ready`, `manual_symbols=["BTWUSDT"]`, `bot_position_count=0`, `manual_position_count=1`, `entry_capacity_available`, `exit_plan_blocked`, `ledger_ready`, `outcome_count=5`, `trace_count=11`.
- Sensitive scan: no API key, secret, bearer, password, confirmation token, or `sk-...` pattern found in the packet artifact.
- Final server state: live timer active, paper timer active, live service inactive, paper service inactive.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

All v1.26 phases are now complete. The next GSD action is milestone closeout: archive v1.26 and decide the next milestone scope from current live packet evidence and operator priorities.

---
*Phase: 65-server-canary-and-pilot-learning-packet*
*Completed: 2026-06-21*
