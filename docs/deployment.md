# Deployment Runbook

This project deploys into an isolated server prefix:

- App root: `/opt/binance-futures-agent`
- Environment file: `/etc/binance-futures-agent/env`
- Health unit: `/etc/systemd/system/binance-futures-agent.service`
- Live runner unit: `/etc/systemd/system/binance-futures-agent-live.service`
- Live timer: `/etc/systemd/system/binance-futures-agent-live.timer`

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
on the server, installs a Python virtualenv, installs the dedicated systemd
units, and runs a secret-safe health check in dry-run mode.

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
BFA_REQUIRE_PROTECTIVE_ORDERS=true
```

For live automated trading, configure the same file out of band with Binance
and OpenAI credentials, then set:

```bash
BFA_MODE=live
BFA_OPENAI_ENABLED=true
BFA_REQUIRE_PROTECTIVE_ORDERS=true
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TIMEOUT_SECONDS=5
OPENAI_MAX_OUTPUT_TOKENS=400
OPENAI_RETRY_AFTER_SECONDS=300
BFA_MARKET_HEAT_NARRATIVE_ENABLED=true
```

`BFA_MAX_POSITION_NOTIONAL_USDT` is a contract notional cap, not the margin
spent from the account. For example, 20 USDT notional at 20x leverage is roughly
1 USDT initial margin before fees, funding, and exchange-specific margin rules.
The live runner records `estimated_initial_margin_usdt` on order intents so the
two numbers stay visible.

Keep the kill-switch path configured. Creating that file stops future live
orders:

```bash
touch /opt/binance-futures-agent/runtime/KILL_SWITCH
```

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

Live activation evidence can be summarized without placing orders:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops live-status \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite
```

`lva05_complete=true` means a submitted entry has corresponding stop-loss and
take-profit evidence, or a protective-order failure triggered the kill-switch
and emergency close path. `lva05_complete=false` means no such live-entry
evidence exists yet.

## Systemd Smoke

The unit runs the health check as a oneshot service. Start it manually:

```bash
systemctl start binance-futures-agent.service
systemctl status binance-futures-agent.service --no-pager
journalctl -u binance-futures-agent.service -n 100 --no-pager
```

## Live Automated Runner

After env values, account balance, risk limits, OpenAI, Binance credentials, and
kill-switch behavior are reviewed, run one live cycle manually:

```bash
systemctl start binance-futures-agent-live.service
journalctl -u binance-futures-agent-live.service -n 100 --no-pager
```

Enable periodic execution only after the one-cycle result is acceptable:

```bash
systemctl enable --now binance-futures-agent-live.timer
systemctl list-timers 'binance-futures-agent-live*' --no-pager
```

Stop automated trading:

```bash
systemctl disable --now binance-futures-agent-live.timer
touch /opt/binance-futures-agent/runtime/KILL_SWITCH
```

The LLM is intentionally a slow-path filter. The runner uses
`OPENAI_TIMEOUT_SECONDS` to fail closed: if OpenAI is slow, unavailable, or
returns invalid output, the cycle stops before execution and the exchange-side
protection logic remains deterministic. When the OpenAI-compatible endpoint is
down, the runner writes `/opt/binance-futures-agent/runtime/openai_backoff.json`
and returns `openai_backoff` until `OPENAI_RETRY_AFTER_SECONDS` has elapsed;
the next timer cycle then checks the API again.

When Square exports and RSS feeds are empty, the live runner can derive a
clearly labelled `market_heat` fallback narrative from Binance USD-M public
metrics. This is controlled by `BFA_MARKET_HEAT_NARRATIVE_ENABLED` and the
`BFA_MARKET_HEAT_*` thresholds in the env file; it does not replace the OpenAI
decision gate or deterministic execution risk checks.
