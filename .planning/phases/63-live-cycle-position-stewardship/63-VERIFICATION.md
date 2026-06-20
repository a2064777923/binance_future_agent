---
phase: 63
name: Live Cycle Position Stewardship
verified: 2026-06-21
status: passed
---

# Phase 63 Verification

## Local Verification

- `python -m unittest tests.test_agent_runner tests.test_config`
  - Result: passed, 37 tests.
- `python -m unittest discover -s tests`
  - Result: passed, 394 tests.
- `git diff --check`
  - Result: passed; only CRLF working-copy warnings were emitted.

## Server Verification

Server path: `/opt/binance-futures-agent/app`.

- Deployed from git archive `HEAD` while live/paper timers were paused and both
  services were inactive.
- Server health:
  `/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check --env-file /etc/binance-futures-agent/env --db /opt/binance-futures-agent/data/agent.sqlite --skip-network`
  - Result: passed.
- Server focused:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest tests.test_agent_runner tests.test_config`
  - Result: passed, 37 tests.
- Server full:
  `/opt/binance-futures-agent/.venv/bin/python -m unittest discover -s tests`
  - Result: passed, 394 tests.

## Server Runtime Evidence

Final timer/service readback after deploy:

- `binance-futures-agent-live.timer=active`
- `binance-futures-agent-live.service=inactive`
- `binance-futures-agent-paper.timer=active`
- `binance-futures-agent-paper.service=inactive`

Server env readback:

- `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT`
- `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`
- `BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE=1`
- `BFA_MAX_OPEN_POSITIONS=8`
- `BFA_MAX_POSITION_NOTIONAL_USDT=80`
- `BFA_MAX_LEVERAGE=10`

Artifact smoke:

- `/opt/binance-futures-agent/runtime/phase63-live-cycle-smoke.json`
  - `status=entry_capacity_blocked`
  - `submitted=false`
  - `candidate_count=0`
  - `market_snapshot_count=0`
  - `persisted.position_lifecycle=432677`

Normal timer run evidence:

- Lifecycle event `432682` was written at `2026-06-20T22:19:04Z`.
- Live candidate event `439056` was written after the lifecycle event.
- Diagnostics recorded `NEARUSDT=close_ready` and `BTWUSDT=manual_hold`.
- The live run completed with `submitted=false` and `status=quant_pass`.

## Requirement Checks

| Requirement | Status | Evidence |
|-------------|--------|----------|
| POS-03 | satisfied | Local tests and server DB event order prove `position_lifecycle_decision` is persisted before candidates/trade setup/AI. Payload diagnostics include `close_ready` and `manual_hold`. |
| EXIT-02 | satisfied for dormant gate | Auto-management has explicit env flags, validates max actions, records enabled/disabled state, selects no actions while disabled, and preserves manual-symbol exclusions. Server env remains disabled. |

## Mutation Check

Phase 63 deployed source code, wrote explicit disabled env keys, ran tests,
health checks, a capacity-blocked live-cycle smoke, and normal timer readbacks.
The smoke had `submitted=false` and did not scan candidates or call AI. The
normal post-restore timer run submitted no order.

No confirmed close/reduce execution, live-resume apply, Binance order, or
cancel command was run. No file under `F:\stock` was touched.
