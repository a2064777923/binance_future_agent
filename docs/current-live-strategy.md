# Current Live Strategy State

This is the canonical handoff snapshot for the live Binance Futures Agent.
Historical GSD phase files remain useful for decisions, but they are not the
current live strategy contract. Verify the server before making live claims,
because timers, env caps, positions, and order intents change continuously.

## 2026-07-11 Safety Freeze And P0-P2 Review

The live and position-sentinel units were explicitly left `inactive` after the
review, and the kill switch remains present. Existing exchange positions are
operator-owned manual positions; this change set does not trail, close, resize,
or otherwise adopt them. Deploying code or migrating SQLite does not authorize
re-enabling live execution. Resume requires a separate explicit operator
instruction after read-only readiness and exchange-protection checks.

The July 3-11 order review produced three implementation layers:

- P0 fixes the protection lifecycle: a 20-second micro-grid order is polled and
  protected inline instead of entering the long deferred path; trend SL/TP and
  micro SL use `MARK_PRICE`, while micro TP uses `CONTRACT_PRICE`; identical
  protection plans are no-ops; replacement is sequential (SL first, then TP);
  and lifetime MFE/MAE is persisted in `position_excursions`.
- P1 adds the trend climax-entry guard, second-level pending-order quality,
  shared seconds-cache parsing, conservative outcome attribution, and
  shadow-only micro economics / trend early-failure diagnostics. Trend and
  micro pending caps remain 8 and 3 respectively.
- P2 separates latest state from full audit history. Unchanged sentinel cycles
  do not write a full multi-kilobyte event every five seconds; full state is
  kept in one `latest_states` row, with a 300-second full heartbeat and a
  60-second compact delta. Unchanged decision snapshots use compact deltas.
  Repeated same-cycle K-line and seconds-cache work is reused.

Micro-grid 1-second replay over three disjoint windows remained negative after
fees. The shadow economic gate reduced loss/drawdown materially in two windows
and was neutral in one, but did not establish positive expectancy; therefore
`BFA_LIVE_MICRO_GRID_COST_QUALITY_ENFORCE_ENABLED` remains `false`. Stored-live
trend counterfactuals showed the climax guard would block 0%, 14.65%, 26.18%,
and 24.80% of eligible signals across four windows. Only one attributable
closed trade was guard-hit (a `-0.3246U` loss), so the result supports a
defensive guard but is not enough to claim a proven profit uplift.

Snapshot checked from the server at `2026-07-05T12:07:56Z`
(`2026-07-05 20:07:56` Asia/Hong_Kong) before the USDC execution-preference
deploy.

## 2026-07-09 Live Reset And Limit-Wait Fix

Server inspection on `2026-07-09` found no active old rescue/paper service, but
the deployed `live.service` could be blocked by the current trend-leg
`1800s` limit-entry wait. The root cause is architectural: the live candidate
queue is serial, while the trend profile intentionally allows 30-minute GTX
entry orders. A single accepted trend candidate could therefore keep the
oneshot service in `activating` and prevent the two-minute live timer from
starting fresh scans.

Current fix:

- long-wait limit entries can be submitted and persisted as
  `entry_order_pending` instead of synchronously waiting for fill;
- `pending-limit-watchdog` is responsible for later fill detection and
  protective STOP/TAKE_PROFIT backfill;
- live env should set `BFA_LIMIT_ENTRY_DEFER_ENABLED=true` and
  `BFA_LIMIT_ENTRY_DEFER_MIN_WAIT_SECONDS=20`;
- this preserves the trend 30-minute wait contract without letting it block
  micro-grid or the next live scan.

## 2026-07-10 Pending Capacity And Quality Controls

The pending-order lifecycle now uses an indexed state table, cancels expired
entries, protects partial fills after canceling their remainder, and performs a
bounded signal-time quality check without adding per-order market API calls.
The reviewed live pending limits are:

- `BFA_TREND_MAX_PENDING_ORDERS=8`;
- `BFA_MICRO_GRID_MAX_PENDING_ORDERS=3`;
- `BFA_MICRO_GRID_MAX_PENDING_MARGIN_USDT=40`.

Eight and three are maximum parallel pending counts, not guaranteed capacity.
All ordinary portfolio, same-direction, available-balance, position-slot, and
margin checks still apply. The live profile also reserves 20 USDT of margin for
micro-grid entries and keeps 10 USDT or 5% of wallet balance available,
whichever is larger. Quality checking and quality cancellation are enabled on
the reviewed server profile; ambiguous evidence remains fail-closed and keeps
the order for watchdog reconciliation.

On the same reset, existing account positions were classified as manual by
symbol in `BFA_MANUAL_POSITION_SYMBOLS`, including `SKHYNIXUSDT`. Sentinel
dry-run evidence showed every current position as `manual_position_ignored`
with no adjustment plan. Do not remove those symbols from manual ignore unless
the operator explicitly hands them back to the bot.

## 2026-07-06 Clean Plan Override

For the next implementation pass, use
`docs/clean-fusion-plan-2026-07-06.md` as the compact strategy contract. It
overrides older GSD phase notes and older live handoff assumptions when they
conflict. In particular:

- the trend leg is treated as a `Trend Pullback Continuation` setup family,
  not a generic blended hotness vote;
- trend limit orders should use a 30-minute wait (`1800s`) with periodic thesis
  revalidation. Treat any `75s` trend-wait reference as stale historical or
  research residue unless current server code/env proves otherwise;
- micro-grid remains the range/needle mean-reversion leg and should not be
  re-described as a new EV-only strategy;
- outcome persistence is a first-class requirement because missing closed
  outcomes make live learning and forensic review unreliable.

Additional verified root cause from the `BIRBUSDT` trend sample:

- the deployed app path is a copied release, not a git checkout; compare files
  or deploy explicitly instead of assuming `git status` on the server app path;
- old code could write pending-limit watchdog `submitted` rows for sibling
  ladder orders whose Binance query was still `NEW` with `executedQty=0`;
- outcome reconciliation must use the original pending intent time for
  watchdog-filled limits and must skip historical watchdog rows whose own query
  proves they were not filled.
- the positive `BIRBUSDT` sample around `2026-07-05 20:30`
  Asia/Hong_Kong still needs explicit outcome reconciliation because the local
  outcome table observed during this pass was incomplete after
  `2026-07-05T12:30:31Z`.
- server evidence for that sample is precise: `trc` filled, while sibling
  `trm` and `tra` were still `NEW` with `executedQty=0`. Old watchdog behavior
  wrote all three as submitted, which can pollute both protection handling and
  outcome learning.
- current local branch does not expose a named `trend_entry_ladder_*`
  generator in source search, despite those reason codes existing in server
  history. Treat that as a deployment/local-code drift risk until reconciled.

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
  hotfix, the 2026-06-26 trend near-structure entry guard, and the
  2026-06-27 trend fresh-confirmation / layered protection update. Use the
  latest Git commit on this branch as the code reference.
- Live app path: `/opt/binance-futures-agent/app`.
- The live app path is a deployed copy, not a git checkout.
- Hashes of the live deployed strategy files matched the local files at the
  snapshot:
  - `src/bfa/strategy/micro_grid_live.py`
  - `scripts/run_micro_grid_research.py`
  - `src/bfa/agent.py`
  - `src/bfa/execution/risk.py`

If a future agent changes local code, deploy the changed files or run the
deployment script before claiming the server is on the same version.

Post-deploy verification for this snapshot observed `trend_profit_layer:observe`
and `trend_profit_layer_waiting` in the live position sentinel logs, confirming
that the deployed sentinel is running the layered protection code.

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

## Current Risk Profile

Selected non-secret server env values observed at the snapshot:

- `BFA_MODE=live`
- `BINANCE_USE_TESTNET=false`
- `BFA_ACCOUNT_CAPITAL_USDT=400`
- `BFA_MAX_LEVERAGE=30`
- `BFA_MAX_OPEN_POSITIONS=5`
- `BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS=2`
- `BFA_MAX_MARGIN_PER_POSITION_USDT=80`
- `BFA_MAX_RISK_PER_TRADE_USDT=40`
- `BFA_MAX_DAILY_LOSS_USDT=120`
- `BFA_MAX_PORTFOLIO_MARGIN_USDT=400`
- `BFA_MAX_PORTFOLIO_MARGIN_FRACTION=1.00`
- `BFA_MAX_PORTFOLIO_NOTIONAL_USDT=4800`
- `BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT=3200`
- `BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT=2000`
- `BFA_MAX_EFFECTIVE_NOTIONAL_USDT=2400`
- `BFA_MAX_POSITION_NOTIONAL_USDT=2400`
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
- `BTCUSDT`
- `CAPUSDT`
- `DRAMUSDT`
- `BABAUSDT`
- `KORUUSDT`
- `LABUSDT`
- `MUUSDT`
- `RKLBUSDT`
- `SAMSUNGUSDT`
- `SNDKUSDT`
- `SOLUSDC`
- `USUSDT`
- `VELVETUSDT`

Do not let those symbols block bot capacity analysis, and do not let automated
ops close or trail them unless the operator explicitly reclassifies them.

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

## USDC Execution Preference

After a candidate has passed regime routing, setup, AI/quant approval, and
sizing, the live runner now checks whether the same base asset has a tradable
USDC perpetual contract. If `BFA_PREFER_USDC_EXECUTION=true`, a `BTCUSDT`
signal may execute as `BTCUSDC` when all of these checks pass:

- the source symbol ends in `USDT`;
- the matching `...USDC` symbol exists in Binance `exchangeInfo`;
- the USDC symbol is `TRADING`, `PERPETUAL`, `quoteAsset=USDC`, and
  `marginAsset=USDC`;
- both USDT and USDC 24h tickers return positive `lastPrice`;
- the observed USDC/USDT price difference is within
  `BFA_PREFER_USDC_MAX_PRICE_DIFF_PERCENT` (default `0.35`).

When the switch is accepted, entry, stop, and target prices are scaled by the
USDC/USDT last-price ratio and then quantized through the USDC symbol filters.
If any check fails, execution falls back to the original USDT symbol. The
strategy signal remains attributable to the source symbol, while
`order_intents.intent.symbol` records the actual execution symbol.

Fields to inspect during review:

- `candidate_evaluations[].execution_symbol_preference`
- `trade_setups.setup.price_basis.execution_symbol_preference`
- `order_intents.intent.metadata.source_symbol`
- `order_intents.intent.metadata.execution_symbol`
- `order_intents.intent.metadata.execution_quote_asset`

USDT and USDC contracts for the same base asset share the duplicate-exposure
risk key, so switching quote asset cannot bypass same-symbol exposure guards.

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

### DeepSeek Trend Review Context

DeepSeek is currently a trend-leg veto overlay, not a live point generator. The
live flow first builds the deterministic `quant_setup` with entry, stop, target,
notional, route diagnostics, and sizing. DeepSeek then receives a compact JSON
packet and may either approve it by echoing the exact same fields or veto it
with `decision=pass`. If it returns changed `entry_price`, `stop_price`,
`target_price`, `notional_usdt`, or `hold_time_minutes`, validation rejects the
decision. This is intentional: direct AI point adjustment is still a research
goal, not live behavior.

Current DeepSeek-visible context includes:

- candidate market snapshot fields: 24h price change, quote volume, open
  interest and change, taker buy/sell ratio and acceleration, funding, support,
  resistance, VWAP, ATR, realized volatility, RSI, EMA fast/slow/spread, MACD
  line/signal/histogram, short-window momentum, close-position, and volume
  impulse;
- regime-router fields: `strategy_leg`, `regime_label`,
  `regime_confidence`, `regime_reason_codes`, `allowed_strategy_legs`,
  `route_decision`, and `regime_diagnostics`;
- deterministic setup fields: side, entry, stop, target, notional, hold time,
  risk/reward, stop/target distance, factor scores, factor summary,
  post-cost edge, liquidation diagnostics, fresh-trend confirmation,
  limit-entry quality, entry/stop/target basis, near-structure guard, and
  exchange min-notional/filter diagnostics;
- risk limits and dynamic sizing caps.

Current explicit gaps:

- L2/L3 order book depth, queue position, and book-ticker imbalance are not yet
  part of the DeepSeek live packet.
- On-chain data is not part of the live packet.
- External real-time news/social context is only present when narrative records
  exist; it is not a guaranteed full external feed.
- DeepSeek has no authority to mutate live order prices yet.

Near-term research target: add a shadow-only `ai_point_adjustment_suggestion`
schema that lets the model propose adjusted entry/stop/target with reasons,
while the executor still uses deterministic prices. Those suggestions should be
logged and compared against fills/outcomes before any bounded live authority is
considered.

Known current risk from live analysis: trend losses must be classified by
actual post-entry path. Some losses have been wrong direction or poor entry,
not merely tight stops. Future tuning should inspect each losing trade with
price path, setup factors, regime labels, and fill timing before changing
thresholds.

Trend limit entries now include a near-structure guard to avoid the ENAUSDT
failure pattern where the trend leg shorted near support after a large move:

- if a trend short signal is within the lower `18%` of the support/resistance
  band, the system only keeps the tiny volatility-retrace entry when breakout
  evidence is strong enough: directional momentum, micro-momentum, volume
  impulse, and taker-flow must all confirm continuation;
- otherwise it posts a higher rebound short using
  `limit_entry_anchor:support_nearby_rebound_short`, with the entry moved
  toward the configured rebound zone and the stop/target recomputed from that
  new entry;
- the long side is symmetric: if a trend long is too close to resistance
  without strong continuation evidence, it posts a lower pullback long using
  `limit_entry_anchor:resistance_nearby_pullback_long`;
- diagnostics are persisted in `price_basis.entry_basis.trend_near_structure_guard`.

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

- below `0.35R` and below `0.22` target progress, trend positions are observed
  unless they are missing protective orders;
- from the early defensive layer (`0.35R` or `0.22` target progress), sentinel
  can move protection only when risk is confirmed by profit giveback, flow fade,
  or adverse micro reversal; default lock/giveback are `0.08R` / `0.85R`;
- from the defensive layer (`0.60R` or `0.30` target progress), sentinel can
  move protection only when reversal-score, flow-fade, giveback, or adverse
  micro evidence supports it; default lock/giveback are `0.12R` / `0.75R`;
- from the strong layer (`1.00R` or `0.55` target progress), default
  lock/giveback are `0.35R` / `0.65R`.

2026-07-09 live protection fix: JUPUSDT exposed two sentinel execution breaks.
First, a confirmed trend `early_defensive`/`strong` signal could be rejected by
the older `trailing_activation_r_not_reached` gate after profit had already
started giving back; sentinel-layer activation now allows trailing when current
R is still positive and at least high enough to support the layer lock. Second,
when global `BFA_TRAILING_PROTECTION_ENABLED=false`, a position already marked
`trail_or_reduce` could fall back to `partial_take_profit`, which the sentinel
auto-action whitelist does not execute; sentinel overlay now also takes over
existing `trail_or_reduce` review items and rebuilds them as
`trail_protective_orders`. Server verification observed
`2026-07-09T02:08:06Z` JUPUSDT executing `trail_protective_orders` with
`trailing_activated_by_sentinel_layer`, stop `0.2111`, target `0.2071`, while
the 180-second trend cooldown remained active afterward.

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

## Backtest Sizing Notes

For micro-grid live-like backtests, use
`scripts/run_micro_grid_research.py --pullback-scale-mode none`. The legacy
research default `cap` treats `pullback_size_multiplier` as a hard portfolio
scale cap and produces tiny notional/margin numbers that do not match live
setup sizing. The 2026-07-06 long-window check showed that this difference is
material: the legacy cap run averaged about `0.144U` margin per micro trade,
while live-like sizing averaged about `14.92U` margin per micro trade.

The first useful live-like micro-grid quality gate tested locally was:

- `--min-net-notional-reward-percent 0.60`
- `--max-reversal-response-rate 0.70`

It improved the 2026-07-01 through 2026-07-04 standalone micro-grid run from
`-105.55U` to `+26.31U`, but PF was only `1.0685`, so treat it as a measured
guardrail, not a final proof of robust edge.

Cross-validation on two non-overlapping two-day slices showed the same
quality-v1 gate improved both slices:

- `2026-07-01..02`: baseline `-48.19U`, quality-v1 `+18.79U`;
- `2026-07-03..04`: baseline `-65.22U`, quality-v1 `+7.19U`.

Two follow-up ideas were tested and should not be enabled by default:

- target-progress trailing. It is available as an explicit research switch,
  but the tested variants improved one slice while breaking the other;
- rolling symbol quality guard with a 3-sample PF/stop-rate block. It reduced
  activity but made both slices net negative.

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
