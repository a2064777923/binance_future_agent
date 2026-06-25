# Position Profit Protection

This note records the live position-monitoring layer used to reduce profit giveback after an entry has filled.

## Intent Metadata

New order intents carry routing fields from the setup reasons into `intent.metadata`:

- `strategy_leg`
- `regime_label`
- `route_decision`

`position_hold_check` and `position_review` preserve these fields so the sentinel can distinguish trend positions from micro-grid/range positions. Older live positions without this metadata are still handled, but they fall back to the trend profile.

## Sentinel Logic

`position_sentinel` now evaluates each active position with recent 1m klines:

- Current profit progress: `stop_r_multiple`, `target_progress`.
- Recent MFE approximation from recent high/low path:
  - `recent_max_stop_r_multiple`
  - `recent_max_target_progress`
  - `target_progress_giveback_ratio`
- Flow weakness:
  - `volume_ratio`
  - `direction_alignment`
  - adverse short-return against the current side

The sentinel requests protective-order replacement when a protected position has meaningful current profit or recent MFE, plus one of:

- reversal score above the profile threshold
- profit giveback detected
- volume fade detected
- adverse micro reversal detected

It does not market-close positions for this protection path. It only asks `position_adjustment` to replace STOP/TAKE_PROFIT algo orders.

## Profiles

Micro-grid/range positions use fast protection, but loss-control trailing is only allowed after post-entry evidence. MFE is scoped to bars after the matched entry intent, so pre-entry spikes are not counted as profit for the active position.

- `BFA_POSITION_SENTINEL_MICRO_MIN_PROFIT_R=0.05`
- `BFA_POSITION_SENTINEL_MICRO_MIN_TARGET_PROGRESS=0.22`
- `BFA_POSITION_SENTINEL_MICRO_REVERSAL_THRESHOLD=0.46`
- `BFA_POSITION_SENTINEL_MICRO_VOLUME_FADE_RATIO=0.82`
- `BFA_POSITION_SENTINEL_MICRO_ADVERSE_RETURN_PERCENT=0.04`
- `BFA_POSITION_SENTINEL_MICRO_LOCK_R=0.18`
- `BFA_POSITION_SENTINEL_MICRO_GIVEBACK_R=0.25`
- `BFA_POSITION_SENTINEL_MICRO_TARGET_EXTENSION_R=0.20`
- `BFA_POSITION_SENTINEL_MICRO_GIVEBACK_RATIO=0.35`
- `BFA_POSITION_SENTINEL_MICRO_STAGNATION_SECONDS=150`
- `BFA_POSITION_SENTINEL_MICRO_STAGNATION_MAX_ABS_R=0.12`
- `BFA_POSITION_SENTINEL_MICRO_STAGNATION_MAX_MFE_R=0.18`
- `BFA_POSITION_SENTINEL_MICRO_INVALIDATION_ADVERSE_R=0.18`
- `BFA_POSITION_SENTINEL_MICRO_INVALIDATION_DIRECTION_ALIGNMENT=0.25`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_LOCK_R=0.0`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_GIVEBACK_R=0.18`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_MIN_SECONDS=90`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_MIN_GIVEBACK_R=0.35`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_HARD_ADVERSE_R=0.55`
- `BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_TARGET_EXTENSION_R=0.08`

Note: `lock_r` is floored to cover at least one round-trip transaction cost
(~0.08% of entry / risk_distance) so a "break-even" lock never becomes a
guaranteed small loss after fees. This floor is applied in code, not config.

Trend positions use wider protection to avoid closing too often:

- `BFA_POSITION_SENTINEL_TREND_MIN_PROFIT_R=0.35`
- `BFA_POSITION_SENTINEL_TREND_MIN_TARGET_PROGRESS=0.35`
- `BFA_POSITION_SENTINEL_TREND_REVERSAL_THRESHOLD=0.62`
- `BFA_POSITION_SENTINEL_TREND_VOLUME_FADE_RATIO=0.68`
- `BFA_POSITION_SENTINEL_TREND_ADVERSE_RETURN_PERCENT=0.10`
- `BFA_POSITION_SENTINEL_TREND_LOCK_R=0.15`
- `BFA_POSITION_SENTINEL_TREND_GIVEBACK_R=0.65`
- `BFA_POSITION_SENTINEL_TREND_TARGET_EXTENSION_R=0.75`
- `BFA_POSITION_SENTINEL_TREND_GIVEBACK_RATIO=0.55`

## Verification

Targeted local and server verification:

```bash
python -m unittest tests.test_ops_position_sentinel tests.test_ops_position_adjustment tests.test_ops_position_hold_check tests.test_ops_position_review tests.test_execution_executor tests.test_config tests.test_agent_runner
```

Expected result at deployment time: `Ran 110 tests ... OK`.

## Live Scalping Tuning

The live micro-grid leg exposes these speed controls:

- `BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS`: limit-entry wait window before the order is allowed to expire.
- `BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS`: maximum micro-grid hold window; set `0` to disable time-based position exit for micro-grid live orders.
- `BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS`: internal micro-grid path horizon used to estimate entry/TP/SL when max hold is disabled; `0` follows the max hold value, or falls back to 180 seconds when max hold is disabled.
- `BFA_LIVE_MICRO_GRID_MAX_AGE_SECONDS`: maximum raw-feed cache age before the micro-grid leg skips trading.

Current live tuning after 2026-06-24 risk expansion:

- `BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS=30`
- `BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS=0`
- `BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS=180`
- `BFA_LIVE_MICRO_GRID_MAX_AGE_SECONDS=12`
- `BFA_LIVE_MICRO_GRID_MIN_SCORE=1.05`
- `BFA_LIVE_MICRO_GRID_TOP_N=12`

This keeps micro-grid entries passive and entry-time-limited: if the limit price is not hit quickly enough, the watchdog should let it expire instead of chasing. Filled positions are no longer closed only because a fixed micro-grid hold window expired; stop-loss, take-profit, and sentinel protection remain responsible for exits.

## Micro-Grid Exit State Machine

The micro-grid leg separates exits into three states:

- Profit protection: after enough recent MFE or target progress, sentinel can replace protective orders to lock profit and keep a runner.
- Stagnation pressure: if a micro-grid position has been open for `BFA_POSITION_SENTINEL_MICRO_STAGNATION_SECONDS`, has not produced meaningful MFE, and volume/price action is fading, sentinel uses `sentinel_loss_control` to tighten the stop near mark instead of waiting indefinitely.
- Setup invalidation: if adverse R, short return, direction alignment, and volume show that the entry thesis is failing, sentinel can tighten the stop even before the position is profitable.

Loss-control does not market-close by default. It replaces protective orders with a closer stop, keeping exits exchange-side while avoiding a fixed max-hold exit.

## Latency Telemetry

Micro-grid candidates and order intents carry a latency chain:

- `micro_grid_latency.signal_time_ms`: second-bar signal timestamp.
- `micro_grid_latency.cache_updated_at_ms`: raw-feed cache freshness.
- `setup_latency.duration_ms`: candidate-to-setup calculation time.
- `ai_latency.duration_ms`: AI review time; micro-grid should show `bypassed=true`.
- `entry_submit_duration_ms`: local signed order submission duration.
- `signal_to_entry_submit_finished_ms`: total signal-to-submit delay.

These fields are persisted in decision snapshots, candidate evaluations, order intent metadata, and exchange responses where available.
