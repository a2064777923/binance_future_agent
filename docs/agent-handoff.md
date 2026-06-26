# Agent Handoff

This repository is the source of truth for the isolated Binance Futures Agent.
It is intended to be safe for GitHub: runtime databases, raw feeds, logs,
private env files, API keys, passwords, and SSH keys must stay outside git.

## First Read

1. `AGENTS.md` - repository safety rules and working conventions.
2. `docs/current-live-strategy.md` - current live strategy, server snapshot,
   risk profile, services, and non-secret env facts.
3. `README.md` - project overview and common local commands.
4. `docs/deployment.md` - server deployment and operations runbook.
5. `docs/live-scalping-ops.md` - live scalping/raw-feed operational notes.
6. `docs/position-profit-protection.md` - active position protection logic.
7. `.planning/POST-GSD-LIVE-ITERATIONS.md` - post-GSD live strategy changes
   that are newer than the formal Phase 70 artifacts.

The planning history lives under `.planning/`. It is useful for context, but
new work should be grounded in the current code and tests first. The formal GSD
phase history currently ends at v1.27 Phase 70; later live iterations are
summarized in `.planning/POST-GSD-LIVE-ITERATIONS.md`.

## Local Setup

From a fresh clone:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m unittest discover -s tests
git diff --check
```

On Linux/macOS, replace `.venv\Scripts\python` with `.venv/bin/python`.

## Repository Layout

- `src/bfa/agent.py` - live/paper runner orchestration, candidate fusion, regime
  routing, AI overlay, risk/execution flow.
- `src/bfa/strategy/` - candidate scoring, deterministic setup logic, regime
  router, micro-grid/scalping strategy.
- `src/bfa/execution/` - Binance client, risk checks, sizing, order execution,
  protective order handling.
- `src/bfa/ops/` - operational commands for live status, kill switch,
  position sentinel, pending-limit watchdog, DB maintenance, reconciliation,
  and risk profile changes.
- `src/bfa/backtest/` - candle/replay backtest models and hftbacktest adapter.
- `scripts/` - research, replay, raw-feed, deployment, and audit helpers.
- `deploy/` - server bootstrap and systemd unit templates.
- `tests/` - unit and regression tests covering strategy, ops, risk, execution,
  deployment assets, and scripts.

## Live Server Context

The live deployment is isolated from other projects:

- App root: `/opt/binance-futures-agent`
- Live app path: `/opt/binance-futures-agent/app`
- Python: `/opt/binance-futures-agent/.venv/bin/python`
- Env file: `/etc/binance-futures-agent/env`
- SQLite DB: `/opt/binance-futures-agent/data/agent.sqlite`
- Runtime state: `/opt/binance-futures-agent/runtime`
- Logs: `/opt/binance-futures-agent/logs`

The live app path is a deployed copy, not necessarily a git checkout. The
latest checked live caps were `BFA_ACCOUNT_CAPITAL_USDT=200`,
`BFA_MAX_PORTFOLIO_MARGIN_USDT=160`, base `BFA_MAX_OPEN_POSITIONS=5`, and
`BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS=2`; see
`docs/current-live-strategy.md` for the full non-secret snapshot. Always verify
the server env before using these numbers.

Do not put server credentials in this repository. Configure SSH access outside
the repo. Any agent operating from another machine must obtain SSH access and
the server env file through an out-of-band channel.

Useful read-only checks:

```bash
systemctl list-units --type=service --type=timer --all 'binance-futures-agent*' --no-pager

python -m bfa.cli ops live-status \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --check-binance

python -m bfa.cli ops position-hold-check \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite

python -m bfa.cli ops live-cycle-explainability \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --latest-cycles 10

python -m bfa.cli ops kill-switch-clearance \
  --env-file /etc/binance-futures-agent/env
```

Only use mutation commands after reading their docs and confirming the current
live state. The live account is real money.

## Current Live Ops Semantics

Before assuming "the bot stopped," inspect systemd timers, the latest live
result, current exchange positions, open algo orders, and matching event-store
intents. A healthy timer can produce no new position when passive entries expire
unfilled or when risk gates reject the current state.

Processed live-cycle statuses include `entry_order_expired_canceled`,
`entry_order_unknown_canceled`, `entry_order_reconciled_from_position`,
`protective_order_failed_no_position`, and `protective_order_failed_open`.
They keep the live timer from falsely failing after the state is recorded.
`protective_order_failed_open` is still urgent risk evidence: verify exchange
protection and current position ownership immediately. `entry_order_unknown_cancel_failed`
remains a failed status.

Unmatched positions require special care. If `ops position-hold-check` shows an
active exchange position with no matching submitted intent, the pending-limit
watchdog cannot help because it only reconciles unresolved pending entry
intents. Classify the symbol as manual only after operator confirmation;
otherwise handle protection or closure through the explicit confirmation flow.

## Current Strategy Shape

The current system is a fused live strategy with a regime router:

- `TREND`: normal trend leg, DeepSeek/OpenAI-compatible AI review when enabled,
  longer hold tolerance, wider R targets, trend-aligned direction only.
- `RANGE`: micro-grid / range-reversion scalping leg using recent raw feed,
  post-only limit entry, short pending wait, and fast protection management.
- `CHOP`: no new entry.

Micro-grid can use extra slots and an extra same-direction notional allowance so
trend positions do not fully crowd out scalping attempts. Protective SL/TP is
required for live fills, and the pending-limit watchdog plus position sentinel
exist to close gaps between submitted limit orders, fills, and protection.

Micro-grid is now an independent fast lane and should not be analyzed as a
trend candidate that happened to use small exits. It bypasses AI, records
`strategy_leg=micro_grid`, uses `regime_label=RANGE`, and persists latency
fields so signal-to-submit delay can be audited. Trend candidates still use the
AI review path when enabled. See `docs/current-live-strategy.md` before
changing routing or risk.

Micro-grid live now consumes real per-symbol market context derived from the
same Binance snapshots used elsewhere in the system. Do not reintroduce fake
liquidity or synthetic `min_executable_notional` values in the live path. If a
symbol lacks market context, the candidate should carry explicit `missing_*`
diagnostics or be rejected.

Live outcome guard is a downsize-first feedback signal, not a one-trade kill
switch. The default symbol sample floor is `5` closed outcomes; lower values can
be set explicitly for experiments, but should not be treated as production
evidence.

## Runtime Data Policy

These are intentionally ignored and must not be committed:

- `.env`, `.env.*` except `.env.example`
- `data/`, `runtime/`, `logs/`, `results/`, `raw_exports/`
- `*.sqlite`, `*.db`, `*.jsonl`, `*.csv`, `*.parquet`, `*.log`
- SSH keys, PEM files, certificates, cookies, and exchange exports

If an analysis artifact is needed for collaboration, summarize it in docs or
commit a small redacted fixture under `tests/fixtures/`.

## Before Pushing

Run:

```bash
python -m unittest discover -s tests
git diff --check
```

Also run a secret-pattern scan before publishing:

```bash
python - <<'PY'
import os, re, sys
root = "."
patterns = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
ignore_dirs = {".git", ".venv", ".venv-hft", "__pycache__", ".pytest_cache",
               "data", "results", "runtime", "logs"}
findings = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
    for filename in filenames:
        path = os.path.join(dirpath, filename)
        try:
            data = open(path, "rb").read()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in patterns):
                findings.append(f"{path}:{lineno}")
for finding in findings:
    print(finding)
sys.exit(1 if findings else 0)
PY
```
