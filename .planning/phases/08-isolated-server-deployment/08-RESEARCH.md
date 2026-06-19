# Phase 8 Research: Isolated Server Deployment

**Date:** 2026-06-20
**Scope:** Linux server deployment, systemd unit, env handling, health checks,
and safe local-to-remote workflow.

## Findings

1. The project has no runtime dependencies beyond Python 3.11+, so deployment
   can use a dedicated virtualenv and editable install from the app directory.

2. Existing config defaults already target `/opt/binance-futures-agent`, making
   the deployment path consistent with the application contract.

3. A dedicated systemd unit can reference an env file with `EnvironmentFile=`
   and avoid embedding secrets in the unit file.

4. A Windows-origin deployment flow should not assume `rsync`; PowerShell can
   package a git-tracked source archive and use OpenSSH `scp`/`ssh` when the
   user has a secure auth path.

5. A deployment script should default to plan/what-if mode and require an
   explicit `-Apply` switch before it runs remote mutating commands.

## Implementation Direction

- Keep deployment assets reviewable and static.
- Keep server paths allowlisted and centralized.
- Add a health-check CLI that can run locally and on the server.
- Keep network checks optional in tests and fakeable in unit tests.
- Do not commit secrets or interactive credentials.

## Validation Architecture

- Unit tests for health-check result aggregation and redaction.
- CLI tests for health-check JSON output.
- Static tests for deploy scripts/manifests:
  - only allowlisted server paths;
  - systemd unit points to dedicated env/app/venv paths;
  - scripts contain no forbidden stock paths or secret placeholders.
- Full regression: `python -m unittest discover -s tests`.

## Known Pitfalls

- Root server access can damage unrelated services if scripts are not
  allowlisted.
- Systemd units must not embed secret values.
- Password-based SSH should not be automated by writing passwords to files or
  command-line arguments.
- The first server run must be dry-run/test mode, not live.
