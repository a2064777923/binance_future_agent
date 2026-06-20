# Summary 42-01: Forward-Paper Performance Gate

## Completed

- Added `src/bfa/ops/forward_paper_performance.py`.
- Added CLI command `ops forward-paper-performance-check`.
- The report reads existing `paper_signals` and `paper_outcomes`, migrates an
  empty database safely, and reports:
  - signal and outcome counts;
  - open paper signal count;
  - win/loss/flat counts and win rate;
  - total and average net PnL;
  - gross profit, gross loss, and profit factor;
  - worst drawdown;
  - exit reason counts;
  - per-symbol summaries;
  - latest settled outcomes.
- The gate returns `no_paper_evidence`, `insufficient_paper_evidence`,
  `keep_live_paused`, or `paper_evidence_promising`.
- Even when paper evidence is promising, the report keeps
  `live_resume_allowed=false`.
- Added focused tests for promising evidence, insufficient evidence, no
  evidence, and enough-but-bad evidence.
- Added a CLI test proving an empty database returns `no_paper_evidence` and a
  non-zero exit code.

## Operational Result

The active paper-only timer can keep collecting out-of-sample observations, and
operators now have a deterministic read-only command to judge when those paper
outcomes are strong enough to continue paper promotion discussions. It does not
restore live automation or convert paper evidence into live permission.

## Not Changed

- Live timer was not restored by this phase.
- Risk profile was not changed.
- No exchange order, close, or position adjustment was executed.
- No Binance signed endpoint is required by the performance command.

## Next

Deploy the gate, run it against the server paper database, and keep collecting
paper outcomes until the evidence is no longer `insufficient_paper_evidence`.
