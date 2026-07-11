# Post-GSD Live Iterations

**Created:** 2026-06-24
**Purpose:** Record live strategy and operations work that happened after the
formal GSD v1.27 phase artifacts were closed.

## Why This Exists

The formal GSD process currently ends at v1.27 Phase 70. Those artifacts are
historically useful, but they are not the full current state of the project.
After Phase 70, the live system continued to evolve through direct operator
feedback, server debugging, live order observations, micro-grid/scalping
research, and safety fixes.

Any future agent must treat this file, the current code, and the live server
state as newer than `.planning/phases/70-*` and the v1.27 roadmap text.

## Snapshot Boundary

- Last formal GSD phase closeout: v1.27 Phase 70.
- Phase 70 server deployment referenced commit: `7a55ece`.
- Post-GSD commits now on `main` include:
  - `c0cdfe1 feat(live): add trailing protection and spike reversal signals`
  - `4fc0539 feat(live): add regime routed scalping operations`
- Current GitHub branch after push: `main` at `4fc0539`.

The phase files do not explain all behavior added by `c0cdfe1` and `4fc0539`.

## Current Source Of Truth

Use this precedence when continuing work:

1. Current code and tests in `main`.
2. Current live server evidence from `/opt/binance-futures-agent/app`,
   `/etc/binance-futures-agent/env`, Binance account state, and the SQLite DB.
3. This post-GSD iteration log.
4. `docs/agent-handoff.md`, `docs/live-scalping-ops.md`, and
   `docs/position-profit-protection.md`.
5. Historical `.planning/phases/*` artifacts.

The phase artifacts are still valuable for why the system was built, but they
are stale for the latest live strategy shape.

## Major Post-GSD Changes

### 1. Regime Router Was Added

The live strategy moved away from one blended scoring surface toward a regime
router:

- `TREND` allows the normal trend leg.
- `RANGE` allows micro-grid and range-reversion legs.
- `CHOP` allows no new entry.

Key files:

- `src/bfa/strategy/regime.py`
- `src/bfa/agent.py`
- `tests/test_strategy_regime.py`

Important caveat: repo examples default `BFA_REGIME_ROUTER_SHADOW_ONLY=true`.
The live server env may differ. Always read `/etc/binance-futures-agent/env`
before assuming whether the route is observe-only or enforced.

### 2. Trend Leg Was Reworked

`quant_setup_live_action_flow` is no longer meant to behave like a short
scalping leg. In current backtest/profile code it is a cleaner trend leg:

- trend alignment required
- counter-signal disabled
- orderly-range logic disabled for this leg
- higher risk/reward target
- wider target multiplier
- longer time-exit window
- time exit should only apply when the position is not profitable
- trailing activation and giveback are wider than the scalping profiles

Key files:

- `src/bfa/backtest/models.py`
- `src/bfa/strategy/setup.py`
- `tests/test_strategy_setup.py`

Do not infer trend-leg behavior from older GSD descriptions that still talk
about a thin hotness score or very short exits.

### 3. Micro-Grid / Scalping Leg Was Added To Live Flow

Micro-grid is now a first-class candidate source. It consumes recent raw feed
seconds, builds post-only limit entries, and bypasses the AI layer as a
quant-only leg.

Key files:

- `src/bfa/strategy/micro_grid_live.py`
- `src/bfa/market/raw_feed_recorder.py`
- `deploy/record-raw-feed-loop.sh`
- `deploy/systemd/binance-futures-agent-raw-feed.service`
- `tests/test_strategy_micro_grid_live.py`
- `tests/test_raw_feed_recorder.py`

Important caveats:

- Repo example env may set `BFA_LIVE_MICRO_GRID_ENABLED=false`; the live server
  may set it differently.
- `BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS=0` disables micro-grid time exit while
  keeping pending limit wait behavior.
- Most live micro-grid attempts observed during debugging were valid
  post-only orders that expired unfilled, not strategy candidates blocked before
  exchange submission.

### 4. Extra Micro-Grid Capacity Was Added

The user wanted trend positions not to fully crowd out scalping. The system now
has separate knobs:

- `BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS`
- `BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT`

Key files:

- `src/bfa/agent.py`
- `src/bfa/execution/risk.py`
- `src/bfa/config.py`
- `tests/test_execution_risk.py`

These are not proof that more scalping risk is profitable. They only provide
capacity so the leg can be observed live.

### 5. Protective Order Replacement Was Hardened

Live investigation found Binance can reject duplicate same-direction
`GTE + closePosition` algo orders with error `-4130`. The execution layer and
position-adjustment flow now cancel old same-side close-position algo orders
before replacing SL/TP protection.

Key files:

- `src/bfa/execution/executor.py`
- `src/bfa/ops/position_adjustment.py`
- `tests/test_execution_executor.py`
- `tests/test_ops_position_adjustment.py`

Important behavior: cancellation happens before replacement. If old protection
cannot be canceled, replacement is not attempted. Older tests or notes that
expect "new protection first, cancel old later" are stale.

### 6. Pending Limit Watchdog Was Added

The user observed that a limit entry can fill after submission and must be
protected immediately, not only when the next new-order cycle happens. A
pending-limit watchdog now checks pending entry intents and backfills
protection when a fill is detected.

Key files:

- `src/bfa/ops/pending_limit_watchdog.py`
- `deploy/systemd/binance-futures-agent-pending-limit-watchdog.service`
- `deploy/systemd/binance-futures-agent-pending-limit-watchdog.timer`
- `tests/test_ops_pending_limit_watchdog.py`

This is critical for live safety. Do not disable it casually.

### 7. Position Sentinel Was Added

The live system now has a position sentinel for active position monitoring. It
separates micro-grid and trend thresholds so a scalp can protect small profit
faster while a trend position can tolerate more movement.

Key files:

- `src/bfa/ops/position_sentinel.py`
- `deploy/systemd/binance-futures-agent-position-sentinel.service`
- `deploy/systemd/binance-futures-agent-position-sentinel.timer`
- `docs/position-profit-protection.md`
- `tests/test_ops_position_sentinel.py`

Important caveat: sentinel behavior is env-driven. Check
`BFA_POSITION_SENTINEL_*` values on the server before judging live behavior.

### 8. Raw Feed Coverage And DB Maintenance Were Added

The raw feed originally covered too few symbols while live scanning widened to
many hot symbols. Raw feed selection now supports auto-hot crypto USDT symbol
selection, and DB maintenance exists to prevent uncontrolled SQLite/raw-feed
growth.

Key files:

- `scripts/select_raw_feed_symbols.py`
- `src/bfa/market/raw_feed_recorder.py`
- `src/bfa/ops/db_maintenance.py`
- `deploy/systemd/binance-futures-agent-db-maintenance.service`
- `deploy/systemd/binance-futures-agent-db-maintenance.timer`
- `docs/live-scalping-ops.md`

Important tradeoff: disabling heavy `market_snapshots` persistence reduces DB
growth, but later analysis may need raw feed or decision snapshots instead.
Check data availability before promising detailed post-trade analysis.

### 9. Research And Backtest Scripts Were Added Outside GSD Phases

Several research scripts were written while iterating on the range/scalping
strategy. They are not fully represented in the GSD phase plan:

- `scripts/run_micro_grid_research.py`
- `scripts/run_limit_range_research.py`
- `scripts/run_orderly_range_research.py`
- `scripts/run_feature_label_research.py`
- `scripts/run_second_agg_compound_backtest.py`
- `scripts/run_strategy_fusion_replay.py`
- `scripts/run_hftbacktest_micro_grid.py`
- `scripts/run_hftbacktest_l2_micro_grid.py`
- `src/bfa/backtest/hft_adapter.py`

Do not treat old phase matrix results as the latest evaluation of these
scripts. Re-run the relevant scripts with current code and current data when a
strategy conclusion matters.

### 10. Handoff Documentation Was Added

The GitHub handoff now includes:

- `docs/agent-handoff.md`
- `docs/live-scalping-ops.md`
- `docs/position-profit-protection.md`

These docs are newer than the GSD phase files. They are concise on purpose and
should be read before starting implementation.

### 11. Pending-Order Lifecycle, Risk, And Attribution Were Hardened

The live audit on 2026-07-10 found that deferred `NEW` limit orders could remain
open until their long strategy TTL, while the watchdog only observed them. It
also found that pending orders were missing from risk state, daily realized PnL
was not wired into live risk, and symbol/time-window outcome reconstruction
could reuse the same exchange trades for more than one intent.

The corrective implementation adds:

- indexed `pending_limit_entries` state with expiry-ordered bounded reads;
- TTL cancellation and partial-fill remainder cancellation before protection;
- signal-time pending-order quality checks using shared market/exchange data;
- pending slot, notional, direction, and initial-margin accounting;
- independent available-balance and micro-grid margin reserves;
- current-day outcome PnL in the live risk snapshot;
- exchange-order-ID-first, trade-ID-unique outcome attribution;
- a wick walk-forward fill prerequisite so unfilled paths cannot earn profit;
- one shared live exchange snapshot for risk, watchdog, position review, and
  signal-time quality checks.

Quality execution and new reserve/cap values remain env controlled. A deploy
must keep the kill switch in place until migration, watchdog, readiness,
protection, and open-entry checks pass.

The reviewed server profile deployed on 2026-07-10 enables signal-time quality
checking/cancellation and uses `BFA_MICRO_GRID_MAX_PENDING_ORDERS=3` plus
`BFA_TREND_MAX_PENDING_ORDERS=8`. These are leg-specific upper bounds only;
portfolio, direction, balance, position-slot, and margin guards remain in
force. Micro-grid pending initial margin is additionally capped at 40 USDT.

### 12. 2026-07-11 Trade Review P0-P2

The operator paused live and requested a full order/strategy review focused on
unfilled 20-second micro orders, stale 30-minute trend limits, poor entry
geometry, early failure recognition, profit runners, and server overhead.

Implemented results:

- micro-grid inline fill/protection and leg-specific trigger working types;
- sequential SL-first protection replacement, no-op identical plans, lifetime
  MFE/MAE, and confirmed-execution cooldowns;
- trend climax guard using actual planned entry position plus at least two of
  volume, taker flow, momentum, and flow-acceleration confirmation;
- pending quality on every scan, with persistent adverse flow + volume
  expansion + price acceptance required for ordinary flow cancellation;
- shared seconds-cache parsing, 8 trend pending / 3 micro pending caps, and
  shadow-only micro economic and trend early-failure models;
- latest-state upserts, compact unchanged decision/sentinel deltas, bounded
  full-event retention, same-cycle K-line reuse, and cooldown API short-circuit.

Research boundary: three micro-grid replay windows remained net negative. The
economic gate improved two and was neutral in one, so it stays shadow-only.
Four stored-live trend windows show meaningful signal reduction from the climax
guard, but only one closed attributable guard-hit outcome was available. Do not
describe either model as proven profitable.

The 2026-07-11 scalping audit corrected passive-fill direction, maker/taker cost
gates, sparse-tick horizon exits, millisecond ordering, and intraday research
windows. Dynamic Stoch/flow confirmation reduced the same MAGMA research run's
candidate time from 59.82s to 24.43s by rejecting before wick fitting. A
development profile reached 8 wins from 9 trades, but failed predeclared unseen
validation: 2 trades across 18 symbol-days, 1 win, PF 0.988, net -0.0006U, plus
zero trades in the separate intraday and higher-beta sets. The confirmation,
post-fill exit, and research trailing variants remain disabled in live.

Operational boundary: live and sentinel remain disabled and the kill switch
remains in place. Existing positions are manual and must not be adopted by the
agent. Code deployment or DB migration is not permission to resume trading.

## Live Server Notes

Known deployment shape:

- App root: `/opt/binance-futures-agent`
- App checkout: `/opt/binance-futures-agent/app`
- Python: `/opt/binance-futures-agent/.venv/bin/python`
- Env: `/etc/binance-futures-agent/env`
- DB: `/opt/binance-futures-agent/data/agent.sqlite`
- Runtime: `/opt/binance-futures-agent/runtime`

Before making live claims, run read-only checks on the server:

```bash
cd /opt/binance-futures-agent/app
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops live-status \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --check-binance

/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops kill-switch-clearance \
  --env-file /etc/binance-futures-agent/env
```

Never rely only on `.planning/STATE.md` for live positions, current caps, kill
switch state, open orders, or service/timer state.

## Current Open Questions For Next Work

1. Are micro-grid orders still mostly expiring unfilled? If yes, analyze entry
   distance, post-only repricing, wait time, and immediate post-cancel price
   path before loosening risk.
2. Are live losses concentrated in `CHOP`, wrong regime route, bad entry
   geometry, stale raw feed, or protection/trailing behavior?
3. Does the server env enforce regime routing or only shadow it? Decide based
   on current live outcome attribution, not phase docs.
4. Are active positions always protected within seconds after fill? Verify with
   pending-limit watchdog and exchange algo-order evidence.
5. Is DB/raw-feed retention sufficient for later high-resolution backtests?
6. Should the next formal GSD milestone be v1.28 "Post-GSD Live Strategy
   Consolidation" to convert these ad hoc iterations into planned phases?

## Guidance For Future Agents

- Start by reading this file and `docs/agent-handoff.md`.
- Treat `.planning/phases/70-*` as historical, not current.
- Check live server state before changing code, env, risk caps, or services.
- Do not turn on higher live risk because capacity exists.
- Do not claim a strategy is profitable from hand-entered examples or old
  backtests. Use current code, current data, fees, slippage, fills, and
  outcome attribution.
- Commit future live iterations back into `.planning` promptly, or create a new
  GSD milestone before further broad strategy work.
