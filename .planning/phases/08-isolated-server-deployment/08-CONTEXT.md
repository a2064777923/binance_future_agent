# Phase 8: Isolated Server Deployment - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Source:** Project roadmap, Phase 7 verification, deployment constraints

<domain>
## Phase Boundary

Phase 8 prepares and performs a dry-run-first deployment of the isolated Binance
Futures Agent to the user's server without touching existing projects. It should
ship reviewable deployment assets, health checks, and a narrowly scoped remote
bootstrap path. Live trading must remain disabled unless explicitly configured
after dry-run verification.

</domain>

<decisions>
## Implementation Decisions

### Isolation

- D-01: Server files are limited to `/opt/binance-futures-agent` and
  `/etc/binance-futures-agent`; deployment scripts must reject any other target
  root.
- D-02: Deployment must not modify existing project directories, cron jobs,
  databases, or unrelated systemd units.
- D-03: Runtime data, logs, raw exports, SQLite DB, and kill-switch files live
  under `/opt/binance-futures-agent` subdirectories.

### Secrets

- D-04: Do not write server passwords, Binance keys, OpenAI keys, cookies, or
  tokens to git, planning docs, command examples, or generated deployment files.
- D-05: The server env file is documented and created as a placeholder with
  restrictive permissions; the user supplies real values out of band.

### Deployment Shape

- D-06: Deployment is dry-run-first. `BFA_MODE=dry_run` is the default server
  mode; live mode remains a manual post-verification change.
- D-07: The systemd unit is dedicated to this project and references only the
  isolated env file, app directory, venv, and runtime paths.
- D-08: Deployment tooling should support a local `what-if`/dry-run mode and an
  explicit apply mode.

### Verification

- D-09: Server health checks must verify config, required directories, DB
  access, kill-switch path, optional public Binance connectivity, and optional
  OpenAI connectivity without printing secrets.
- D-10: If secure non-interactive SSH credentials are unavailable, execution
  should stop at a human-action checkpoint rather than placing a password in
  command-line history or files.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` - isolation, server path, and secret posture.
- `.planning/REQUIREMENTS.md` - DEP-01 through DEP-04.
- `.planning/phases/07-risk-gated-binance-execution/07-VERIFICATION.md` -
  execution layer that deployment will package.
- `.env.example` - server env contract.
- `src/bfa/config.py` - runtime paths, risk caps, credentials, and mode checks.
- `src/bfa/cli.py` - existing CLI command style.

</canonical_refs>

<specifics>
## Specific Ideas

- Add deployment templates under `deploy/` and scripts under `scripts/`.
- Add a health-check module and CLI command using dependency injection in tests.
- Make deployment scripts fail closed on non-isolated paths.
- Add docs/runbook for dry-run-first server setup and live activation checklist.

</specifics>

<deferred>
## Deferred Ideas

- Continuous strategy scheduler/daemon beyond health-check and dry-run smoke.
- Production-grade process supervision for multi-strategy loops.
- Live-mode activation with real keys unless the user explicitly completes the
  deployment checkpoint.

</deferred>

---
*Phase: 08-isolated-server-deployment*
*Context gathered: 2026-06-20*
