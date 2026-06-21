---
phase: 70-server-canary-and-manual-boundary-verification
status: passed
verified_at: 2026-06-21T02:49:32Z
requirements:
  - OPS-04
  - OPS-05
  - RISK-05
---

# Phase 70 Verification

## Result

Status: passed.

The completed v1.27 code is deployed to the isolated server. Live and paper
timers are active, one-shot services are inactive, Phase 70 artifacts were
generated, the latest live canary submitted no order, and `BTWUSDT` remains
manual-only.

## Requirement Evidence

| Requirement | Status | Evidence |
|-------------|--------|----------|
| OPS-04 | Passed | Server artifacts include timer/service state, live status, exposure capacity, pilot learning packet, position review, and live-cycle explainability. Final timer state is live timer active, live service inactive, paper timer active, paper service inactive. |
| OPS-05 | Passed | Deployment used `/opt/binance-futures-agent` and `/etc/binance-futures-agent`, server tests passed, timers were restored, and artifact sensitive scan returned `finding_count=0`. |
| RISK-05 | Passed | `BFA_MANUAL_POSITION_SYMBOLS=BTWUSDT`; exposure status reports `BTWUSDT` under `manual_exposures`, `manual_position_count=1`, `active_position_count=0`; position review recommends `manual_hold` with `manual_position_ignored`. |

## Automated Checks

- Server focused tests:
  - Passed: 107 tests.
- Server full tests:
  - Passed: 420 tests.
- Server health check:
  - Passed: `ok=true`, network checks skipped.
- Server live one-shot:
  - Passed: `Result=success`, `ExecMainStatus=0`, service returned inactive.
- Final timer/service check:
  - Passed: live timer active, live service inactive, paper timer active, paper service inactive.
- Sensitive artifact scan:
  - Passed: no `sk-...`, Binance secret, DeepSeek key, OpenAI key, or password pattern in Phase 70 artifacts.

## Canary Evidence

| Artifact | Evidence |
|----------|----------|
| `/opt/binance-futures-agent/app/runtime/phase70-pilot-learning-packet.json` | `schema=bfa_pilot_learning_packet_v1`, `status=packet_ready`, `manual_symbols=["BTWUSDT"]`, mutation proof all false, `trace_count=10`. |
| `/opt/binance-futures-agent/app/runtime/phase70-exposure-status-final.json` | `current_profile_entry_capacity_available`, `entry_capacity_available`, `active_position_count=0`, `manual_position_count=1`, manual `BTWUSDT` visible as manual-only exposure in the canary artifact. |
| `/opt/binance-futures-agent/app/runtime/phase70-position-review-final.json` | `status=review_ok`, `BTWUSDT` recommendation `manual_hold`, reason `manual_position_ignored`. |
| `/opt/binance-futures-agent/app/runtime/phase70-live-cycle-final.json` | Latest cycle inspected `JUPUSDT`, `submitted=false`, with sizing caps showing dynamic sizing enabled and 500 USDT position/effective caps. |
| `/opt/binance-futures-agent/app/runtime/phase70-live-oneshot-journal.txt` | Live one-shot scanned broad hot symbols and returned `status=quant_pass`, `submitted=false`, blocked by `forward_paper_guard_factor:24h_momentum`. |
| `/opt/binance-futures-agent/app/runtime/phase70-exposure-status-final-check.json` | Final post-restore check: `active_position_count=0`, `manual_position_count=1`, manual `BTWUSDT` SHORT notional about `316.6096` USDT, manual initial margin about `31.66096` USDT, `entry_capacity_available`. |
| `/opt/binance-futures-agent/app/runtime/phase70-live-cycle-final-check.json` | Final post-restore latest cycle: `REUSDT` flat, `submitted=false`, no order intent. |

## Residual Risk

This is server deployment and boundary proof, not profitability proof. The
latest live canary declined to trade because forward-paper factor evidence
blocked the setup. The next milestone should monitor whether this guard is too
strict under current market conditions before loosening it.
