# Deployment Runbook

This project deploys into an isolated server prefix:

- App root: `/opt/binance-futures-agent`
- Environment file: `/etc/binance-futures-agent/env`
- Health unit: `/etc/systemd/system/binance-futures-agent.service`
- Live runner unit: `/etc/systemd/system/binance-futures-agent-live.service`
- Live timer: `/etc/systemd/system/binance-futures-agent-live.timer`
- Position sentinel unit: `/etc/systemd/system/binance-futures-agent-position-sentinel.service`
- Position sentinel timer: `/etc/systemd/system/binance-futures-agent-position-sentinel.timer`
- Pending-limit watchdog unit: `/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.service`
- Pending-limit watchdog timer: `/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.timer`
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

The final order size is the smallest cap left after all sizing gates. In live
mode the common reducers are `BFA_MAX_MARGIN_PER_POSITION_USDT`,
`BFA_MAX_MARGIN_FRACTION`, `BFA_MAX_EFFECTIVE_NOTIONAL_USDT`,
`BFA_MAX_PORTFOLIO_MARGIN_USDT`, `BFA_MAX_PORTFOLIO_MARGIN_FRACTION`, stop-risk
distance, exchange min-notional rounding, open/manual exposure pressure, and the
adaptive sizing governor. This is why a trade can show only 0.6-2 USDT initial
margin even when the configured account capital is larger: notional is divided
by leverage after those caps. If this is too small, raise the margin/portfolio
caps and governor ceiling together; raising leverage alone does not necessarily
raise notional.

The latest live handoff profile increased the configured account capital to
`BFA_ACCOUNT_CAPITAL_USDT=200` and portfolio margin cap to
`BFA_MAX_PORTFOLIO_MARGIN_USDT=160`. Treat those values as operator-tuned live
env settings, not source-code defaults; verify `/etc/binance-futures-agent/env`
before reasoning about current capacity.

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

## Data Retention

Live should keep `BFA_PERSIST_MARKET_SNAPSHOTS=false`. The runner still uses
fresh REST market snapshots for selection and scoring, but it does not write
every snapshot into both `events` and `market_snapshots`. Leaving this enabled
can grow the SQLite database by gigabytes in a few days because each collection
cycle writes high-volume market payloads twice, once as a generic event and once
as a category row.

Keep `BFA_PERSIST_DECISION_SNAPSHOTS=true` when raw market snapshots are
disabled. Each cycle then writes one compact `decision_snapshots` artifact with
symbol selection health, market-source counts, per-symbol ticker/kline/flow/OI
summaries, candidate rankings, micro-grid health, and rejection counts. This is
small enough for live retention while preserving the evidence needed for later
strategy debugging.

Preview retention before deleting rows:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops db-maintenance \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --clean-raw-feed
```

Apply retention without shrinking the database file:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops db-maintenance \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --execute --batch-size 5000 --max-delete-rows 25000 --clean-raw-feed
```

The normal hourly unit is intentionally incremental: it reports the full stale
snapshot backlog, but only deletes up to `BFA_DB_MAINTENANCE_MAX_DELETE_ROWS`
market-snapshot rows per run in batches of `BFA_DB_MAINTENANCE_BATCH_SIZE`.
This avoids multi-million-row deletes creating huge WAL files beside live
trading. Re-run maintenance or let the timer catch up gradually.

Enable hourly retention:

```bash
systemctl enable --now binance-futures-agent-db-maintenance.timer
systemctl list-timers 'binance-futures-agent-db-maintenance*' --no-pager
```

`--vacuum` physically shrinks `agent.sqlite`, but it can take time and lock the
database. Stop live, paper, sentinel, watchdog, and raw-feed services first, run
one maintenance command with `--execute --vacuum --clean-raw-feed`, then restart
the timers/services that should continue running.

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

### Live Cycle Status Semantics

Not every non-submitted live result is a systemd failure. The live runner treats
the following execution statuses as processed cycles so the timer can continue
scanning after the state has been recorded:

- `entry_order_expired_canceled`: a passive limit entry reached the exchange,
  waited through its configured window, and was canceled unfilled.
- `entry_order_unknown_canceled`: Binance returned an unknown entry state, no
  matching position was found, and cleanup succeeded.
- `entry_order_reconciled_from_position`: Binance returned an unknown entry
  state but a matching position exists, so the fill path was reconciled from
  position risk.
- `protective_order_failed_no_position`: protection placement failed, but the
  matching position no longer exists.
- `protective_order_failed_open`: protection placement failed and the position
  remains open. This is urgent follow-up evidence, but the service should not
  falsely stop future scans just because the cycle reported it.

`entry_order_unknown_cancel_failed` remains a failed live result because neither
the entry state nor cleanup was resolved. Protection failure statuses should
still be investigated in `order_intents`, exchange responses, current positions,
and open algo orders; they are "processed" for service health, not safe to
ignore.

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

### Fast Position Sentinel

The live cycle runs every two minutes, which is too slow for post-fill
protective maintenance. The position sentinel is a separate high-frequency
oneshot:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops position-sentinel \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite
```

With `--execute` and `BFA_POSITION_SENTINEL_EXECUTE_ENABLED=true`, it may
backfill missing stop-loss/take-profit algo orders or replace existing
protective orders when a profitable position shows rising reversal risk:

```bash
systemctl enable --now binance-futures-agent-position-sentinel.timer
systemctl list-timers 'binance-futures-agent-position-sentinel*' --no-pager
```

The sentinel deliberately ignores unrelated normal open orders while checking
already-filled positions, because a pending limit order elsewhere must not block
backfilling protection on a newly filled position. It still requires live mode,
Binance credentials, exchange symbol filters, a matching submitted intent, and
agent-managed position evidence.

If `BFA_POSITION_SENTINEL_EXECUTE_ENABLED=false`, the sentinel is observe-only:
it may emit backfill or replacement plans, but it will not place or replace
exchange orders. If `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`, full-close or
backfill lifecycle plans from the live cycle are also not executed
automatically.

The reversal-aware trailing path is not a fixed "small profit means breakeven"
rule. The sentinel scores the active position using target progress, R multiple,
recent same-direction or opposite short return, volume ratio, and recent range.
Only when the position has meaningful favorable progress and the reversal score
crosses `BFA_POSITION_SENTINEL_REVERSAL_THRESHOLD` will it convert a normal
hold/watch review into a `trail_protective_orders` plan. It does not auto full
close positions; the automatic action allowlist remains limited to protective
backfill and protective-order replacement.

`BFA_POST_ONLY_REPRICE_ENABLED=true` makes `GTX` limit entries retry after
Binance `-5022` maker rejection. For a long entry, each retry moves the price
down by `BFA_POST_ONLY_REPRICE_TICKS`; for a short entry it moves the price up.
Retries are capped by `BFA_POST_ONLY_REPRICE_MAX_ATTEMPTS`. Every attempt is
stored in the exchange response so rejected maker entries can be audited later.

### Live Rejection Triage

Use SQLite to group recent live results:

```bash
sqlite3 /opt/binance-futures-agent/data/agent.sqlite \
  "select json_extract(payload_json,'$.status') status,
          json_extract(payload_json,'$.risk.reason_codes') reasons,
          count(*) n
     from order_intents
    group by status,reasons
    order by n desc;"
```

Common rejection roots observed during live pilot:

- `-5022` post-only rejection: the limit price would immediately take liquidity.
  Reprice attempts are recorded under `entry_order.post_only_reprice`.
- `-4028` leverage invalid: that symbol does not accept the requested leverage;
  the executor downshifts through 25/20/15/12/10/8/5/3/2/1 where possible.
- `-4168` margin mode conflict: Multi-Assets mode can reject isolated-margin
  changes. Use a margin mode compatible with the account setting.
- `-4411` TradFi-Perps agreement required: exclude these symbols or complete the
  exchange-side agreement intentionally.
- `-4509` protective algo placement with no active position: old filled pending
  limits must be reconciled against current same-direction position risk before
  placing TP/SL. The pending-limit watchdog resolves filled-but-flat records
  without placing protective orders.

### Pending-Limit Watchdog

Limit entries can fill between two live cycles. The pending-limit watchdog scans
unresolved `entry_order_pending` limit intents and reconciles them against
Binance order status and current position risk:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops pending-limit-watchdog \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite
```

Without `--execute`, this command is observe-only. With `--execute` and
`BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED=true`, it immediately backfills
missing `STOP_MARKET` and `TAKE_PROFIT_MARKET` close-position algo orders for a
filled pending entry, then persists the reconciliation evidence. The timer runs
independently from the two-minute live strategy cycle:

```bash
systemctl enable --now binance-futures-agent-pending-limit-watchdog.timer
systemctl list-timers 'binance-futures-agent-pending-limit-watchdog*' --no-pager
```

This service does not open new positions. It only protects pending limit entries
that the agent already wrote to the event store, and it skips symbols listed in
`BFA_MANUAL_POSITION_SYMBOLS`.

The watchdog does not manage manual or unmatched exchange positions. If
`ops position-hold-check` reports an active position with
`matching_intent=null`, the watchdog has no pending intent to reconcile. First
classify the position with the operator, then protect or close it through the
explicit confirmation flow if it is agent-managed.

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
