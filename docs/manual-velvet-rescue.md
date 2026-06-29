# Manual VELVETUSDT Hedge Rescue

This is an operator-directed, symbol-specific rescue monitor for the manual
`VELVETUSDT` hedge opened on 2026-06-28 Asia/Hong_Kong time. It is intentionally
separate from the normal live strategy. The underlying script is now parameterized
by `--symbol`; VELVET remains the default symbol and keeps the original service
name, state file, and log file.

## Server State

- Service: `binance-futures-agent-velvet-rescue.service`
- Script: `/opt/binance-futures-agent/app/scripts/manual_ops/velvet_rescue.py`
- Audit log: `/opt/binance-futures-agent/runtime/manual-rescue/velvet_actions.jsonl`
- State file: `/opt/binance-futures-agent/runtime/manual-rescue/velvet_state.json`
- Normal live exclusion: `BFA_MANUAL_POSITION_SYMBOLS` includes `VELVETUSDT`

## Current Policy

As of 2026-06-29, VELVET runs `--mode downtrend-long-t` because the live path
shifted from a clean range into a falling, volatile trend. The intent is to
restore the recently reduced `SHORT` at a suitable rebound/fade location, then
keep the short hedge running and use only small `LONG` probe trades to harvest
down-spike mean reversion.

Downtrend long-T rules:

- First priority: if `SHORT` is recorded in `reduced`, re-add that short only on
  a failed bounce / rebound zone. Do not chase the low.
- After the short is restored, do not reduce `SHORT` in this mode.
- Add a small `LONG` probe only on a down-spike near the 30-minute lower zone,
  with downtrend bias still active.
- The added long quantity is capped by `--max-long-to-short-ratio`; live uses
  `1.02`, so long can only be very slightly larger than short.
- Sell only the added `LONG` probe after mean reversion or a price target
  recovery. The original hedge long is not mechanically closed by this mode.
- The added `LONG` probe must not be sold below its recorded entry price. Live
  also requires `--long-probe-min-exit-profit-pct 0.18` before any probe sell,
  even when the mean-reversion zone appears to have triggered.
- Every cycle records mode diagnostics in `velvet_actions.jsonl`.

Current live service parameters:

- mode: `downtrend-long-t`
- scan interval: `10s`
- action cooldown: `30s`
- long-probe controls:
  `--long-probe-fraction 0.08 --max-long-to-short-ratio 1.02 --long-probe-min-exit-profit-pct 0.18`

## Previous Range Policy

The monitor only manages `VELVETUSDT` and only after reading the current hedge
position from Binance:

- The script maintains a rolling post-action baseline snapshot for both legs and
  total hedge PnL. New take-profit decisions are evaluated relative to that
  baseline, not only from the raw current unrealized PnL number.
- If one side produces at least `+10U` of effective profit versus the most
  recent baseline, close one third of that side. Effective profit can come
  from:
  - that leg's own U-PnL improving by `10U`, even if it is still below zero;
  - the net hedge book improving because the remaining long/short quantities
    are no longer perfectly balanced after the previous `T` action.
- Profit-side reduction is not mechanical. It also requires the price to be at
  the matching short-term extreme and show fade/bounce evidence:
  - profitable `LONG`: near the 30-minute upper zone, with pullback/fade risk;
  - profitable `SHORT`: near the 30-minute lower zone, with bounce/fade risk.
- If the profitable side is simply riding a strong one-way continuation, the
  monitor does not reduce it just because PnL is above `+10U`.
- Before reducing, the monitor caps the quantity so post-reduction hedge
  imbalance stays within `--max-imbalance-after-reduce` (`0.30` by default).
- Record the reduced side, quantity, and PnL in the state file.
- After each executed reduce/re-add action, reset the rolling baseline from the
  refreshed live Binance position snapshot so the next cycle evaluates from the
  new starting point.
- If that same side later gives back `8U` of the locked profit and price is no
  longer at a pure chase extreme, re-add the same one-third quantity.
- If a side was reduced and the market resumes strong continuation in that
  side's favor, the monitor can re-add urgently to restore hedge balance.
- Only one action is allowed per cycle.
- The cycle interval is 20 seconds and the action cooldown is 45 seconds.

The first version is deliberately conservative. It does not add size before a
side has first produced profit and been reduced.

## Commands

Start or resume:

```bash
systemctl enable --now binance-futures-agent-velvet-rescue.service
```

Stop immediately:

```bash
systemctl stop binance-futures-agent-velvet-rescue.service
```

Inspect:

```bash
systemctl status binance-futures-agent-velvet-rescue.service --no-pager
journalctl -u binance-futures-agent-velvet-rescue.service -n 120 --no-pager
tail -n 20 /opt/binance-futures-agent/runtime/manual-rescue/velvet_actions.jsonl
```

Dry-run one cycle:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=src python3 scripts/manual_ops/velvet_rescue.py --once
```

Dry-run a different symbol with the same engine:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=src python3 scripts/manual_ops/velvet_rescue.py --symbol CAPUSDT --once
```

Execute one cycle manually:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=src python3 scripts/manual_ops/velvet_rescue.py --once --execute
```
