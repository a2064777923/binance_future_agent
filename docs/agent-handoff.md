# Agent Handoff

This repository is the source of truth for the isolated Binance Futures Agent.
It is intended to be safe for GitHub: runtime databases, raw feeds, logs,
private env files, API keys, passwords, and SSH keys must stay outside git.

## First Read

1. `AGENTS.md` - repository safety rules and working conventions.
2. `README.md` - project overview and common local commands.
3. `docs/deployment.md` - server deployment and operations runbook.
4. `docs/live-scalping-ops.md` - live scalping/raw-feed operational notes.
5. `docs/position-profit-protection.md` - active position protection logic.

The planning history lives under `.planning/`. It is useful for context, but
new work should be grounded in the current code and tests first.

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
- Checked-out app path: `/opt/binance-futures-agent/app`
- Python: `/opt/binance-futures-agent/.venv/bin/python`
- Env file: `/etc/binance-futures-agent/env`
- SQLite DB: `/opt/binance-futures-agent/data/agent.sqlite`
- Runtime state: `/opt/binance-futures-agent/runtime`
- Logs: `/opt/binance-futures-agent/logs`

Do not put server credentials in this repository. Configure SSH access outside
the repo. Any agent operating from another machine must obtain SSH access and
the server env file through an out-of-band channel.

Useful read-only checks:

```bash
python -m bfa.cli ops live-status \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --check-binance

python -m bfa.cli ops kill-switch-clearance \
  --env-file /etc/binance-futures-agent/env
```

Only use mutation commands after reading their docs and confirming the current
live state. The live account is real money.

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
