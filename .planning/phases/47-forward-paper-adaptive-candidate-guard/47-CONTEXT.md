---
phase: 47
name: Forward-Paper Adaptive Candidate Guard
created: 2026-06-21
status: discussed
---

# Phase 47 Context: Forward-Paper Adaptive Candidate Guard

## Trigger Evidence

Fresh server forward-paper evidence on `2026-06-20` showed the current
`quant_setup_selective` `5m` paper stream is still not live-ready:

- `signal_count=157`
- `outcome_count=132`
- `win_rate=0.31818182`
- `total_net_pnl_usdt=-4.54251922`
- `profit_factor=0.60054605`
- `worst_drawdown_usdt=5.02186198`
- `live_resume_allowed=false`

Loss attribution pointed at repeatable failure groups:

- worst symbols include `GUAUSDT`, `HEIUSDT`, `BTWUSDT`, `BICOUSDT`,
  and `BEATUSDT`
- both sides are negative, with `short` worse than `long`
- `stop_loss` exits account for the largest gross loss
- weak factor/setup associations include `taker_flow_acceleration`,
  `rsi_bearish_momentum`, `taker_sell_bias`, `ema_trend_down`,
  `momentum`, `rsi_regime`, and `taker_flow`

## Decisions

- **D-01:** Add an adaptive guard that reads recent forward-paper
  `paper_signals` and `paper_outcomes` from the local event store. Do not use
  unverified social claims or AI judgment as guard evidence.

- **D-02:** The guard must be conservative and evidence-gated. If there are too
  few settled outcomes, it must return `insufficient_evidence` and leave
  candidate/setup behavior unchanged.

- **D-03:** The guard may quarantine symbols, block sides, or penalize setup
  factor reasons only when recent paper evidence for that group is negative
  enough and has enough outcomes.

- **D-04:** Apply the guard to both live/dry-run `agent run-once` candidate
  selection and paper-only `ops forward-paper-run`, so paper collection stops
  repeatedly sampling already-disqualified recent conditions.

- **D-05:** The guard is read-only with respect to exchange state, env files,
  risk profiles, timers, and orders. It reads SQLite only and returns auditable
  reasons in reports.

- **D-06:** Keep unattended live automation and live auto-hot disabled. This
  phase improves selection discipline; it does not resume live trading.

## Scope

Implement a dependency-free adaptive paper guard with:

- config defaults and validation
- a read-only guard builder from the event store
- candidate rejection/score penalty plumbing
- setup/profile guard plumbing for side/factor rejection
- forward-paper reporting of guarded/skipped symbols
- focused tests and full-suite verification

## Out Of Scope

- enabling live timers
- applying `30u_10x_multi_dynamic`
- executing position adjustments or exits
- treating this as proof of profitability
- adding heavy notification systems
