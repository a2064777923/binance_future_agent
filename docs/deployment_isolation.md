# Deployment Isolation Notes

Phase 1 does not deploy to the server. These notes define the future isolation
contract so later deployment work does not affect existing projects.

## Target Layout

Use dedicated paths for this project only:

| Purpose | Path or Name |
|---------|--------------|
| Application root | `/opt/binance-futures-agent` |
| Environment file | `/etc/binance-futures-agent/env` |
| Data directory | `/opt/binance-futures-agent/data` |
| Runtime directory | `/opt/binance-futures-agent/runtime` |
| Log directory | `/opt/binance-futures-agent/logs` |
| Systemd unit | `binance-futures-agent.service` |

The server env file should mirror the keys in `.env.example`, with real values
stored only on the server and never committed. Keep file permissions restricted
to the service account when the deployment phase creates it.

## Isolation Rules

- Do not deploy, restart services, create cron jobs, or modify server state in
  Phase 1.
- Future deployment scripts must be scoped to `/opt/binance-futures-agent`,
  `/etc/binance-futures-agent`, and `binance-futures-agent.service`.
- Future deployment scripts must not modify existing project directories,
  unrelated systemd services, cron entries, databases, nginx configs, Docker
  resources, or files from the stock project.
- Runtime data, logs, raw exports, sqlite databases, and env files stay out of
  git and are covered by `.gitignore`.
- Secrets are provided out-of-band. Do not paste them into docs, commits,
  command transcripts, or planning artifacts.

## Config Check

Validate the example config locally with:

```powershell
python -m bfa.cli config-check --env-file .env.example
```

A valid dry-run config exits with code `0`. Invalid `testnet` or `live` config
exits nonzero and prints JSON diagnostics with redacted values only.

## Final Local Gates

Run these before marking Phase 1 complete:

```powershell
python -m pip install -e .
python -m unittest discover -s tests
python -m bfa.cli config-check --env-file .env.example
git diff --check
```

Run a secret-pattern scan over tracked and pending non-ignored files:

```powershell
$patterns = @(
  'AKIA[A-Z0-9]{16}',
  'sk-[a-zA-Z0-9]{20,}',
  'sk-proj-[a-zA-Z0-9_-]+',
  'ghp_[a-zA-Z0-9]{36}',
  'xox[baprs]-[a-zA-Z0-9-]+',
  ('-----BEGIN.*PRIVATE' + ' KEY'),
  'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]\.',
  '(?i)(api[_-]?key|secret|token|password|cookie)\s*[:=]\s*[A-Za-z0-9_./+=-]{16,}'
)
$regex = ($patterns -join '|')
$files = git ls-files --cached --others --exclude-standard
$findings = foreach ($file in $files) {
  if (Test-Path -LiteralPath $file -PathType Leaf) {
    Select-String -LiteralPath $file -Pattern $regex -AllMatches -ErrorAction SilentlyContinue
  }
}
if ($findings) {
  $findings
  exit 1
}
```
