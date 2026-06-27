# Manual VELVETUSDT Hedge Rescue

This is an operator-directed, symbol-specific rescue monitor for the manual
`VELVETUSDT` hedge opened on 2026-06-28 Asia/Hong_Kong time. It is intentionally
separate from the normal live strategy.

## Server State

- Service: `binance-futures-agent-velvet-rescue.service`
- Script: `/opt/binance-futures-agent/app/scripts/manual_ops/velvet_rescue.py`
- Audit log: `/opt/binance-futures-agent/runtime/manual-rescue/velvet_actions.jsonl`
- State file: `/opt/binance-futures-agent/runtime/manual-rescue/velvet_state.json`
- Normal live exclusion: `BFA_MANUAL_POSITION_SYMBOLS` includes `VELVETUSDT`

## Current Policy

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

Execute one cycle manually:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=src python3 scripts/manual_ops/velvet_rescue.py --once --execute
```
