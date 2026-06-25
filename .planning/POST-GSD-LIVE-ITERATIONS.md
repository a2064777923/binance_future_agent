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

### 11. Protective Order Failure Was Hardened (2026-06-24)

Live trade replay (scripts/research/replay_live_trades.py) found that
protective order replacement during sentinel trailing could leave a position
naked when Binance rejected the new algo order with `-4509` (TIF GTE race).
The executor now uses a three-layer fail-closed:

1. Check if existing protective orders are still present (the trail cancel may
   have failed, leaving old SL/TP intact).
2. If missing, place fallback SL/TP at conservative prices.
3. If fallback also fails, emergency market-close the position.

A single protective failure no longer trips the global kill switch that froze
all trading. Key file: `src/bfa/execution/executor.py::_resolve_protective_order_failure`.

### 12. Trailing Stop Safety Was Fixed (2026-06-24)

`lock_r=0` placed the trailing stop exactly at entry (break-even), but
fees+slippage made break-even a guaranteed small loss. The trailing logic now
floors `lock_r` to cover at least one round-trip cost (~0.08% of entry), clamps
the lock price to stay below mark for valid geometry, and re-places the original
SL/TP as a fail-closed fallback when the trailing replacement fails. Micro
`lock_r` tightened 0.10→0.18R; trend `min_profit_r` widened 0.25→0.35R to let
trends run longer before trailing activates. Key file:
`src/bfa/ops/position_adjustment.py`.

### 13. Edge-Exhausted Trend Entries Blocked (2026-06-24)

Live replay showed trades entering at range extremes (close_position>68%)
with fading volume, then reverting. A new profile gate
`block_trend_edge_exhaustion` rejects trend entries in the exhaustion zone.
Key file: `src/bfa/strategy/setup.py::_trend_edge_exhaustion_rejections`.

### 14. Micro Wick Reversals Routed As RANGE (2026-06-24)

Wick-reversal signals now force the regime label to RANGE so they route to the
micro-grid leg instead of being misclassified as trend. Micro sentinel loss
control is now gated: it only activates after `min_profit_r` is reached or a
hard-adverse threshold is confirmed, avoiding premature cuts on micro positions.
Key files: `src/bfa/strategy/regime.py`, `src/bfa/ops/position_sentinel.py`.

### 15. ML Trend Filter + Spike-Depth Entry + Wick Filter (2026-06-24)

Research tooling added under `scripts/research/`:

- `train_trend_filter.py`: LightGBM trend-leg filter from 6 months / 23 symbols.
  Validation AUC 0.559, threshold 0.55 → 56.6% win rate, lift 1.49x over
  baseline. Model persisted to `data/research/trend_filter_v1.txt`.
- `ml_trend_filter.py`: inference + threshold gate, wired into `setup.py`
  via `use_ml_trend_filter` profile flag (defaults off; `quant_setup_ml_trend`
  backtest variant demonstrates it).
- `fetch_history.py` + `select_universe.py`: 23-symbol stratified universe
  selector and 6-month kline downloader.
- Spike-depth entry prediction (B) added to `run_micro_grid_research.py`:
  scouts recent spike depth and posts the passive entry at predicted wick depth.
- `train_wick_filter.py`: ML wick-reversal classifier (A) from real aggTrades.
  Validated on WLD 6 high-vol days: B-only 40% WR → A+B 82% WR.
- `backtest_micro_tick_precise.py`: tick-precise micro backtest using
  `TickReplaySource` so瞬時插針 are captured (1-second-bar simulation
  flattened spikes and showed false 0% WR).

### 16. State-Machine Protection Tests (2026-06-24)

`scripts/research/state_machine_full_pipeline_test.py` runs 2400 simulations
(6 market scenarios × 2 sides × 2 profiles × 100 seeds) verifying fail-closed
protection across trend/range/spike/flash-crash/stagnation dynamics. Result:
**0 protection violations, 0 naked-position events**. Trend vs micro sensitivity
profiles are independently exercised.

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

1. ~~Are micro-grid orders still mostly expiring unfilled?~~ Partially
   answered: spike-depth entry (B) posts deeper and fills more often; the
   wick filter (A) raises win rate to 82% on high-vol days. Remaining
   question: can the micro target/stop ratio be improved from ~0.38 to >0.8
   so the leg is net positive after costs?
2. ~~Are live losses concentrated in CHOP, wrong regime route, bad entry
   geometry, stale raw feed, or protection/trailing behavior?~~ Answered by
   replay: the dominant failure mode was "winning-then-reverted" (88% of
   trades hit profit at peak, 52% reverted to loss). Root cause was
   `lock_r=0` + protective-order nakedness on `-4509`. Both fixed (items 11-12).
3. ~~Does the server env enforce regime routing or only shadow it?~~ Confirmed
   enforced (`BFA_REGIME_ROUTER_SHADOW_ONLY=false`). Wick-reversal signals now
   force RANGE routing (item 14).
4. ~~Are active positions always protected within seconds after fill?~~ The
   three-layer fail-closed (item 11) now guarantees this. Verify on fresh live
   data after the 2026-06-24 deploy.
5. Is DB/raw-feed retention sufficient for later high-resolution backtests?
   Still open — DB hit 6 GB; db-maintenance timer is active.
6. The ML trend filter (`quant_setup_ml_trend`) has validation edge but is NOT
   yet the live variant. Live still runs `quant_setup_live_action_flow`. The
   ML filter needs live deployment + 200+ trades to confirm OOS edge holds.
7. The micro leg's edge on real tick data is thin (-0.054U/trade at current
   target/stop geometry). Improving the target fraction from 0.5×spike to
   0.8-1.0×spike, or restricting to only the deepest wicks, is the path to
   net-positive micro. This is the single biggest remaining improvement.

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
