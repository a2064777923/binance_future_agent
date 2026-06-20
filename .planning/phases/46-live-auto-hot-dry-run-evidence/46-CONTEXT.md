# Context 46: Live Auto-Hot Dry-Run Evidence

## Trigger

Phase 45 deployed optional live auto-hot scanning but deliberately left
`BFA_LIVE_AUTO_HOT_SYMBOLS=false` in the unattended server env. Before deciding
whether to ever enable it, the operator needs concrete server evidence showing
what symbols a one-shot auto-hot cycle would scan and whether top-N evaluation
still remains bounded.

## Decisions

- **D-01:** Use only one-shot dry-run/manual commands; do not start or enable
  the live timer.
- **D-02:** Override `BFA_MODE=dry_run` and `BFA_LIVE_AUTO_HOT_SYMBOLS=true`
  only in the shell command environment, not in `/etc/binance-futures-agent/env`.
- **D-03:** Record `scan_symbols`, `candidate_count`, `evaluated_symbols`,
  `submitted`, and service/timer state as evidence.
- **D-04:** Treat this as operational evidence only; it is not a profitability
  promotion or live-resume permission.

## Constraints

- No exchange order can be submitted because the run must be `dry_run`.
- No server env mutation.
- Paper timer must be restored/left active.
- Live service/timer must remain inactive.
