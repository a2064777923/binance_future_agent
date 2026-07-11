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
candidate time from 59.82s to 24.43s by rejecting before wick fitting. The
first report used the legacy 30U sizing by mistake. Corrected 400U / 30x runs
showed the development profile at 8 wins from 9 trades, PF 1.878, net +8.6226U,
but predeclared unseen validation still failed: 2 trades across 18 symbol-days,
1 win, PF 0.934, net -0.0939U, plus zero trades in the separate intraday and
higher-beta sets. A research-only reversal scout then produced 9/10 wins across
seen development/calibration data, but its newly frozen 24-symbol-day matrix
filled zero of 35 created orders. All new entry, post-fill exit, and trailing
variants remain disabled in live.

Follow-up shared-capital portfolio tests used 6-12 simultaneous symbols and
the corrected 400U caps. Across five separate periods the trade aggregate was
23 trades, 73.91% wins, PF 2.671, net +29.5696U, but 91.5% of net came from the
2026-07-03..04 window and maximum observed concurrency was one. Two unseen
ten-large-cap, two-day portfolios filled no orders. A loose 12-symbol capacity
stress generated 63 trades but degraded to 58.73% wins, PF 0.978, net -2.2960U,
and 28.9241U drawdown. This confirms sparse/symbol-specific edge rather than a
general multi-coin scalp; live remains disabled.

Operational boundary: live and sentinel remain disabled and the kill switch
remains in place. Existing positions are manual and must not be adopted by the
agent. Code deployment or DB migration is not permission to resume trading.

### 13. Market-wide micro opportunity discovery and replay parity

The operator correctly challenged the fixed-symbol conclusion: with hundreds
of futures contracts, opportunity discovery and cross-sectional competition
must be tested before making every entry gate stricter. A prior-only historical
scanner now performs a cheap all-market 5m pass, a 1m top-48 refinement, and a
top-N symbol/hour eligibility schedule before exact aggTrades are downloaded.
The frozen July 5/8/10 scan covered 528 crypto USDT perpetuals and 72 hourly
windows without using current 24h ticker ranks or future signal bars.

The follow-up also corrected research/live parity:

- exact replay CLI defaults to the live single-best order instead of a filled
  multi-layer basket;
- live and research share one micro order score;
- scheduled replay loads cross-day warmup only when required;
- one symbol cannot resubmit while its previous 20-second limit is pending or
  while its previous position remains open;
- pending lifetimes cannot leak across hourly eligibility boundaries;
- a target-progress trailing option can enforce full modeled round-trip cost,
  but remains disabled.

Strict-versus-relaxed market-ranked evidence shows blanket loosening is harmful
but not every strict sub-gate is universally useful. On July 5, strict produced
31 trades, PF 0.777, -23.4573U; removing only pullback produced PF 0.784,
-27.2864U; moving Stoch toward 70/30 produced PF 0.655, -89.3878U; full
capacity relaxation produced PF 0.478, -189.8134U. In the same relaxed run,
Stoch-plus-pullback failures were deeply negative, while adverse-flow-only
failures were positive, opposite an earlier fixed-list sample. Flow therefore
remains unchanged live and is a future regime-aware research variable.

The final frozen top-three, single-order, pending-lifecycle validation on June
27/29 and July 2 produced 41 trades, 73.17% wins, PF 1.816, +102.1110U, three
positive dates, and distributed profit. The same architecture at the current
120-second live cadence produced only one fill across a separate three-day
set. The edge is therefore evidence for a future dedicated shadow-only
three-second micro loop, not permission to restart the two-minute live system.
Queue/L2 modeling, incremental six-hour rank state, resource budgets, and
forward shadow evidence remain required.

Cost-aware profit locking raised validation wins to 82.93% but reduced net PnL
to +44.0709U and made one date negative. It stays disabled because preserving
runners matters more than manufacturing a higher win rate.

### 14. Self-collected tick parity and recorder performance

The operator proposed using the continuously collected live raw feed for the
next validation. A frozen July 10 top-three, 400U, three-second, `live_best`
comparison extracted six symbols only after fixing the schedule and time
window. Public aggTrades and 1,231,762 self-collected individual trade events
produced the same one SKL winner, including millisecond entry/exit and
+1.1912207U net PnL. Candidate order counts differed (12 public versus 10 raw),
so the sources are not interchangeable at every rejected state. One winner is
not a profitability sample.

The exercise exposed a more important operational defect. The production raw
feed had multi-second receive tails, 206 files over roughly 25 hours, repeated
ping timeouts, and 169 service restarts at inspection. The second cache retained
287 inactive symbols, JSON-decoded every depth message, rescanned expiry on
every trade, and synchronously rewrote about 21.47MB every two seconds.

The repo now globally expires inactive cache symbols, prunes active symbols at
bounded intervals, emits compact bars, batches lower-cost gzip writes, skips
depth parsing, writes cache snapshots off the event loop, and distinguishes
receive freshness from Binance event freshness. A matched 90-second `/tmp`
canary captured the same 63,012 trades as the official recorder while reducing
p95 receive-event latency from 1,053ms to -22ms (about -40ms server clock
offset) and max from 1,388ms to 85ms. Cache snapshot size fell 66%. The server
service itself was not changed.

Research now has a one-pass selected raw-trade extractor and a strict local
archive mode that cannot silently download missing public days. Signal-window
clipping also avoids irrelevant prior-day I/O. Original gzip depth remains
available for future queue/L2 work, but this replay used trades only. Live,
sentinel, and kill-switch safety state remain unchanged; no strategy flag was
promoted.

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
