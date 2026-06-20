---
phase: 53
name: Server Live-Resume Readiness Evidence
created: 2026-06-21
source: inline-gsd-fallback
---

# Context: Phase 53

## Goal

Prove the Phase 52 readiness command runs on the isolated server as a read-only
evidence command against current server, exchange, and manual exposure state.

## Requirements

- SRV-01: Operator can run `ops live-resume-readiness` on the isolated server
  deployment without restoring live timers, starting live services, applying
  risk profiles, editing env files, or placing/canceling Binance orders.
- SRV-02: Server readiness output records current paper timer, live timer, live
  service, risk profile, exchange exposure, and confirmation blockers in a
  secret-safe evidence artifact.
- SRV-03: Manual ETH/ETHUSDT or other operator-opened exposure can be marked as
  manual in the server readiness command and is never counted as agent-managed
  strategy evidence.

## Decisions

- The phase is read-only with respect to Binance, risk profiles, env files, and
  systemd timer/service state.
- Manual ETH/ETHUSDT exposure must be passed as manual exposure.
- A fail-closed readiness result is acceptable and expected while paper/matrix
  evidence is incomplete.
- Server command exit code `1` is not automatically a failure when the JSON
  schema is valid and `status` indicates a blocked live resume.
- No passwords, API keys, env file values, or raw secret-bearing command output
  may be written to git or planning docs.

## Existing Entry Points

- `python -m bfa.cli ops live-resume-readiness`
- `scripts/deploy-server.ps1`
- `docs/deployment.md`
- `src/bfa/ops/live_resume_readiness.py`
- `tests/test_ops_live_resume_readiness.py`
- `tests/test_deploy_assets.py`

## Expected Output

- A local helper for previewing/running the read-only server readiness command.
- Tests that prove the helper remains isolated and does not expose secrets or
  live-mutating commands.
- A server readiness artifact when SSH/server access is available.
- A Phase 53 summary that clearly distinguishes "command proved read-only" from
  "live resume authorized".
