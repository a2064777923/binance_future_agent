# Summary 41-01: Forward-Paper Scheduling Assets

## Completed

- Added `deploy/systemd/binance-futures-agent-paper.service`.
- Added `deploy/systemd/binance-futures-agent-paper.timer`.
- Extended `deploy/remote-bootstrap.sh` to install paper systemd assets under
  `/etc/systemd/system`.
- Kept bootstrap deployment passive: it installs units and reloads systemd, but
  does not enable, start, or restart paper or live timers.
- Updated deployment docs with paper-only manual service and timer commands.
- Updated deployment asset tests to verify the paper service uses
  `ops forward-paper-run` and not `agent run-once`.

## Operational Result

The project now has deployable systemd assets for repeated forward-paper
collection. These assets are isolated from live automation and are intended to
collect out-of-sample `paper_signals` and `paper_outcomes` while the strict
all-interval live gate remains blocked.

## Not Changed

- Live timer was not restored by this local work.
- Risk profile was not changed.
- No exchange order or position adjustment was executed.
- No Binance signed endpoint is required by the paper service command.

## Next

Deploy the assets to `/opt/binance-futures-agent/app`, verify that the live
timer remains inactive, then optionally enable only
`binance-futures-agent-paper.timer` for scheduled observation.
