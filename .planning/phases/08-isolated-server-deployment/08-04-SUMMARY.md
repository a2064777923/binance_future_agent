---
phase: "08-isolated-server-deployment"
plan: "08-04"
subsystem: server-deployment-smoke
tags:
  - deployment
  - server-smoke
  - systemd
key-files:
  created: []
  modified:
    - .planning/phases/08-isolated-server-deployment/08-VALIDATION.md
requirements-completed:
  - DEP-01
  - DEP-04
metrics:
  tests: "python -m unittest discover -s tests"
  server_health: "passed"
---

# Plan 08-04 Summary

## Commits

| Commit | Description |
|--------|-------------|
| 3950c86 | Captured the initial SSH-auth checkpoint after local deployment verification. |
| 20bf19e | Hardened bootstrap env line endings before final server apply. |
| 86ed2f2 | Added risk-state health verification before final server apply. |

## Delivered

- Used password auth through an in-memory Paramiko session to upload the source
  archive and bootstrap script without writing credentials to repo files or
  deployment scripts.
- Deployed latest HEAD to `/opt/binance-futures-agent/app`.
- Installed/updated `/etc/binance-futures-agent/env` and normalized it to LF.
- Installed/updated `/etc/systemd/system/binance-futures-agent.service`.
- Verified server health in `dry_run` mode.
- Verified public Binance `exchangeInfo` connectivity from the server.
- Verified `risk_state` table readiness in the SQLite event store.
- Ran the dedicated systemd oneshot service and confirmed `Result=success`,
  `ExecMainStatus=0`, `LoadState=loaded`, and disabled service state.

## Deviations

The original plan expected either SSH key access or a human-action checkpoint.
The user explicitly confirmed the root password could be used. Deployment used
Paramiko password authentication in process memory rather than command-line
password arguments, `sshpass`, or checked-in credential files.

## Self-Check

PASSED - local tests, server health checks, public Binance connectivity, DB/risk
state checks, and systemd oneshot smoke all pass. OpenAI health remains skipped
on the server until an OpenAI key is configured in the server env file.
