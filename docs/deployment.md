# Deployment Runbook

This project deploys into an isolated server prefix:

- App root: `/opt/binance-futures-agent`
- Environment file: `/etc/binance-futures-agent/env`
- Health unit: `/etc/systemd/system/binance-futures-agent.service`
- Live runner unit: `/etc/systemd/system/binance-futures-agent-live.service`
- Live timer: `/etc/systemd/system/binance-futures-agent-live.timer`
- Forward-paper unit: `/etc/systemd/system/binance-futures-agent-paper.service`
- Forward-paper timer: `/etc/systemd/system/binance-futures-agent-paper.timer`

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
BFA_AI_PROVIDER=openai
BFA_OPENAI_ENABLED=false
BFA_REQUIRE_PROTECTIVE_ORDERS=true
```

For live automated trading, configure the same file out of band with Binance
and AI provider credentials, then set:

```bash
BFA_MODE=live
BFA_AI_PROVIDER=openai
BFA_OPENAI_ENABLED=true
BFA_REQUIRE_PROTECTIVE_ORDERS=true
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TIMEOUT_SECONDS=5
OPENAI_MAX_OUTPUT_TOKENS=400
OPENAI_RETRY_AFTER_SECONDS=300
BFA_MARKET_HEAT_NARRATIVE_ENABLED=true
```

DeepSeek can be used instead of OpenAI through its OpenAI-compatible Chat
Completions API:

```bash
BFA_AI_PROVIDER=deepseek
BFA_OPENAI_ENABLED=true
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

`OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`, and
`OPENAI_RETRY_AFTER_SECONDS` still apply to the selected AI provider.

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

## Live Resume Readiness

Before discussing any live timer restore, run the read-only readiness report on
the isolated server. Preview the exact SSH command first:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-server-readiness.ps1
```

Run it only after reviewing the preview:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-server-readiness.ps1 -Run
```

The helper runs `ops live-resume-readiness` under `/opt/binance-futures-agent`
with env from `/etc/binance-futures-agent/env`, writes a local JSON artifact
under `runtime/`, and marks `ETHUSDT` as manual exposure by default. Use
`-ManualExposureSymbols "ETHUSDT,SOLUSDT"` if more manually opened symbols must
be excluded from agent-managed evidence.

By default the helper uses SSH `BatchMode=yes` so it fails fast instead of
hanging on an interactive password prompt. If you intentionally want to type the
server password in an SSH prompt, add `-AllowPasswordPrompt`; do not place
passwords in scripts, docs, shell history, or git-tracked files.

Exit code `1` can be an expected fail-closed result when readiness is blocked.
The helper accepts exit code `0` or `1` only when stdout parses as
`bfa_live_resume_readiness_v1`. Any other exit code or invalid JSON is treated
as a failed check.

This procedure does not restore `binance-futures-agent-live.timer`, start
`binance-futures-agent-live.service`, apply risk profiles, edit env files,
create order intents, or place/cancel Binance orders.

To turn a readiness artifact into the operator-facing next action, run the
read-only decision packet:

```bash
cd /opt/binance-futures-agent/app
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops operator-resume-decision \
  --env-file /etc/binance-futures-agent/env \
  --readiness-report /opt/binance-futures-agent/app/runtime/server-live-resume-readiness-phase54-20260620T181837Z.json
```

The packet returns one of `keep_live_paused`, `collect_more_paper`,
`resolve_exposure`, or `eligible_for_operator_resume`. It still does not
restore timers, apply profiles, edit env files, create order intents, or touch
Binance orders; `eligible_for_operator_resume` only means a separate explicit
confirmation flow can be prepared.

## Live Automated Runner

After env values, account balance, risk limits, AI provider, Binance credentials, and
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
`OPENAI_TIMEOUT_SECONDS` to fail closed: if the selected AI provider is slow,
unavailable, or returns invalid output, the cycle stops before execution and the
exchange-side protection logic remains deterministic. When the AI endpoint is
down, the runner writes `/opt/binance-futures-agent/runtime/openai_backoff.json`
and returns `openai_backoff` until `OPENAI_RETRY_AFTER_SECONDS` has elapsed;
the next timer cycle then checks the API again.

When Square exports and RSS feeds are empty, the live runner can derive a
clearly labelled `market_heat` fallback narrative from Binance USD-M public
metrics. This is controlled by `BFA_MARKET_HEAT_NARRATIVE_ENABLED` and the
`BFA_MARKET_HEAT_*` thresholds in the env file; it does not replace the AI
decision gate or deterministic execution risk checks.

Live and dry-run cycles can optionally scan a wider hot-symbol universe before
candidate ranking by setting `BFA_LIVE_AUTO_HOT_SYMBOLS=true`. When enabled,
the runner selects up to `BFA_LIVE_AUTO_HOT_TOP_N` USDT USD-M symbols from the
public 24h ticker using quote-volume and absolute price-change filters, then
uses that same universe for market collection, narrative matching, market-heat
fallback, and candidate allowlisting. This only widens scanning: `agent run-once
--top-n`, deterministic setup gates, AI overlay or quant fallback, risk caps,
and one-order-per-cycle behavior still apply. The default is `false`; when
disabled or empty, the runner falls back to `BFA_MARKET_SYMBOLS`.

## Forward-Paper Recorder

Forward-paper collection is separate from live automation. It records
`paper_signals` and `paper_outcomes` from public klines and never creates
`order_intents`. By default the paper service auto-selects up to 40 hot USD-M
USDT symbols from Binance 24h ticker data using quote-volume and absolute
price-change filters. This is deliberately wider than the live
`BFA_MARKET_SYMBOLS` pilot allowlist:

```bash
systemctl start binance-futures-agent-paper.service
journalctl -u binance-futures-agent-paper.service -n 100 --no-pager
```

Enable the paper-only timer only when you want repeated observation:

```bash
systemctl enable --now binance-futures-agent-paper.timer
systemctl list-timers 'binance-futures-agent-paper*' --no-pager
```

This does not enable `binance-futures-agent-live.timer`.
