# Live Scalping Ops Notes

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
```

If `BFA_RAW_FEED_SYMBOLS` is set to a fixed list, live may scan 80 symbols while
the seconds cache only covers that fixed list. The symptom is many micro-grid
rejections with `insufficient_cached_seconds`.

## Kill Switch Clearance

Protective-order failures create `BFA_KILL_SWITCH_FILE` and risk rejects all new
orders. Clear it only after checking exchange-side protection:

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
