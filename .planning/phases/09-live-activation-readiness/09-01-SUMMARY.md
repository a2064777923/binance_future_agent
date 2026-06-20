---
phase: "09-live-activation-readiness"
plan: "09-01"
subsystem: live-activation
tags:
  - live
  - market-heat
  - openai-backoff
key-files:
  modified:
    - src/bfa/agent.py
    - src/bfa/cli.py
    - src/bfa/ops/live_status.py
    - docs/deployment.md
    - README.md
requirements-completed:
  - LVA-01
  - LVA-02
  - LVA-03
  - LVA-04
  - LVA-06
metrics:
  tests: "python -m unittest discover -s tests"
---

# Plan 09-01 Summary

## Delivered

- Added conservative market-heat fallback narratives so live cycles can produce
  candidates when Binance Square/manual/RSS sources are empty.
- Preserved OpenAI as the slow-path analyst/veto layer and added fail-closed
  timeout/backoff behavior.
- Clarified futures `notional_usdt` versus estimated initial margin in operator
  evidence.
- Added `ops live-status` evidence reporting for candidates, AI decisions,
  order intents, OpenAI backoff, and protective-order status.
- Deployed the live-capable system under `/opt/binance-futures-agent` with
  dedicated env/systemd paths and no secret values in planning docs.

## Server Evidence

- `BFA_MODE=live`, `BFA_OPENAI_ENABLED=true`,
  `BFA_REQUIRE_PROTECTIVE_ORDERS=true`, and OpenAI-compatible endpoint settings
  were configured out of band.
- `binance-futures-agent-live.timer` was enabled and active after reviewed
  one-cycle evidence.
- Candidate-driven live cycles reached OpenAI and either produced pass/no-trade
  decisions or fail-closed timeout/backoff outcomes.
- No submitted live entry was observed in the captured evidence.

## Verification

- Local unit suite passed during Phase 9 evidence capture.
- Server live health and service smoke checks succeeded without printing
  secrets.
- `ops live-status` reported `submitted_order_intents=0` and
  `lva05_complete=false`, which is expected until a live entry is submitted.

## Decision

Live timer operation can continue under the existing 100 USDT pilot caps.
Do not raise limits until a future submitted entry proves exchange-side
protective stop-loss and take-profit evidence, or fail-closed emergency handling.
