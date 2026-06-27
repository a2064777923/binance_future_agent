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

- If one side's unrealized PnL reaches `+10U`, close one third of that side.
- Record the reduced side, quantity, and PnL in the state file.
- If that same side later gives back `8U` of the locked profit and price is no
  longer at a pure chase extreme, re-add the same one-third quantity.
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
