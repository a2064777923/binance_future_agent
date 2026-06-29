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

## Current Policy

- Service: `binance-futures-agent-cap-rescue.service`
- Script: `/opt/binance-futures-agent/app/scripts/manual_ops/velvet_rescue.py`
- Symbol/mode arguments: `--symbol CAPUSDT --mode trend-rescue`
- Audit log: `/opt/binance-futures-agent/runtime/manual-rescue/cap_actions.jsonl`
- State file: `/opt/binance-futures-agent/runtime/manual-rescue/cap_state.json`
- Normal live exclusion: `BFA_MANUAL_POSITION_SYMBOLS` should include `CAPUSDT`

CAP originally ran with the VELVET range-T policy. That was wrong for this
symbol's live path: CAP behaved like directional chop with a strong downward
bias, not a clean range. The old policy realized too much loss by trimming the
losing `LONG` leg merely because it had improved versus baseline.

The CAP service now uses trend rescue mode:

- scan interval: `20s`
- improvement trigger: `10U` versus rolling baseline
- re-add trigger: `8U` giveback
- action cooldown: `240s`
- post-reduce imbalance cap: `0.25`
- reduce fraction: `0.08`
- losing-leg trim net-book requirement: `+2.5U` versus the latest baseline
- error backoff: `600s`

Trend rescue mode is intentionally slower and more selective:

- In a downtrend, keep the profitable `SHORT` hedge running. Do not trim it just
  because it is green.
- In a downtrend, only trim overweight losing `LONG` exposure on a fading
  countertrend bounce, and only when the whole hedge book has improved by at
  least `2.5U` versus the latest post-action baseline.
- In an uptrend, mirror the rule: keep profitable `LONG`, and only trim
  overweight losing `SHORT` exposure on a fading pullback with the same
  net-book improvement requirement.
- In range mode, a leg must be actually profitable before it can be reduced.
- Re-add is no longer an automatic chase. It requires a pullback/bounce or
  trend invalidation signal, and exchange errors trigger a backoff instead of
  repeated immediate retries.
- Every cycle writes `decision_diagnostics` into `cap_actions.jsonl`. This is
  intentionally verbose: it records why each side did not reduce, including
  cooldown, backoff, trigger, imbalance, regime, and net-book checks.

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
