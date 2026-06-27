# Current Live Strategy State

This is the canonical handoff snapshot for the live Binance Futures Agent.
Historical GSD phase files remain useful for decisions, but they are not the
current live strategy contract. Verify the server before making live claims,
because timers, env caps, positions, and order intents change continuously.

Snapshot checked from the server at `2026-06-27T08:56:47Z`
(`2026-06-27 16:56:47` Asia/Hong_Kong) after the trend loss-control /
structure-break deploy.

## Source Of Truth Order

1. Current code in this repository.
2. Server deployment under `/opt/binance-futures-agent/app`.
3. Server env at `/etc/binance-futures-agent/env`, with secrets redacted.
4. Server SQLite DB at `/opt/binance-futures-agent/data/agent.sqlite`.
5. Binance signed account state: positions, open orders, open algo orders,
   and user trades.
6. This document and `docs/agent-handoff.md`.
7. `.planning/POST-GSD-LIVE-ITERATIONS.md`.
8. Older `.planning/phases/*` artifacts.

Do not infer current live behavior from old Phase 70 or v1.27 files without
checking the newer sources above.

## Deployment Sync

- Local branch checked during this snapshot:
  `codex/protection-degrade-hotfix`.
- This snapshot includes the 2026-06-26 spike-depth/stale-signal micro-grid
  hotfix, the 2026-06-26 trend near-structure entry guard, the 2026-06-27 trend
  fresh-confirmation / layered protection update, and the 2026-06-27
  WIF/GUSDT protection degradation hotfix. Use the latest Git commit on this
  branch as the code reference.
- Live app path: `/opt/binance-futures-agent/app`.
- The live app path is a deployed copy, not a git checkout.
- The latest changed files were copied to the deployed app path and verified by
  server-side `config-check`, a read-only `ops position-sentinel` run, and a
  subsequent systemd live cycle that exited `0/SUCCESS`:
  - `src/bfa/config.py`
  - `src/bfa/ops/position_adjustment.py`
  - `src/bfa/ops/position_sentinel.py`
  - `src/bfa/strategy/setup.py`

If a future agent changes local code, deploy the changed files or run the
deployment script before claiming the server is on the same version.

Post-deploy verification for this snapshot observed the live runner emitting
`limit_entry_anchor:resistance_nearby_pullback_long`, proving the widened
near-structure trend entry guard was active on the server. The sentinel
read-only check also loaded the new trend loss-control fields without config
errors.

## Live Services

At the snapshot, these services/timers were active:

- `binance-futures-agent-live.timer`
- `binance-futures-agent-position-sentinel.timer`
- `binance-futures-agent-pending-limit-watchdog.timer`
- `binance-futures-agent-raw-feed.service`
- `binance-futures-agent-db-maintenance.timer`

`binance-futures-agent-live.service` is a oneshot service. It can be
`inactive` after a healthy completed cycle or `activating` while a cycle is
running. Do not call live "stopped" just because the service is not continuously
active; check the timer and recent `order_intents` / `exchange_responses`.

At this snapshot the live timer was restored after debugging. A systemd-triggered
live cycle finished with `status=0/SUCCESS` at `2026-06-27 16:56:47` server
time.

## Current Risk Profile

Selected non-secret server env values observed at the snapshot:

- `BFA_MODE=live`
- `BINANCE_USE_TESTNET=false`
- `BFA_ACCOUNT_CAPITAL_USDT=200`
- `BFA_MAX_LEVERAGE=30`
- `BFA_MAX_OPEN_POSITIONS=5`
- `BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS=2`
- `BFA_MAX_MARGIN_PER_POSITION_USDT=20`
- `BFA_MAX_RISK_PER_TRADE_USDT=6`
- `BFA_MAX_DAILY_LOSS_USDT=25`
- `BFA_MAX_PORTFOLIO_MARGIN_USDT=160`
- `BFA_MAX_PORTFOLIO_MARGIN_FRACTION=0.80`
- `BFA_MAX_PORTFOLIO_NOTIONAL_USDT=2400`
- `BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT=1600`
- `BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT=1000`
- `BFA_MAX_EFFECTIVE_NOTIONAL_USDT=600`
- `BFA_MAX_POSITION_NOTIONAL_USDT=600`
- `BFA_DYNAMIC_POSITION_SIZING_ENABLED=true`
- `BFA_ADAPTIVE_SIZING_GOVERNOR_ENABLED=true`

The risk layer still calculates final size from the smallest surviving cap:
available balance, max margin, max notional, portfolio caps, stop-risk cap,
symbol filters, duplicate exposure, manual exclusions, and adaptive sizing.
Raising leverage alone does not guarantee larger margin or notional.

## Manual Positions

The live env currently excludes these manual symbols from bot position slots
and bot margin capacity:

- `BTWUSDT`
- `DRAMUSDT`
- `BABAUSDT`

Do not let those symbols block bot capacity analysis, and do not let automated
ops close or trail them unless the operator explicitly reclassifies them.

At the snapshot, Binance showed manual `BABAUSDT` and `DRAMUSDT` positions and
bot-managed crypto shorts including `PUMPUSDT`, `SUIUSDT`, and `XRPUSDT`.
This can change quickly; always re-query signed position risk before acting.

## Strategy Architecture

The live system is no longer one blended hotness score. It is a routed fusion
of two legs plus a flat state:

- `TREND`: normal trend leg. It uses regime routing, deterministic setup, risk
  gates, and DeepSeek/OpenAI-compatible AI review when enabled. It should not
  behave like a scalp leg.
- `RANGE`: micro-grid/range-reversion scalping. It is quant-only, uses recent
  raw-feed seconds, bypasses AI, and submits passive GTX limit entries.
- `CHOP`: no new entry.

Regime routing is enforced on the server:

- `BFA_REGIME_ROUTER_ENABLED=true`
- `BFA_REGIME_ROUTER_SHADOW_ONLY=false`

The route fields are persisted in candidates, setups, intents, and decision
snapshots:

- `strategy_leg`
- `regime_label`
- `route_decision`
- `regime_reason_codes`

Use those fields when analyzing a trade. Do not guess the leg from the symbol
or side.

## Data Provenance And Bias Notes

- Real Binance market data is used for normal feature extraction through
  `MarketDataCollector` and `src/bfa/strategy/features.py`.
- Micro-grid live used to be missing the same market context and previously
  injected fake-looking liquidity / tradability defaults. That path now
  receives a per-symbol market context built from the same live snapshots and
  exchange filters. Missing context is recorded as `missing_*` and may reject
  the candidate.
- `market_context_source=market_snapshots` means the field came from live
  market snapshots, not a synthetic fallback.
- `min_executable_notional_source=exchange_symbol` means the value came from
  exchange filters. `simulation_default` means a backtest / forward-paper
  assumption, not a live exchange constraint.
- Regime scores such as the `0.52` / `0.60` priors in `src/bfa/strategy/regime.py`
  are router priors, not external market measurements.
- Confidence floors such as the `0.45` base in `_confidence()` are model
  priors from feature coverage, not market data.

## Trend Leg

The trend leg is the normal candidate path. It uses `strategy_leg=trend` and
`regime_label=TREND` when allowed by the router. The AI layer is a slow-path
review for trend; server env uses:

- `BFA_AI_PROVIDER=deepseek`
- `BFA_OPENAI_ENABLED=true`
- `BFA_AI_FALLBACK_TO_QUANT_ENABLED=true`

The selected deterministic trend variant is
`BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_live_action_flow`.

Known current risk from live analysis: trend losses must be classified by
actual post-entry path. Some losses have been wrong direction or poor entry,
not merely tight stops. Future tuning should inspect each losing trade with
price path, setup factors, regime labels, and fill timing before changing
thresholds.

Trend limit entries include a near-structure anti-chase guard to avoid both the
ENAUSDT failure pattern and later live cases where trend entries drifted back
toward the middle of the band:

- if a trend short signal is in the lower half of the support/resistance band
  (`trend_near_structure_zone_percent=49`), the system only keeps the tiny
  volatility-retrace entry when breakout evidence is strong enough:
  directional momentum, micro-momentum, volume impulse, and taker-flow must all
  confirm continuation;
- otherwise it posts a higher rebound short using
  `limit_entry_anchor:support_nearby_rebound_short`, with the entry moved toward
  the configured `70%` rebound zone and the stop/target recomputed from that new
  entry;
- the long side is symmetric: if a trend long is in the upper half of the band
  without strong continuation evidence, it posts a lower pullback long using
  `limit_entry_anchor:resistance_nearby_pullback_long`, also targeting the
  `70%` pullback geometry;
- diagnostics are persisted in `price_basis.entry_basis.trend_near_structure_guard`.

The 2026-06-27 WIF/GUSDT hotfix tightened the breakout exemption. Strong
momentum/volume/taker flow alone is no longer enough to keep a tiny
`volatility_retrace` trend entry near support/resistance:

- a short near support must also have actually broken support by at least
  `trend_near_structure_breakout_min_structure_break_percent=0.03`;
- a long near resistance must also have actually broken resistance by at least
  the same threshold;
- the diagnostic is stored under
  `trend_near_structure_guard.breakout.structure_break`;
- without that real break, the setup must wait for the rebound/pullback entry
  instead of chasing the move at the edge.

This specifically addresses the GUSDT-style failure where trend saw strong
short-side flow close to support and opened short before support had truly
broken. That case should now be routed to `support_nearby_rebound_short` unless
the structure break itself is confirmed.

The ENAUSDT forensic replay that originally produced a `0.07881` short now
replays locally and on the server as a passive rebound short near `0.079588`,
with stop and target recalculated from the new entry.

Trend entries also include a fresh continuation check. A high longer-window
edge is not enough if the short-window micro momentum and taker flow have both
flipped against the proposed side. The live `quant_setup_live_action_flow`
profile enables:

- `require_fresh_trend_confirmation=true`
- `fresh_trend_micro_momentum_percent=0.08`
- `fresh_trend_taker_flow_edge=0.04`
- `fresh_trend_taker_acceleration_edge=0.04`

Diagnostics are persisted in `price_basis.fresh_trend_confirmation`. This gate
is intentionally narrow: it rejects fresh adverse micro/flow flips, but it does
not replace the broader regime router, entry-quality, or near-structure logic.

A Lorenzian Distance Classifier (LDC) trend-leg confidence modifier was
implemented on 2026-06-26 but is **dormant and NOT part of the live strategy**:
its flag defaults off, the live server still selects
`BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_live_action_flow`, and live behavior
is unchanged. Local training produced an artifact and an offline lift report
(`lift=1.0043`, `linear`, `strength=0.05`), but that lift is too thin and the
server read-only proxy-side calibration was poor: 2,717 / 16,906 recorded
setups agreed with the offline proxy side (`agreement_fraction=0.1607`) for
setups since `2026-06-20T00:00:00Z`. Therefore **do not enable
`quant_setup_ldc` live from this artifact**. It needs a retrained label/proxy
aligned with the real routed trend setup, or a stronger server-side validation,
before any testnet or live enablement.

The LDC code is deployed to the server for research tooling, but not selected
by env. When eventually enabled it would retune confidence from a kNN direction
prediction (never hard-rejecting). See
`docs/superpowers/specs/2026-06-26-lorenz-distance-classifier-design.md` and
iteration entry 13 in `.planning/POST-GSD-LIVE-ITERATIONS.md`. Do not treat
LDC as live until an operator has explicitly switched
`BFA_LIVE_QUANT_SETUP_VARIANT` to `quant_setup_ldc` and verified the server.

Actual routed-setup tick calibration was added on 2026-06-26 via
`scripts/server_actual_setup_ldc_calibration.py`. It reads `trade_setups`
read-only, labels each setup from self-collected raw trade ticks using that
setup's own limit entry / stop / target geometry, and writes JSON/CSV research
outputs. Latest server run:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=/opt/binance-futures-agent/app:/opt/binance-futures-agent/app/src \
python3 scripts/server_actual_setup_ldc_calibration.py \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --raw-feed-dir /opt/binance-futures-agent/data/raw-feed \
  --since 2026-06-26T10:00:00Z --until 2026-06-26T13:45:00Z \
  --max-setups 120 --order desc --horizon-seconds 1800 \
  --raw-file-padding-minutes 10 --raw-workers 4 \
  --out-dir /opt/binance-futures-agent/results/research/ldc_actual_latest_120_v2
```

Result: 120 latest trend setup rows, 25 limit fills, 84 no-fill, 11 no raw ticks,
5 stop-first, 0 target-first under the configured target, 19 usable LDC samples.
The tiny validation split produced only a research hint (`lift=1.75`) and must
not be treated as production evidence. Keep LDC disabled until the raw-feed
retention contains enough filled setup labels across symbols and days.

## Micro-Grid Fast Lane

Micro-grid is live and independent from AI:

- `BFA_LIVE_MICRO_GRID_ENABLED=true`
- `BFA_LIVE_MICRO_GRID_FAST_LANE_ENABLED=true`
- `BFA_LIVE_MICRO_GRID_TOP_N=12`
- `BFA_LIVE_MICRO_GRID_ORDER_TYPE=LIMIT`
- `BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS=20`
- `BFA_LIVE_MICRO_GRID_MAX_HOLD_SECONDS=0`
- `BFA_LIVE_MICRO_GRID_MODEL_HORIZON_SECONDS=180`
- `BFA_LIVE_MICRO_GRID_MAX_AGE_SECONDS=12`
- `BFA_LIVE_MICRO_GRID_MAX_SIGNAL_AGE_SECONDS=12`
- `BFA_LIVE_MICRO_GRID_NOTIONAL_FRACTION=1.0`

Micro-grid submits GTX/post-only limits and may expire or be canceled without a
fill. A recent intent with `entry_order_expired_canceled` or
`entry_order_unknown_canceled` can still prove that the leg scanned, routed,
risk-checked, and reached exchange handling.

Micro-grid side selection has been corrected to prefer mean-reversion geometry:

- near the upper band, short is strongly preferred and long is penalized;
- near the lower band, long is strongly preferred and short is penalized;
- EMA/center deviation adds a mean-reversion bias;
- the edge bias is continuous and bounded; it must not use cliff-style
  `-80` score penalties that turn a ranking cue into an uncalibrated hard ban;
- fresh-edge checks are now a quality reduction, not a hard block;
- `entry_path_too_directional` remains a hard block in research logic.

Micro-grid entry geometry is dynamic:

- base entry edge is close to the band edge;
- flow, momentum, volatility, wick depth, and continuation pressure can push the
  limit deeper;
- the existing deeper wick-derived entry is kept when it is more conservative;
- spike-depth entries may extend beyond the old `-0.36` edge floor when recent
  wick depth plus tail pressure says the next needle can overshoot further;
- stop and target geometry are adjusted from the same volatility/quality
  context rather than using one fixed distance.

SLXUSDT 2026-06-26 forensic note: the `03:54:38Z` micro-grid short was
directionally correct but geometrically too shallow. The signal saw current
price around `0.41896`, posted a short at `0.42088`, filled at `03:55:53Z`,
hit the original stop around `0.4228` at `03:56:12Z`, then spiked to `0.4280`
at `03:56:14Z` before eventually trading down through the original target
`0.41785` at `04:04:15Z`. Root cause was not "micro-grid failed to identify a
short"; it did identify the upper-wick short. The problem was that spike-depth
entry/stop estimates were later constrained by old edge/stop caps and the
candidate was still executed after roughly `49.6s` from signal to entry submit.
Current code therefore adds:

- spike-depth tail-pressure buffer for entry and stop geometry;
- dynamic entry lower bounds that can follow the spike-depth estimate instead
  of being clipped back to `-0.36`;
- stop caps that never shrink a spike-depth base stop back to an older generic
  cap;
- `BFA_LIVE_MICRO_GRID_MAX_SIGNAL_AGE_SECONDS` and an execution-time stale
  gate so stale micro-grid candidates are skipped before setup/execution.

For future diagnostics, inspect these intent reason codes and metadata:

- `dynamic_entry_*`
- `dynamic_exit_*`
- `spike_depth_*`
- `planner_*`
- `entry_edge_fraction`
- `stop_span_fraction`
- `target_span_fraction`
- `entry_taker_buy_ratio`
- `close_position_percent`
- `micro_grid_latency`

## Position Protection

Entry protection is still mandatory:

- `BFA_REQUIRE_PROTECTIVE_ORDERS=true`

After a live fill, protection is handled by:

- entry-time protective order placement in the executor;
- pending-limit watchdog for fills that occur after the main live cycle;
- position sentinel for active-position monitoring.

Current automation posture:

- `BFA_PENDING_LIMIT_WATCHDOG_ENABLED=true`
- `BFA_PENDING_LIMIT_WATCHDOG_EXECUTE_ENABLED=true`
- `BFA_POSITION_SENTINEL_ENABLED=true`
- `BFA_POSITION_SENTINEL_EXECUTE_ENABLED=true`
- `BFA_POSITION_SENTINEL_TREND_COOLDOWN_SECONDS=180`
- `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`

That means the watchdog can backfill missing protection for pending limit fills
when enabled, while the sentinel can replace existing stop/take-profit algo
orders when a protected position has enough favorable progress and reversal or
profit-giveback evidence. Verify these env values before assuming live can or
cannot move protective orders. If `BFA_POSITION_SENTINEL_EXECUTE_ENABLED=false`,
the sentinel is observe-only: it will keep logging `trail_or_backfill` plans but
will not actually move the exchange-side stop.

Trend protection is intentionally slower than micro-grid protection. The live
trend profile enforces a same-symbol/same-side cooldown of at least 180 seconds
between trend protection judgements that could move protective orders. During
that cooldown the sentinel records `trend_protection_cooldown_active` and only
observes the position. Emergency missing-protection backfill is not delayed.

Trend sentinel protection is layered:

- below `0.60R` and below `0.30` target progress, trend positions are observed
  unless they are missing protective orders;
- from the defensive layer (`0.60R` or `0.30` target progress), sentinel can
  move protection only when reversal-score, flow-fade, giveback, or adverse
  micro evidence supports it; default lock/giveback are `0.12R` / `0.75R`;
- from the strong layer (`1.00R` or `0.55` target progress), default
  lock/giveback are `0.35R` / `0.65R`.

Trend loss-control is separate from trend profit protection. It exists for
WIFUSDT-style cases where the original direction may still later work, but the
position has already deteriorated enough that waiting for the original stop can
create an outsized loss:

- it only applies to `strategy_leg=trend`;
- it requires complete exchange-side protection first (`STOP` and
  `TAKE_PROFIT`);
- default minimum elapsed time is
  `BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_MIN_SECONDS=1800`;
- it requires at least `0.55R` adverse movement, or `0.78R` hard adverse
  movement, plus reversal-risk evidence unless the hard threshold is reached;
- when active it emits `trend_degrade_loss_control_ready` and uses
  `sentinel_loss_control`, allowing a negative lock such as
  `BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_LOCK_R=-0.30`;
- ordinary profit protection still cannot move stops on a negative-R position.

This is not a scalping-style immediate stop shuffle. The trend cooldown remains
`180` seconds, and the loss-control gate is deliberately slower than micro-grid
protection.

Micro-grid remains faster. It keeps the normal profit gate
(`0.45R` or `0.35` target progress), and can bypass the old 45-second wait
after at least 20 seconds only when first-wave evidence is strong enough
(`0.65R` or `0.55` recent/current target progress). Tiny-profit noise still
observes.

2026-06-26 review: after reconciling exchange fills from
`2026-06-25T16:00:00Z`, 93 closed outcomes were available. Trend-leg outcomes
were 37 trades, 11 wins, 26 losses, net `-20.9909U`; micro-grid outcomes were
56 trades, 21 wins, 35 losses, net `-6.0623U`. The sentinel produced 13,930
`trail_or_backfill` signals in that window, including many trend signals with
`profit_r_threshold_met`, `target_progress_threshold_met`, `flow_fade_detected`,
and `reversal_risk_threshold_met`, but executed zero replacements because
`BFA_POSITION_SENTINEL_EXECUTE_ENABLED=false`. The live env was corrected to
`true` so profitable trend positions are no longer observation-only.

The same deployment review found a separate persistence issue: the event-store
SQLite connection had `PRAGMA busy_timeout=0`, so concurrent writes from the
two-minute live runner, five-second sentinel, ten-second pending-limit watchdog,
and forward-paper timer could fail immediately with `sqlite3.OperationalError:
database is locked`. The store now opens file-backed SQLite databases with WAL,
`busy_timeout=30000`, and a short retry around event writes so transient writer
contention does not abort a live trading cycle.

Protection failure statuses such as `protective_order_failed_open` are
processed live-cycle statuses so the timer can continue scanning. They are not
safe-to-ignore statuses. Check exchange algo orders and position ownership
immediately.

The kill-switch path still exists and risk rejects new orders when it is
active, but current tests assert that protective-order failure paths should not
blindly create a kill switch for every handled failure. Use
`ops kill-switch-clearance` and signed exchange evidence instead of assuming
that any protection issue halted the system.

## TradFi Perps

TradFi contracts are no longer globally filtered out by default. The live
scanner has a market-hours window:

- `BFA_LIVE_TRADFI_WINDOW_ENABLED=true`
- `BFA_LIVE_TRADFI_TIMEZONE=America/New_York`
- `BFA_LIVE_TRADFI_OPEN_TIME=09:30`
- `BFA_LIVE_TRADFI_CLOSE_TIME=16:00`
- `BFA_LIVE_TRADFI_PRE_OPEN_MINUTES=30`
- `BFA_LIVE_TRADFI_POST_CLOSE_MINUTES=60`
- `BFA_LIVE_TRADFI_WEEKDAYS_ONLY=true`

Outside that window, TradFi symbols should be skipped for liquidity/time
reasons. If Binance rejects a TradFi symbol because an agreement is missing,
that is exchange account state, not a USDT funding issue.

## Data Collection And Retention

At the snapshot:

- SQLite DB: about `6.6G`.
- Raw feed directory: about `9.5G`.
- Runtime: about `41M`.
- Logs: about `63M`.
- Raw-feed seconds cache: about `15M`.

Current data policy:

- `BFA_PERSIST_MARKET_SNAPSHOTS=false`
- `BFA_PERSIST_DECISION_SNAPSHOTS=true`
- `BFA_RAW_FEED_AUTO_HOT_SYMBOLS=true`
- `BFA_RAW_FEED_AUTO_HOT_TOP_N=80`
- `BFA_RAW_FEED_AUTO_HOT_CRYPTO_ONLY=true`
- `BFA_RAW_FEED_SECONDS_CACHE_WINDOW=1200`
- `BFA_RAW_FEED_SECONDS_CACHE_FLUSH_SECONDS=2`
- `BFA_RAW_FEED_RETENTION_HOURS=24`

Market snapshots are intentionally not persisted at full volume because the DB
was growing too fast. For later analysis, rely on decision snapshots, raw-feed
files, order intents, exchange responses, outcomes, fills, and signed
`userTrades` reconciliation.

## Recent Live Evidence At Snapshot

The latest recent intents proved that the micro-grid leg was scanning and
submitting or attempting exchange-handled limits:

- `AINUSDT`: micro-grid `RANGE`, `BUY LIMIT`, status
  `entry_order_unknown_canceled`, AI bypassed, about `9748ms`
  signal-to-execution telemetry.
- `GUSDT`: micro-grid `RANGE`, `BUY LIMIT`, status
  `entry_order_unknown_canceled`, AI bypassed, about `5030ms`
  signal-to-execution telemetry.
- `HUSDT`: micro-grid `RANGE`, `BUY LIMIT`, rejected by
  `account_available_balance_insufficient` after leverage downshift pressure.
- `PUMPUSDT`: micro-grid `RANGE`, `SELL LIMIT`, rejected by
  `duplicate_symbol_direction_exposure`.
- `SUIUSDT`: trend `TREND`, `SELL LIMIT`, submitted, AI was not bypassed.

This is a snapshot, not a performance verdict.

## How To Inspect Live Without Guessing

Use read-only checks first:

```bash
cd /opt/binance-futures-agent/app

/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops live-status \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --check-binance

/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops live-cycle-explainability \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --latest-cycles 10

/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops position-hold-check \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite
```

For per-trade forensic analysis, use the read-only helper:

```bash
python scripts/server_live_trade_forensics.py \
  --db /opt/binance-futures-agent/data/agent.sqlite \
  --raw-feed-dir /opt/binance-futures-agent/data/raw-feed \
  --since 2026-06-25T15:00:00Z \
  --until 2026-06-25T23:00:00Z \
  --pre-minutes 15 \
  --post-minutes 15 \
  --price-source public_1m \
  --out-dir /tmp/live_trade_forensics
```

The script joins outcomes, intents, setups, AI decisions, exchange responses,
fills, and minute price path. It does not place orders, call signed Binance
endpoints, or mutate SQLite.
