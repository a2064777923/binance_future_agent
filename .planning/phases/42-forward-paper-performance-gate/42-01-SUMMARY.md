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

## Server Result

- Deployed to `/opt/binance-futures-agent/app`.
- Server focused tests passed with `5` tests.
- Server full suite passed with `327` tests.
- Secret-safe health-check passed with network checks skipped.
- `binance-futures-agent-live.service` and
  `binance-futures-agent-live.timer` remained `inactive`.
- `binance-futures-agent-paper.timer` was paused during deployment and restored
  afterwards.
- Latest server `ops forward-paper-performance-check --min-outcomes 20`
  returned `keep_live_paused`: `57` paper signals, `35` settled outcomes,
  `22` open paper signals, win rate `0.34285714`, total net PnL
  `-1.46500894` USDT, profit factor `0.53973765`, and worst drawdown
  `1.60719683` USDT.
- The latest gate reasons were `paper_total_net_pnl_not_above_min`,
  `paper_win_rate_below_min`, and `paper_worst_drawdown_exceeds_cap`.
- `order_intents` remained at `18` after the paper/performance checks.

## Not Changed

- Live timer was not restored by this phase.
- Risk profile was not changed.
- No exchange order, close, or position adjustment was executed.
- No Binance signed endpoint is required by the performance command.

## Next

Keep collecting paper outcomes and recalibrate the setup before live resume:
current forward-paper performance is negative enough to keep live paused.
