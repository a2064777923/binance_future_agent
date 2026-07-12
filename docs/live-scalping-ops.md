# Live Scalping Ops Notes

For the latest server-verified scalping profile, read
`docs/current-live-strategy.md` first. This file explains the operational
pieces; the current env values can drift and must be verified on the server.

This note captures the current live micro-grid/scalping operational wiring.

## Raw Feed Coverage

Micro-grid uses `BFA_LIVE_MICRO_GRID_SECONDS_CACHE`, populated by
`binance-futures-agent-raw-feed.service`. Keep `BFA_RAW_FEED_SYMBOLS` empty in
live so `deploy/record-raw-feed-loop.sh` selects the current hot-symbol universe
from Binance 24h ticker on each recorder rotation.

Relevant env:

```bash
BFA_RAW_FEED_SYMBOLS=
BFA_RAW_FEED_AUTO_HOT_SYMBOLS=true
BFA_RAW_FEED_AUTO_HOT_TOP_N=80
BFA_RAW_FEED_AUTO_HOT_CRYPTO_ONLY=true
BFA_RAW_FEED_SECONDS_CACHE_WINDOW=1200
BFA_RAW_FEED_SECONDS_CACHE_FLUSH_SECONDS=2
BFA_RAW_FEED_WRITE_BATCH_MESSAGES=256
BFA_RAW_FEED_GZIP_COMPRESSLEVEL=3
BFA_RAW_FEED_WEBSOCKET_MAX_QUEUE=4096
```

If `BFA_RAW_FEED_SYMBOLS` is set to a fixed list, live may scan 80 symbols while
the seconds cache only covers that fixed list. The symptom is many micro-grid
rejections with `insufficient_cached_seconds`.

The recorder hot path deliberately does not JSON-decode depth messages merely
to update the trade-second cache. Raw lines are written in batches at gzip
level 3, and cache snapshots are serialized in a background thread. If one
snapshot is still being written at the next flush deadline, that redundant
flush is skipped. The cache globally evicts symbols whose latest trade second
falls outside the configured window and omits repeated `symbol` and derived
`close_time` fields from each bar; readers reconstruct both from the enclosing
symbol key and `open_time`.

Cache health has two clocks:

- `updated_at_ms` is when the recorder processed the newest trade message;
- `latest_event_time_ms` is the newest Binance trade event time in that cache.

Live micro-grid remains fail-closed when either is older than
`BFA_LIVE_MICRO_GRID_MAX_AGE_SECONDS`. This distinction matters under WebSocket
backlog: a process can be actively writing an already-delayed message, making
the receive clock look fresh while the exchange event clock is stale.

For read-only replay of self-collected ticks, first freeze symbols and time
windows without reading outcomes, then extract only those public trade events:

```bash
python scripts/prepare_self_collected_tick_replay.py \
  --raw-feed-dir /opt/binance-futures-agent/data/raw-feed \
  --symbols BTCUSDT,ETHUSDT \
  --start 2026-07-10T20:00:00Z \
  --end 2026-07-10T23:59:59.999Z \
  --output-cache-dir /opt/binance-futures-agent/runtime/self-tick-cache
```

Pass that directory to `run_micro_grid_research.py` with
`--archive-cache-only`. This flag is important: a missing local day must be
reported as missing rather than silently downloaded from the public archive.
Raw archives and extracted ticks are runtime data and must never be committed.

## Kill Switch Clearance

`BFA_KILL_SWITCH_FILE` is still the global manual kill switch checked by the
risk layer. If it exists, new live orders are rejected. Current protection
failure handling records processed failure statuses and attempts reconciliation
or fallback protection; do not assume every handled protective-order failure
automatically creates the kill switch. Clear an active kill switch only after
checking exchange-side protection:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops kill-switch-clearance \
  --env-file /etc/binance-futures-agent/env
```

Add `--execute` only when the report shows every active position has both
`STOP_MARKET` and `TAKE_PROFIT_MARKET` protection. The command archives the kill
switch file instead of deleting it in place.

## Protective Order Replacement

Binance rejects multiple same-direction `GTE + closePosition` conditional algo
orders with code `-4130`. Entry protection now handles that by cancelling
conflicting old close-position algo orders and then re-placing fresh stop-loss
and take-profit orders.

Position trailing replacement also cancels old same-side algo orders before
placing replacement protection. If old-order cancellation fails, replacement is
not attempted and the action is reported as failed so a half-protected state is
not silently created.

## Micro-grid Capacity

Base open-position capacity is controlled by `BFA_MAX_OPEN_POSITIONS`. Micro-grid
can use extra slots via:

```bash
BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS=2
```

It can also use extra same-direction notional capacity without enlarging the
trend leg:

```bash
BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT=1000
```

When micro-grid intents reach the exchange but show
`entry_order_expired_canceled`, the signal passed risk and submitted a post-only
limit order, but price did not touch the limit within
`BFA_LIVE_MICRO_GRID_ORDER_WAIT_SECONDS`.

Current live micro-grid behavior is also documented in
`docs/current-live-strategy.md`: it is a quant-only candidate path inside the
main live scan, bypasses AI, uses `RANGE` regime routing, and has corrected side
selection that favors upper-edge shorts and lower-edge longs. “Fast lane” does
not mean a deployed three-second service; the main live timer remains the
slower cycle unless the server state explicitly proves otherwise.

Pending entries now consume the same portfolio slot, direction-notional, and
margin budgets as filled positions. The available-balance reserve can also keep
capital unavailable to the trend leg while still allowing the micro-grid leg:

```bash
BFA_MIN_AVAILABLE_BALANCE_RESERVE_USDT=10
BFA_MIN_AVAILABLE_BALANCE_RESERVE_FRACTION=0.05
BFA_MICRO_GRID_RESERVED_MARGIN_USDT=20
BFA_MICRO_GRID_MAX_PENDING_ORDERS=3
BFA_MICRO_GRID_MAX_PENDING_MARGIN_USDT=40
BFA_TREND_MAX_PENDING_ORDERS=8
```

These are the reviewed live values as of 2026-07-10. The order caps are maximum
parallel pending counts, not reserved capacity: portfolio notional, same-side
notional, available balance, open-position slots, and margin checks can still
admit fewer orders. The 40 USDT micro-grid pending-margin cap also applies
across its three pending slots. Setting an order cap to zero disables that cap
and is not recommended for the live profile.

The cap does not make the current synchronous path three-way concurrent. The
main CLI executes at most one selected order per cycle, and a micro LIMIT can
wait synchronously for its 20-second TTL. A safe live implementation of three
simultaneous micro entries would need in-process fill events plus immediate
per-fill protection; the ten-second watchdog alone leaves an unacceptable
protection gap. No such batch path is enabled.

## Public Near-BBO Shadow

`scripts/run_near_bbo_shadow.py` is a separate public-market-data experiment.
It subscribes only to `bookTicker` and public trades, has no signed exchange
client, and cannot place orders. It keeps a broad watch set, evaluates every
three seconds, and admits at most three shadow intents after ranking.

The July 12 600-second run demonstrated frequency and performance, not edge:
400U shadow capital, 120U notional per intent, at most 3 active intents, 49
admitted, 12 queue-proxy fills, 0 wins, PF 0, and -1.1637U after modeled
fees/slippage. It completed 200/200 evaluations with 0 misses and 0.243ms p95
ranking latency despite two reconnects. Keep it shadow-only. Its score is an
uncalibrated heuristic, top-of-book quantity is only a queue proxy, and target
fills still lack real queue priority.

Freshness uses the later of local wall time and the newest exchange event time,
so a connected-but-silent stream ages out instead of freezing the stale-data
clock. Unknown `BFA_LIVE_MICRO_GRID_*` environment names fail config validation;
obsolete experimental knobs can no longer appear active while being ignored.

## Pending Entry Lifecycle And Quality

Deferred limits are registered in the indexed `pending_limit_entries` table.
The watchdog reads only `status='pending'`, ordered by `expires_at`, with a SQL
limit; it no longer scans and JSON-decodes the full order-intent and exchange-
response history every ten seconds.

- `NEW` before TTL remains pending.
- `NEW` after TTL is canceled and resolved as `entry_order_expired_canceled`.
- `PARTIALLY_FILLED` cancels the remainder before protecting executed quantity.
- cancel or query failure leaves the row unresolved and blocks optimistic
  cleanup.
- filled entries are protected from the shared cycle position snapshot.

When a fresh execution signal exists, an optional quality pass reuses the
already-collected market context and the shared open-orders snapshot. It adds no
per-order market API call. It marks an order for cancellation only when evidence
is explicit: a fresh opposite-side signal, price beyond the original stop, a
limit moving too far away while momentum continues away, or the persistent
flow/volume/price-acceptance combination described below.

```bash
BFA_PENDING_LIMIT_QUALITY_CHECK_ENABLED=true
BFA_PENDING_LIMIT_QUALITY_EXECUTE_ENABLED=true
BFA_PENDING_LIMIT_QUALITY_MAX_ITEMS=11
BFA_PENDING_LIMIT_QUALITY_MIN_AGE_SECONDS=5
BFA_PENDING_LIMIT_QUALITY_MAX_DISTANCE_PERCENT=0.35
BFA_PENDING_LIMIT_QUALITY_MOMENTUM_PERCENT=0.08
BFA_PENDING_LIMIT_QUALITY_TAKER_SELL_RATIO=0.85
BFA_PENDING_LIMIT_QUALITY_TAKER_BUY_RATIO=1.18
BFA_PENDING_LIMIT_QUALITY_ADVERSE_TAKER_BUY_FRACTION=0.42
BFA_PENDING_LIMIT_QUALITY_ADVERSE_MIN_WINDOWS=2
BFA_PENDING_LIMIT_QUALITY_VOLUME_EXPANSION_RATIO=1.25
BFA_PENDING_LIMIT_QUALITY_PRICE_ACCEPTANCE_RETURN_PERCENT=0.03
```

The reviewed live profile enables both flags after kill-switch deployment
validation. A new environment should begin observe-only until cancellation
reasons are reviewed. Missing context, partial fills, and ambiguous evidence
always keep the order for the normal watchdog to reconcile.

The quality pass runs on every live scan, including scans that produce no new
candidate. Ordinary adverse taker flow is no longer enough to cancel by itself:
the adverse second-level flow must persist across configured windows and be
confirmed by expanding volume plus price acceptance away from the entry.
Explicit opposite signals or a breached original stop remain independent hard
invalidation evidence. The raw seconds cache is parsed once per agent cycle and
shared between micro-grid generation and pending-quality checks.

## High-Frequency Persistence Budget

The sentinel stores current full state by upserting
`latest_states.position_sentinel:global`. A semantic state change, attempted
execution, or 300-second heartbeat writes a full `position_sentinel` event.
Unchanged state writes at most one small `position_sentinel_delta` per 60
seconds. Cooldown decisions short-circuit before K-line access, and same-symbol
positions share one K-line response within the cycle.

Decision snapshots behave similarly: the newest full payload is available in
`latest_states`, while a cycle whose semantic fingerprint is unchanged writes
`bfa_decision_snapshot_delta_v1` instead of repeating candidate and market
summaries. Defaults and retention controls are:

```bash
BFA_POSITION_SENTINEL_FULL_HEARTBEAT_SECONDS=300
BFA_POSITION_SENTINEL_DELTA_HEARTBEAT_SECONDS=60
BFA_DECISION_SNAPSHOT_COMPACT_UNCHANGED=true
BFA_DB_DECISION_SNAPSHOT_RETENTION_HOURS=72
BFA_DB_SENTINEL_EVENT_RETENTION_HOURS=168
BFA_DB_HIGH_FREQUENCY_RETENTION_BATCH_SIZE=50
BFA_DB_HIGH_FREQUENCY_RETENTION_MAX_DELETE_ROWS=100
```

SQLite migration creates `latest_states` automatically. Preview DB maintenance
before applying it. Maintenance removes stale market snapshots, decision
snapshot full/delta rows, and sentinel full/delta events within one bounded
delete budget. `--vacuum` still requires all writers to be stopped.

## Outcome Attribution

Outcome reconciliation now fetches user trades once per symbol window, prefers
the persisted exchange order ID, assigns every Binance trade ID to at most one
intent, and excludes reduce-only/position-adjustment intents. Ambiguous layered
entries remain `unreconciled` instead of guessing. This makes daily-loss and
strategy-leg performance metrics conservative rather than double counted.

## Processed Live Cycle Statuses

These statuses mean the live runner handled and recorded the exchange state for
that cycle. They should not by themselves make systemd stop future scans:

- `entry_order_expired_canceled`: post-only limit accepted, not filled within
  the wait window, and canceled.
- `entry_order_unknown_canceled`: entry status was unknown, no matching position
  was found, and cleanup succeeded.
- `entry_order_reconciled_from_position`: entry status was unknown but matching
  position risk existed, so the fill path was reconciled from the position.
- `protective_order_failed_no_position`: protection failed, but the matching
  position was already gone.
- `protective_order_failed_open`: protection failed while the matching position
  remained open. This is urgent risk evidence and needs follow-up, but it is a
  processed cycle for timer health.

`entry_order_unknown_cancel_failed` is still a true failed status. It means the
runner could not reconcile the entry state or clean it up.

## Unmatched Live Positions

If an active exchange position has no matching submitted intent, do not assume
it is safe or bot-managed. Use read-only checks first:

```bash
/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops position-hold-check \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite

/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops position-adjustment-plan \
  --env-file /etc/binance-futures-agent/env \
  --db /opt/binance-futures-agent/data/agent.sqlite
```

Classify the symbol as manual only after operator confirmation and, if needed,
add it to `BFA_MANUAL_POSITION_SYMBOLS`. If it is agent-managed but unmatched,
handle it through the explicit protection or close confirmation flow. The
pending-limit watchdog only reconciles unresolved `entry_order_pending` intents;
it cannot protect a position that never had a matching intent in the event
store.
