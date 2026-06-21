---
phase: 70-server-canary-and-manual-boundary-verification
plan: 01
subsystem: server-ops
tags: [server-canary, live-pilot, manual-boundary, adaptive-sizing, v1.27]

requires:
  - phase: 66-live-cycle-explainability-and-ledger-cadence
    provides: live-cycle explainability command
  - phase: 67-adaptive-hot-symbol-breadth-and-guarded-queue
    provides: broad live auto-hot scanner
  - phase: 68-multi-factor-edge-and-point-precision
    provides: factor and point diagnostics
  - phase: 69-adaptive-sizing-and-high-leverage-governor
    provides: adaptive sizing governor
provides:
  - v1.27 deployed on the isolated server path
  - server canary artifacts for current live/paper state
  - live one-shot evidence using the latest strategy and risk stack
  - manual `BTWUSDT` boundary proof under current live exchange state
  - restored live/paper timers after deployment
affects: [live-ops, v1.27-closeout]

tech-stack:
  added: []
  patterns:
    - isolated bootstrap deployment
    - timer pause/deploy/test/canary/restore cycle
    - artifact-level sensitive field scan

key-files:
  created:
    - .planning/phases/70-server-canary-and-manual-boundary-verification/70-01-PLAN.md
    - .planning/phases/70-server-canary-and-manual-boundary-verification/70-01-SUMMARY.md
    - .planning/phases/70-server-canary-and-manual-boundary-verification/70-VERIFICATION.md
  modified:
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md
    - .planning/PROJECT.md

key-decisions:
  - "Phase 70 deploys v1.27 using the existing isolated bootstrap path instead of adding new deployment mechanics."
  - "The live canary runs with timers paused to avoid overlap with scheduled cycles."
  - "BTWUSDT remains operator-owned: visible in diagnostics, excluded from bot-managed count and action recommendations, included only as margin pressure."
  - "The live one-shot may submit no order; a no-order result is acceptable when deterministic guard evidence blocks the setup."

patterns-established:
  - "Server canary evidence is stored under /opt/binance-futures-agent/app/runtime/phase70-*.json."
  - "Final timer state is verified after deployment and after any restored paper service finishes."
  - "Sensitive scans cover JSON artifacts and live one-shot journal snippets."

requirements-completed: [OPS-04, OPS-05, RISK-05]

duration: 52 min
completed: 2026-06-21
status: complete
---

# Phase 70 Plan 01: Server Canary And Manual Boundary Verification Summary

**v1.27 is deployed on the isolated server, live/paper timers are restored, and the latest live canary ran without submitting an order because the forward-paper factor guard blocked the setup.**

## Performance

- **Duration:** 52 min
- **Started:** 2026-06-21T01:58:00Z
- **Completed:** 2026-06-21T02:49:32Z
- **Tasks:** 6/6
- **Files modified:** planning closeout only

## Accomplishments

- Deployed commit `7a55ece` to `/opt/binance-futures-agent/app` using the existing `deploy/remote-bootstrap.sh` isolated path guards.
- Backed up `/etc/binance-futures-agent/env` to `/etc/binance-futures-agent/env.bak.phase70-governor-20260621T024001Z` and added explicit adaptive sizing governor keys without changing secrets.
- Ran server focused tests (`107` tests OK), server full tests (`420` tests OK), and server health check (`ok=true`).
- Generated Phase 70 server artifacts:
  - `/opt/binance-futures-agent/app/runtime/phase70-pilot-learning-packet.json`
  - `/opt/binance-futures-agent/app/runtime/phase70-live-status-final.json`
  - `/opt/binance-futures-agent/app/runtime/phase70-exposure-status-final.json`
  - `/opt/binance-futures-agent/app/runtime/phase70-position-review-final.json`
  - `/opt/binance-futures-agent/app/runtime/phase70-live-cycle-final.json`
  - `/opt/binance-futures-agent/app/runtime/phase70-live-oneshot-journal.txt`
- Ran a live one-shot canary with timers paused. It scanned broad hot symbols, evaluated the latest multi-factor setup path, and ended `quant_pass` with `submitted=false`; journal evidence shows the final setup was blocked by `forward_paper_guard_factor:24h_momentum`.
- Restored live and paper timers. Final server state: live timer active, live service inactive, paper timer active, paper service inactive.
- Verified `BTWUSDT` is visible as manual exposure and not bot-managed. Final check reports `manual_position_count=1`, `active_position_count=0`, `manual_initial_margin_usdt=31.66096`, and `entry_capacity_available`.

## Current Server State

- Mode: `live`
- Manual symbols: `BTWUSDT`
- Leverage/caps: `10x`, `60` max open bot positions, `500` USDT max position/effective notional, `150` USDT portfolio margin cap, `5000` USDT portfolio notional cap, `3500` USDT same-direction cap.
- Dynamic sizing: enabled.
- Adaptive sizing governor: enabled, max multiplier `1.15`.
- Current final exchange exposure: one `BTWUSDT` manual `SHORT`, not bot-managed.
- Latest final cycle after timer restore: `REUSDT` flat, no order submitted.
- Live one-shot canary result: no order submitted.

## Decisions Made

- The live env governor keys were made explicit for auditability; this was a non-secret env update with backup.
- The live canary result is treated as a success because the system ran the latest scanner/setup/sizing stack and declined to trade for guard reasons.
- The manual `BTWUSDT` position remains operator-owned. It is excluded from bot action but included as margin pressure.

## Deviations from Plan

- `live-status` reports the latest historical protective evidence for `NEARUSDT` even though current exchange evidence has only manual `BTWUSDT`. Final exposure and position-review artifacts are treated as the current-state source of truth for manual boundary proof.
- The first Phase 70 exposure artifact captured `BTWUSDT` as manual LONG, while the final read after timer restore captured `BTWUSDT` as manual SHORT. In both cases it remained manual-only with bot active positions `0`.

## Issues Encountered

- One initial server focused-test command was run outside `/opt/binance-futures-agent/app`, causing `ModuleNotFoundError: No module named 'tests'`. Re-running from the deployed app directory passed.
- One PowerShell/SSH inline JSON summarizer had quoting issues. It did not mutate server state; the same checks were rerun through base64-encoded remote scripts.

## User Setup Required

None. The server timers are active again and the latest deployed code is running under the isolated service.

## Next Phase Readiness

v1.27 is complete. The next milestone should focus on live outcome monitoring and calibration from the running v1.27 pilot, especially whether forward-paper factor blocks are too strict for `24h_momentum` under the widened capacity profile.

---
*Phase: 70-server-canary-and-manual-boundary-verification*
*Completed: 2026-06-21*
