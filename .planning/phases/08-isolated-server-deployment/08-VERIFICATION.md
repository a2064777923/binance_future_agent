---
phase: 08-isolated-server-deployment
verified: 2026-06-20T01:45:00+08:00
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
---

# Phase 08: Isolated Server Deployment Verification Report

**Phase Goal:** Deploy the agent to `64.83.34.222` without affecting existing projects.
**Verified:** 2026-06-20T01:45:00+08:00
**Status:** passed

## Goal Achievement

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Deployment assets are secret-free and reviewable. | VERIFIED | `deploy/server-env.example`, `deploy/remote-bootstrap.sh`, `deploy/systemd/binance-futures-agent.service`, and `tests/test_deploy_assets.py`. |
| 2 | Deployment uses isolated server paths only. | VERIFIED | Remote bootstrap allowlists `/opt/binance-futures-agent` and `/etc/binance-futures-agent`; systemd unit path is dedicated. |
| 3 | The server app is installed under `/opt/binance-futures-agent/app`. | VERIFIED | Remote bootstrap installed latest HEAD and `pip install -e /opt/binance-futures-agent/app` succeeded. |
| 4 | The server env file exists with restrictive permissions. | VERIFIED | Remote `stat` showed `/etc/binance-futures-agent/env` mode `600 root:root`; line-ending check showed `contains_cr=False`. |
| 5 | Runtime/data/log directories are isolated and present. | VERIFIED | Server health passed runtime/log/export checks; remote `stat` showed app/data/log/runtime directories under `/opt/binance-futures-agent`. |
| 6 | Server health checks cover config, DB, risk state, kill switch, Binance, and OpenAI capability. | VERIFIED | `ops health-check` passed config, DB, `risk_state`, kill switch, and Binance public connectivity. OpenAI check is implemented and fake-tested; server skipped because OpenAI is disabled until a key is configured. |
| 7 | Systemd unit is dedicated and dry-run-first. | VERIFIED | `systemctl show` reported `FragmentPath=/etc/systemd/system/binance-futures-agent.service`, `Result=success`, `ExecMainStatus=0`; unit remains disabled. |
| 8 | Deployment did not enable live trading. | VERIFIED | Server health reported `mode: dry_run`, `BFA_OPENAI_ENABLED=false`, and no live-mode service loop was enabled. |
| 9 | Local regression remains green. | VERIFIED | `python -m unittest discover -s tests` passed 147 tests; `git diff --check` passed. |

**Score:** 9/9 truths verified.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| DEP-01: User can deploy the project to server under `/opt/binance-futures-agent`. | SATISFIED | Latest HEAD deployed to `/opt/binance-futures-agent/app`; health check runs from server venv. |
| DEP-02: Deployment creates/documents env file, venv, data/log/runtime dirs, and systemd unit. | SATISFIED | Bootstrap creates env placeholder, venv, data/log/runtime/export dirs, and dedicated unit; runbook documents use. |
| DEP-03: Deployment does not modify existing project directories, services, cron jobs, or databases. | SATISFIED | Scripts are allowlisted to this project's `/opt`, `/etc`, and unit path; no unrelated service/cron/database commands exist in deploy assets. |
| DEP-04: User can run server-side health checks for config, Binance, OpenAI, database, risk state, and kill switch. | SATISFIED | Health CLI supports all checks; server passed config, Binance public, DB, risk state, and kill-switch checks. OpenAI remains disabled/skipped until the server env contains an OpenAI key. |

## Automated Checks

| Command | Result |
|---------|--------|
| `python -m unittest discover -s tests` | Passed, 147 tests |
| `git diff --check` | Passed |
| `python -m unittest tests.test_deploy_assets` | Passed, 6 tests |
| `python -m unittest tests.test_ops_health tests.test_cli` | Passed, 20 tests |

## Server Checks

| Check | Result |
|-------|--------|
| Remote bootstrap | Passed |
| Server `ops health-check --check-binance --check-openai` | Passed overall; OpenAI skipped because disabled |
| Server mode | `dry_run` |
| Binance public connectivity | Passed, `exchangeInfo reachable` |
| SQLite/risk state | Passed, `risk_state table ready` |
| Systemd oneshot | Passed, `Result=success`, `ExecMainStatus=0` |
| Unit enabled state | Disabled |

## Human Verification Required

None for v1 dry-run deployment. Live activation remains a separate manual
operator action: edit `/etc/binance-futures-agent/env`, configure real keys,
confirm kill-switch behavior, run health checks again, and only then consider
`BFA_MODE=live`.

## Gaps Summary

No Phase 8 deployment gaps found for the dry-run-first v1 milestone.

---
*Verified: 2026-06-20T01:45:00+08:00*
*Verifier: Codex inline verifier*
