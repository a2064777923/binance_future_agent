# Summary 46-01: Live Auto-Hot Dry-Run Evidence

## Completed

- Ran a one-shot server command with shell-only overrides:
  - `BFA_MODE=dry_run`
  - `BFA_LIVE_AUTO_HOT_SYMBOLS=true`
  - `BFA_LIVE_AUTO_HOT_TOP_N=12`
  - `BFA_AI_FALLBACK_TO_QUANT_ENABLED=true`
  - `BFA_OPENAI_ENABLED=false`
- Stored the command output at
  `/opt/binance-futures-agent/runtime/live-auto-hot-dry-run-phase46.json`.
- Confirmed the command did not modify `/etc/binance-futures-agent/env`.
- Confirmed paper timer active and live timer/service inactive after the run.

## Evidence

- One-shot dry-run output:
  - `mode=dry_run`
  - `status=rejected`
  - `submitted=false`
  - `scan_symbols` selected 12 symbols:
    `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `REUSDT`, `HYPEUSDT`, `ZECUSDT`,
    `BICOUSDT`, `BTWUSDT`, `LABUSDT`, `XRPUSDT`, `WLDUSDT`, `CLUSDT`
  - `candidate_count=3`
  - `evaluated_symbols=["BTWUSDT"]`
  - `risk_reasons=["BTWUSDT:quant_only", "risk_exceeds_cap"]`
- Server env check still showed no explicit `BFA_LIVE_AUTO_HOT_*` entries and
  retained the fixed 10-symbol `BFA_MARKET_SYMBOLS` list.
- Server health-check after the dry-run returned `ok=True` and
  `BFA_LIVE_AUTO_HOT_SYMBOLS=false` from the redacted config.
- Service state after the run:
  - `binance-futures-agent-paper.timer=active`
  - `binance-futures-agent-live.timer=inactive`
  - `binance-futures-agent-live.service=inactive`

## Not Changed

- No unattended live auto-hot enablement.
- No live timer restore.
- No server env mutation.
- No risk profile, leverage, sizing, or max-position change.
- No live order, close, or position adjustment.

## Result

Phase 45's wider scan path works on the server when explicitly enabled for a
one-shot dry-run. It selected more than the fixed 10-symbol live list while
still keeping candidate evaluation bounded by `--top-n 3`; the single evaluated
candidate was rejected by risk and no order was submitted.

## Next

Continue forward-paper evidence collection and strategy calibration. Treat live
auto-hot as a controlled diagnostic capability until strategy promotion and
paper performance evidence improve.
