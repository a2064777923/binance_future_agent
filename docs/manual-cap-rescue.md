# Manual CAPUSDT Hedge Rescue

This is a CAP-specific manual hedge rescue monitor. It reuses the rolling
baseline `manual_ops/velvet_rescue.py` engine but runs with separate symbol,
state, log, and systemd service settings.

## Why CAP Is Different

At deployment time, CAP was a larger two-sided losing hedge:

- `LONG`: losing, larger size than the short leg.
- `SHORT`: losing, smaller size than the long leg.
- Price was between the two entries, so both legs could be red at the same time.
- The path looked more like directional chop than VELVET's cleaner range.

For this reason, CAP must not wait for raw `upnl >= +10U`. It uses the rolling
post-action baseline and treats a leg as having usable T-profit when that leg,
or the net hedge book, has improved versus the latest baseline.

## Initial Policy

- Service: `binance-futures-agent-cap-rescue.service`
- Script: `/opt/binance-futures-agent/app/scripts/manual_ops/velvet_rescue.py`
- Symbol argument: `--symbol CAPUSDT`
- Audit log: `/opt/binance-futures-agent/runtime/manual-rescue/cap_actions.jsonl`
- State file: `/opt/binance-futures-agent/runtime/manual-rescue/cap_state.json`
- Normal live exclusion: `BFA_MANUAL_POSITION_SYMBOLS` should include `CAPUSDT`

CAP starts faster but more balance-constrained than VELVET:

- scan interval: `10s`
- improvement trigger: `6U` versus rolling baseline
- re-add trigger: `4.5U` giveback
- action cooldown: `30s`
- post-reduce imbalance cap: `0.20`

The lower trigger is intentional because CAP's oscillation is smaller and both
legs started red. The tighter imbalance cap is also intentional: if CAP trends
one way, over-cutting the improving leg can quickly turn the hedge into a
directional bet.

## Commands

Start or resume:

```bash
systemctl enable --now binance-futures-agent-cap-rescue.service
```

Stop immediately:

```bash
systemctl stop binance-futures-agent-cap-rescue.service
```

Inspect:

```bash
systemctl status binance-futures-agent-cap-rescue.service --no-pager
journalctl -u binance-futures-agent-cap-rescue.service -n 120 --no-pager
tail -n 20 /opt/binance-futures-agent/runtime/manual-rescue/cap_actions.jsonl
```

Dry-run one cycle:

```bash
cd /opt/binance-futures-agent/app
PYTHONPATH=src python3 scripts/manual_ops/velvet_rescue.py --symbol CAPUSDT --once
```
