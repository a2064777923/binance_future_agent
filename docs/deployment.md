# Deployment Runbook

This project deploys into an isolated server prefix:

- App root: `/opt/binance-futures-agent`
- Environment file: `/etc/binance-futures-agent/env`
- Systemd unit: `/etc/systemd/system/binance-futures-agent.service`

Do not place secret values in git, planning docs, shell history, or deployment
commands. Configure SSH authentication outside this repository.

## Preview

From `F:\binance_futures_agent`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-server.ps1
```

Preview mode prints the archive, upload, bootstrap, and health-check commands
without mutating the server.

## Apply

After previewing the commands and confirming SSH authentication is ready:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-server.ps1 -Apply
```

The script uploads a git-tracked source archive, runs `deploy/remote-bootstrap.sh`
on the server, installs a Python virtualenv, installs the dedicated systemd unit,
and runs a secret-safe health check in dry-run mode.

## Server Env

On the server, edit:

```bash
nano /etc/binance-futures-agent/env
chmod 600 /etc/binance-futures-agent/env
```

The first deployment should keep:

```bash
BFA_MODE=dry_run
BFA_OPENAI_ENABLED=false
```

Enable OpenAI and live mode only after dry-run health checks pass and the kill
switch behavior is confirmed.

## Health Checks

Dry-run local server check:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --skip-network
```

Optional network check after credentials are configured:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --check-binance --check-openai
```

## Systemd Smoke

The unit runs the health check as a oneshot service. Start it manually:

```bash
systemctl start binance-futures-agent.service
systemctl status binance-futures-agent.service --no-pager
journalctl -u binance-futures-agent.service -n 100 --no-pager
```

Do not enable live mode from the deploy script. Live activation is a separate
operator action after reviewing health output, env values, account balance, risk
limits, and the kill-switch file.
