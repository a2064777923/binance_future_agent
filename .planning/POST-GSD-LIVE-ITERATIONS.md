# Post-GSD Live Iterations

**Created:** 2026-06-24
**Latest live snapshot:** 2026-06-26, see `docs/current-live-strategy.md`.
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

1. Current code and tests in the active GitHub branch.
2. `docs/current-live-strategy.md` for the latest checked live strategy and
   server snapshot.
3. Current live server evidence from `/opt/binance-futures-agent/app`,
   `/etc/binance-futures-agent/env`, Binance account state, and the SQLite DB.
4. This post-GSD iteration log.
5. `docs/agent-handoff.md`, `docs/live-scalping-ops.md`, and
   `docs/position-profit-protection.md`.
6. Historical `.planning/phases/*` artifacts.

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

### 11. Processed Live Statuses No Longer Stop The Timer

Live debugging found that several resolved execution states were being treated
as failed systemd cycles even though the runner had already handled and recorded
the exchange state. `AgentRunResult.ok` now treats these as processed cycles:

- `entry_order_expired_canceled`
- `entry_order_unknown_canceled`
- `entry_order_reconciled_from_position`
- `protective_order_failed_no_position`
- `protective_order_failed_open`

This is a service-health rule, not a risk waiver. In particular,
`protective_order_failed_open` still means an open position needs urgent
exchange-side protection review. `entry_order_unknown_cancel_failed` remains a
failed status.

Key files:

- `src/bfa/agent.py`
- `tests/test_agent_runner.py`
- `docs/deployment.md`
- `docs/live-scalping-ops.md`

### 12. Current Live Strategy Snapshot Was Consolidated

On 2026-06-26 the handoff docs were synchronized with the actual server state
after several direct live iterations. The canonical current-state doc is now:

- `docs/current-live-strategy.md`

Important current facts from that snapshot:

- `/opt/binance-futures-agent/app` is a deployed copy, not a git checkout.
- Live strategy files on the server matched the local branch by hash at the
  snapshot.
- Live routing is enforced, not shadow-only:
  `BFA_REGIME_ROUTER_ENABLED=true` and
  `BFA_REGIME_ROUTER_SHADOW_ONLY=false`.
- Micro-grid is enabled as an independent fast lane:
  `BFA_LIVE_MICRO_GRID_ENABLED=true` and
  `BFA_LIVE_MICRO_GRID_FAST_LANE_ENABLED=true`.
- Micro-grid uses AI bypass, `RANGE` routing, GTX/passive limit entries, a
  20-second wait window, and no fixed max-hold time exit.
- Current non-secret risk profile is 200U configured capital, 30x max leverage,
  5 base bot positions, 2 extra micro-grid slots, 20U max margin per position,
  4U max single-trade risk, 10U daily loss cap, and 160U portfolio margin cap.
- Manual positions are `BTWUSDT`, `DRAMUSDT`, and `BABAUSDT` and must not
  consume bot slots/caps.
- Raw feed and DB maintenance are active; market snapshots are not persisted at
  full volume, while decision snapshots and raw feed remain the main analysis
  substrate.
- Recent live order intents showed micro-grid scanning and exchange-handled
  limits; do not rely only on stale `outcomes` when diagnosing whether live is
  active.

This snapshot supersedes older planning text that says current capital is 45U,
that Phase 70 commit `7a55ece` is the latest deployed behavior, or that regime
routing is only shadow/observe.

### 13. Lorenzian Distance Classifier (LDC) Code Was Added (Dormant, NOT Live)

On 2026-06-26 an instance-based future-direction predictor was implemented as a
**trend-leg confidence modifier** and merged on branch
`codex/protection-degrade-hotfix`. It is **code-complete but dormant**: the
flag defaults off, the `quant_setup_ldc` variant is not the selected live
variant, and **live strategy behavior is unchanged**. The code has been
deployed to the server for research/calibration tooling, but the live env still
uses `BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_live_action_flow`; it is not
part of live decision-making.

Follow-up verification on 2026-06-26:

- Local research klines were fetched for 24 symbols over roughly 6 months of
  5m data.
- `scripts/research/train_ldc_classifier.py` produced
  `data/research/ldc/ldc_reference.npz` and `results/research/ldc_report.json`
  locally. Those outputs are intentionally gitignored.
- Offline report: recommended `linear` blend, `strength=0.05`, `lift=1.0043`
  on a deterministic 6,000-point validation sample. This is only a very thin
  lift.
- Cross-symbol diagnostic: same-symbol neighbor fraction was `0.05`, so the
  global kNN reference is mostly mixing symbols rather than finding
  same-symbol analogues.
- Server read-only proxy calibration:
  `n_setups=16906`, `n_agree=2717`, `agreement_fraction=0.1607` since
  `2026-06-20T00:00:00Z`.
- Release verdict: **do not enable `quant_setup_ldc` live from this artifact**.
  The offline proxy side is not a faithful stand-in for the real routed trend
  setup side.

What it does (when eventually enabled): a kNN over Lorentzian distance on a
5-feature subset predicts the future price direction; the agreement between
that prediction and the setup side retunes confidence symmetrically (aligned
lifts, opposed depresses). It never hard-rejects; the existing `min_confidence`
gate absorbs the effect. It is orthogonal to the LightGBM `ml_trend_filter`
(which predicts P(win)).

Key files:

- `src/bfa/strategy/ldc_classifier.py` - stateless inference (distance, kNN
  voting, blend modes, fail-closed `ldc_confidence_modifier`).
- `src/bfa/strategy/setup.py` - `ldc_*` profile fields, `_ldc_confidence_modifier`
  helper with live->short feature mapping, confidence-chain wiring recording
  `ldc_confidence_before`/`ldc_confidence_after`.
- `src/bfa/backtest/models.py` - `quant_setup_ldc` variant (mirrors
  `quant_setup_ml_trend`).
- `scripts/research/train_ldc_classifier.py` - offline training + lift sweep +
  cross-symbol neighbor diagnostic + `lift > 1.0` release gate.
- `scripts/server_ldc_proxy_calibration.py` - read-only server script comparing
  proxy setup side vs actual recorded setup side (two-headed release verdict).
- Design: `docs/superpowers/specs/2026-06-26-lorenz-distance-classifier-design.md`.
- Plan: `docs/superpowers/plans/2026-06-26-lorenz-distance-classifier.md`.

Release path (must be followed before any live enablement):

1. **Stage 0 (offline):** run `train_ldc_classifier.py` on real klines; the
   script gates on `lift > 1.0` with a min-passed floor. No lift -> not wired.
2. **Stage 0.5 (server, read-only):** run `server_ldc_proxy_calibration.py`
   against the live DB; high lift + low proxy-actual agreement means the lift
   was calibrated to the wrong baseline and must be discounted.
3. **Stage 2 (testnet/dry-run):** set `BFA_LIVE_QUANT_SETUP_VARIANT=
   quant_setup_ldc` only in testnet/dry-run. This is NOT a pure shadow —
   adjusted confidence changes decisions — so it cannot be "observed" on live
   with the flag on.
4. **Stage 3 (live):** explicit operator authorization only, after verifying
   the server picked up the new variant env value.

A confidence modifier is not a pure shadow mode: unlike the regime router's
`shadow_only` flag, LDC's adjusted confidence flows into `min_confidence` and
AI review and changes decisions once enabled. The `ldc_confidence_before`/
`ldc_confidence_after` diagnostics exist so the testnet LDC-on-vs-off
comparison is reconstructable from a single persisted run.

Known open item: per-symbol standardization is NOT built. The artifact records
per-point source symbols and the lift sweep emits a `cross_symbol_diagnostic`
measuring same-symbol neighbor fraction; per-symbol scaling is a
measured-conditional follow-up if that diagnostic shows neighbors spanning
other symbols' regimes.

Additional open item after server calibration: the LDC training proxy must be
rebuilt from actual recorded trend setups or a closer replay of
`build_trade_setup`, not just the sign of `kline_momentum_percent`.

### 14. Trend Fresh Confirmation And Layered Sentinel Protection

On 2026-06-27 live review showed two broad issues: trend entries could still
enter against a fresh short-window adverse move, and profitable positions were
not protected with the right timing symmetry. The fix is general and not tuned
to one symbol.

Trend setup changes:

- `quant_setup_live_action_flow` now enables
  `require_fresh_trend_confirmation`.
- A trend setup is rejected when micro momentum and taker flow both flip
  against the proposed side, or when micro momentum and taker-flow acceleration
  both flip against it.
- The rejection reason is `fresh_trend_confirmation_failed:*`; diagnostics are
  persisted under `price_basis.fresh_trend_confirmation`.

Sentinel changes:

- Trend protection is layered. It observes below `0.60R` and below `0.30`
  target progress, regardless of noisy reversal score.
- Defensive trend protection starts at `0.60R` or `0.30` target progress, uses
  default `0.12R` lock and `0.75R` giveback, and still requires reversal/fade/
  giveback evidence.
- Strong trend protection starts at `1.00R` or `0.55` target progress, uses
  default `0.35R` lock and `0.65R` giveback.
- The existing 180-second same-symbol/same-side trend cooldown remains.
- Micro-grid can protect a first profitable wave after 20 seconds only when
  current/recent MFE is at least `0.65R` or `0.55` target progress. Tiny
  profitable noise still observes.

Key files:

- `src/bfa/strategy/setup.py`
- `src/bfa/backtest/models.py`
- `src/bfa/ops/position_sentinel.py`
- `src/bfa/ops/position_adjustment.py`
- `tests/test_strategy_setup.py`
- `tests/test_ops_position_sentinel.py`
- `docs/current-live-strategy.md`
- `docs/position-profit-protection.md`

### 15. Trend Structure Entry Anti-Chase Widening

On 2026-06-27 a live review showed that the near-structure guard was present,
but it only acted inside the outer `18%` of the support/resistance band. Trend
orders in the middle-to-upper or middle-to-lower band could still use the tiny
`volatility_retrace` entry and appear to open in the middle. The live
`quant_setup_live_action_flow` profile now uses:

- `trend_near_structure_zone_percent=49`
- `trend_near_structure_rebound_zone_percent=70`

This means a trend short in the lower half must wait for a higher structural
rebound unless all breakout checks pass, and a trend long in the upper half
must wait for a lower structural pullback unless all breakout checks pass.
Diagnostics remain under `price_basis.entry_basis.trend_near_structure_guard`.
The regression tests cover both previous edge cases and the new middle-band
anti-chase behavior.

## Live Server Notes

Known deployment shape:

- App root: `/opt/binance-futures-agent`
- App checkout: `/opt/binance-futures-agent/app`
- Python: `/opt/binance-futures-agent/.venv/bin/python`
- Env: `/etc/binance-futures-agent/env`
- DB: `/opt/binance-futures-agent/data/agent.sqlite`
- Runtime: `/opt/binance-futures-agent/runtime`

The live app directory should be treated as a deployed copy. Check file hashes
or redeploy from Git before assuming server code equals the local branch.

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
