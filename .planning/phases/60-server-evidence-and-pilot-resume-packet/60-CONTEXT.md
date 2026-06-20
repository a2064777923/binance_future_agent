# Phase 60: Server Evidence And Pilot Resume Packet - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** Autonomous inline GSD.

<domain>
## Phase Boundary

Phase 60 deploys and verifies the Phase 59 confirmation-gated live resume
controls on the isolated server, then produces current server-side evidence and
an operator-facing packet/preview. It must stay scoped to
`/opt/binance-futures-agent` and `/etc/binance-futures-agent`, preserve the
live pilot timer, and avoid touching unrelated projects such as `F:\stock` or
other server services.

The current live pilot is already active by operator override. Phase 60 should
not force a resume apply. The expected current packet remains fail-closed
because Phase 58 evidence says `collect_more_paper`.

</domain>

<decisions>
## Implementation Decisions

### Deployment Scope
- Pause only `binance-futures-agent-live.timer` and
  `binance-futures-agent-paper.timer` during code sync and tests.
- Refuse deploy if either corresponding service remains active.
- Sync only repository files under `/opt/binance-futures-agent/app`, reinstall
  the editable package in `/opt/binance-futures-agent/.venv`, and leave
  unrelated server paths untouched.
- Restore both timers after verification, regardless of whether the packet is
  eligible.

### Evidence Packet
- Generate a current `ops operator-resume-decision` artifact on the server using
  the Phase 58 matrix artifact if present.
- Pass `BTWUSDT` as manual exposure so the packet does not treat the operator's
  manual position as agent evidence.
- Generate `ops live-resume-plan` from that packet with actual current
  timer/service states. The preview must show whether apply is blocked and must
  remain non-mutating.

### Live Cycle Evidence
- Capture final timer/service readback before and after deploy.
- Inspect recent live runner output or event evidence for active-position
  review, position-adjustment plan, entry-capacity preflight, and submitted
  order trace identifiers when available.
- Do not force a live order solely for evidence; scheduled live automation can
  continue after deploy.

### the agent's Discretion
- Use compact JSON artifacts in `/opt/binance-futures-agent/app/runtime/`.
- Use focused tests for the new Phase 59 controls plus the full suite.
- If server evidence remains `collect_more_paper`, mark apply as correctly
  blocked rather than treating it as a failure.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 59 added `ops live-resume-plan` and `ops live-resume-apply`.
- Existing deploy patterns pause timers, sync source files, reinstall editable
  package, run focused/full tests, then restore timers.
- Existing `ops operator-resume-decision` can generate the current packet from
  matrix, paper, exchange, server, and risk gates.

### Established Patterns
- Server artifacts live under `/opt/binance-futures-agent/app/runtime/`.
- Server env lives at `/etc/binance-futures-agent/env`.
- Server DB lives at `/opt/binance-futures-agent/data/agent.sqlite`.
- Live timer/service state is recorded with `systemctl is-active`.

### Integration Points
- Deploy the current local code to `/opt/binance-futures-agent/app`.
- Run server focused tests:
  `tests.test_ops_live_resume_plan tests.test_cli`.
- Run server full suite.
- Generate:
  `runtime/phase60-operator-decision.json`,
  `runtime/phase60-live-resume-plan.json`,
  and a final server state artifact.

</code_context>

<specifics>
## Specific Ideas

Current server preflight before planning:
- live timer: `active`
- live service: `inactive`
- paper timer: `active`
- paper service: `inactive`
- active caps at planning start: 10x, max 5 positions, 50 USDT max position
  notional, 300 USDT portfolio notional, 250 USDT same-direction notional.
- operator follow-up during execution widened the active live caps to max 6
  positions, 60 USDT max position notional, 360 USDT portfolio notional, 300
  USDT same-direction notional, and 0.20 per-position margin fraction while
  keeping per-trade risk at 0.4 USDT and daily loss at 1 USDT.
- manual symbols: `BTWUSDT`.

</specifics>

<deferred>
## Deferred Ideas

- If the packet remains `collect_more_paper`, future strategy work belongs to
  v1.26+ rather than forcing Phase 60 to mark live-resume eligible.

</deferred>
