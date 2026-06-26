# Current Live Strategy State

This is the canonical handoff snapshot for the live Binance Futures Agent.
Historical GSD phase files remain useful for decisions, but they are not the
current live strategy contract. Verify the server before making live claims,
because timers, env caps, positions, and order intents change continuously.

Snapshot checked from the server at `2026-06-26T03:10:39Z`
(`2026-06-26 11:10:39` Asia/Hong_Kong).

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
- Latest strategy commit before this doc update:
  `cb3d876 fix: route micro-grid side selection to range edges`.
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
- `BFA_ACCOUNT_CAPITAL_USDT=200`
- `BFA_MAX_LEVERAGE=30`
- `BFA_MAX_OPEN_POSITIONS=5`
- `BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS=2`
- `BFA_MAX_MARGIN_PER_POSITION_USDT=20`
- `BFA_MAX_RISK_PER_TRADE_USDT=4`
- `BFA_MAX_DAILY_LOSS_USDT=10`
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

## Trend Leg

The trend leg is the normal candidate path. It uses `strategy_leg=trend` and
`regime_label=TREND` when allowed by the router. The AI layer is a slow-path
review for trend; server env uses:

- `BFA_AI_PROVIDER=deepseek`
- `BFA_OPENAI_ENABLED=true`
- `BFA_AI_FALLBACK_TO_QUANT_ENABLED=true`

Known current risk from live analysis: trend losses must be classified by
actual post-entry path. Some losses have been wrong direction or poor entry,
not merely tight stops. Future tuning should inspect each losing trade with
price path, setup factors, regime labels, and fill timing before changing
thresholds.

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
- `BFA_LIVE_MICRO_GRID_NOTIONAL_FRACTION=1.0`

Micro-grid submits GTX/post-only limits and may expire or be canceled without a
fill. A recent intent with `entry_order_expired_canceled` or
`entry_order_unknown_canceled` can still prove that the leg scanned, routed,
risk-checked, and reached exchange handling.

Micro-grid side selection has been corrected to prefer mean-reversion geometry:

- near the upper band, short is strongly preferred and long is penalized;
- near the lower band, long is strongly preferred and short is penalized;
- EMA/center deviation adds a mean-reversion bias;
- fresh-edge checks are now a quality reduction, not a hard block;
- `entry_path_too_directional` remains a hard block in research logic.

Micro-grid entry geometry is dynamic:

- base entry edge is close to the band edge;
- flow, momentum, volatility, wick depth, and continuation pressure can push the
  limit deeper;
- the existing deeper wick-derived entry is kept when it is more conservative;
- stop and target geometry are adjusted from the same volatility/quality
  context rather than using one fixed distance.

For future diagnostics, inspect these intent reason codes and metadata:

- `dynamic_entry_*`
- `dynamic_exit_*`
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
- `BFA_POSITION_SENTINEL_EXECUTE_ENABLED=false`
- `BFA_POSITION_AUTO_MANAGEMENT_ENABLED=false`

That means the watchdog can backfill missing protection for pending limit fills
when enabled, while the sentinel currently records diagnostics/plans but does
not automatically replace trailing protection. Verify these env values before
assuming live can or cannot move protective orders.

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
