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
- Added paper-only auto-hot symbol selection so scheduled forward-paper
  observation can scan up to 40 Binance USD-M USDT hot symbols without
  widening the live pilot trading allowlist.

## Operational Result

The project now has deployable systemd assets for repeated forward-paper
collection. These assets are isolated from live automation and are intended to
collect out-of-sample `paper_signals` and `paper_outcomes` while the strict
all-interval live gate remains blocked.

## Server Result

- Deployed to `/opt/binance-futures-agent/app`.
- Server deploy asset tests passed with `6` tests.
- Server full suite passed with `319` tests.
- Secret-safe health-check passed with network checks skipped.
- `binance-futures-agent-paper.service` and
  `binance-futures-agent-paper.timer` are installed.
- `binance-futures-agent-paper.timer` is enabled and active.
- `binance-futures-agent-live.service` and
  `binance-futures-agent-live.timer` remain `inactive`.
- First systemd-triggered paper run returned `paper_run_complete` with
  `generated_signals=0`, `skipped_signals=10`, `paper_signals=0`, and
  `paper_outcomes=0`.
- The first deployed timer used the 10-symbol live pilot allowlist. A
  follow-up local fix changes the paper service to auto-select top hot symbols
  from Binance 24h ticker data before falling back to configured paper/live
  symbols.
- The follow-up fix was deployed. Server focused tests passed with `30` tests,
  server full suite passed with `322` tests, and health-check passed with
  network checks skipped. The deployed paper unit now uses
  `--auto-hot-symbols --top-n 40`. A manual server paper run selected 40
  symbols, generated 15 paper signals, skipped 25, and left
  `order_intents=18` unchanged.

## Not Changed

- Live timer was not restored.
- Risk profile was not changed.
- No exchange order or position adjustment was executed.
- No Binance signed endpoint is required by the paper service command.

## Next

Let the paper timer collect out-of-sample evidence, then rerun recent matrix
and promotion checks before any live resume.
