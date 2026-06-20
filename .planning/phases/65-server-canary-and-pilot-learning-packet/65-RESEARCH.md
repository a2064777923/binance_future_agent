# Phase 65 Research: Server Canary And Pilot Learning Packet

## Existing Building Blocks

- `build_exposure_status_report()` already provides the current profile,
  dynamic sizing, manual exposures, active bot exposures, entry-capacity status,
  exchange account summary, and target-profile preview.
- `build_position_review_report()` already converts active exchange positions
  into lifecycle decisions such as `manual_hold`, `hold`, `watch`,
  `trail_or_reduce`, and `close_review`.
- `build_time_exit_plan_report()` already provides current exit-plan status,
  per-position blockers, and reduce/close order candidates without submitting
  orders.
- `build_live_outcome_ledger_report()` already reports closed live outcome
  summary, attribution groups, latest outcomes, trace IDs, and
  recommendation-only guard feedback.
- `build_trade_trace_report()` reconstructs submitted-entry flow for a symbol
  or event id.

## Technical Approach

The cleanest implementation is a thin ops composition module:

1. Build the four source reports once, sharing the same signed client where
   read-only Binance evidence is enabled.
2. Pull trace IDs from ledger latest outcomes and active position review rows.
3. Fetch a bounded number of trade traces for the newest intent IDs and active
   position symbols.
4. Emit one packet object with:
   - non-mutation proof;
   - server/runtime metadata;
   - manual-symbol policy;
   - cap usage summary;
   - lifecycle summary;
   - exit summary;
   - outcome/guard summary;
   - source report payloads for drill-down.

## Pitfalls

- Do not call `reconcile_submitted_trade_outcomes()` from the packet command.
  Outcome persistence already exists in `live-outcome-ledger --reconcile
  --persist-closed`; the packet itself should remain read-only.
- Do not rely on the risk profile preview as the current truth. Use the active
  env/current profile from exposure status.
- Avoid treating manual exposures as bot capacity or bot performance evidence.
- If signed Binance evidence is unavailable or skipped, return a degraded packet
  with explicit reasons instead of raising unhandled exceptions where possible.
- Keep CLI exit code `0` for packet generation even when the packet says review
  is needed; this is an observation artifact, not a gate that should stop
  cron/systemd by itself.

## Verification Strategy

- Unit tests should use fake signed clients and fixture SQLite rows, not live
  Binance.
- CLI tests should assert JSON schema, source report presence, mutation proof,
  and nonzero/manual exposure handling.
- Server canary should run local tests, deploy, run focused server tests, run
  full server tests, generate the packet JSON, verify timers active/services
  inactive, and keep secrets redacted.
