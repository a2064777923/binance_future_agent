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
- Symbol/mode arguments: `--symbol CAPUSDT --mode uptrend-short-t`
- Audit log: `/opt/binance-futures-agent/runtime/manual-rescue/cap_actions.jsonl`
- State file: `/opt/binance-futures-agent/runtime/manual-rescue/cap_state.json`
- Normal live exclusion: `BFA_MANUAL_POSITION_SYMBOLS` should include `CAPUSDT`

CAP originally ran with the VELVET range-T policy. That was wrong for this
symbol's live path: CAP behaved like directional chop with a strong downward
bias, not a clean range. The old policy realized too much loss by trimming the
losing `LONG` leg merely because it had improved versus baseline.

As of 2026-06-30, CAP uses `uptrend-short-t` mode because the live path rallied
after the previous down/chop rescue sequence. The old generic `trend-rescue`
state machine had a failure mode: a reduced `LONG` could remain in
`waiting_readd` while the symbol flipped to `UP`, blocking useful short-T
actions as the short leg's loss expanded.

The CAP service now uses uptrend short-T mode:

- scan interval: `10s`
- improvement trigger: `10U` versus rolling baseline
- re-add trigger: `8U` giveback
- action cooldown: `30s`
- post-reduce imbalance cap: `0.25`
- reduce fraction: `0.08`
- losing-leg trim net-book requirement: `+2.5U` versus the latest baseline
- short probe fraction: `0.08`
- max short/long ratio after probe: `1.02`
- short probe minimum exit profit buffer: `0.18%`
- error backoff: `600s`

Uptrend short-T mode scans quickly, but action still requires a strict setup:

- The profitable/leading `LONG` hedge is protected. This mode does not
  mechanically reduce the long leg during a rally.
- If an old reduced `LONG` exists, it can be restored on a stable pullback, but
  that stale state no longer blocks short-T probes at the upper edge.
- Short-T probes are small, bounded adds to the `SHORT` side only at upper
  spikes or high 30/120 minute range position with enough momentum/volume.
- The short probe is bought back only after mean reversion and only when the
  current price is at least `0.18%` better than the probe entry. This prevents
  the CAP/V​​ELVET failure mode where a probe was closed below its own entry.
- If a short probe is already open, exiting that probe has priority over
  restoring an old reduced long. A profitable probe should not be left exposed
  just because another recovery action is also allowed.
- A second short probe is not layered on while the first short probe is still
  pending exit.
- The short side is allowed to exceed the long side only very slightly
  (`max_short_to_long_ratio=1.02`) so the rescue does not destroy the hedge if
  CAP keeps trending upward.
- Exchange errors trigger a backoff instead of repeated immediate retries.
- Every cycle writes `decision_diagnostics` into `cap_actions.jsonl`. This is
  intentionally verbose: it records why each side did not reduce, including
  cooldown, backoff, probe stage, regime, and guard checks.

## 2026-06-30 Live Status

The server service was restarted at about `2026-06-30 07:41 CST` with:

```bash
--symbol CAPUSDT --mode uptrend-short-t --execute --interval 10 \
  --cooldown-seconds 30 --short-probe-fraction 0.08 \
  --max-short-to-long-ratio 1.02 --short-probe-min-exit-profit-pct 0.18
```

Observed immediately after deployment:

- The old stale reduced `LONG` state was restored on a stable pullback, so the
  previous `trend-rescue` deadlock is cleared.
- One short-T loop added a bounded `SHORT` probe near `0.02867` and bought it
  back near `0.02857` only after the `0.18%` profit buffer was satisfied.
- The current log shape should show stages such as `add_short_probe`,
  `buy_back_short_probe`, and `restore_long_if_stable`; it should no longer
  show generic `trend-rescue` reduce/readd decisions for CAP.

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
