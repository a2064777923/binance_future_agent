# Verification 46: Live Auto-Hot Dry-Run Evidence

## Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | One-shot server evidence uses dry-run mode with live auto-hot enabled only for the command. | VERIFIED | Command output recorded `mode=dry_run`, `scan_symbols` count 12, and `submitted=false`. |
| 2 | Evidence records scan/evaluation bounds. | VERIFIED | Output recorded `candidate_count=3`, `evaluated_symbols=["BTWUSDT"]`, and `risk_reasons=["BTWUSDT:quant_only","risk_exceeds_cap"]`. |
| 3 | Server env remains live-auto-hot disabled after the command. | VERIFIED | Health-check redacted config reported `BFA_LIVE_AUTO_HOT_SYMBOLS=false`; env grep showed only the fixed `BFA_MARKET_SYMBOLS` line. |
| 4 | Timers remain isolated. | VERIFIED | Paper timer active; live timer and live service inactive after the run. |

## Commands

| Command | Result |
|---------|--------|
| Server one-shot `agent run-once` with `BFA_MODE=dry_run BFA_LIVE_AUTO_HOT_SYMBOLS=true BFA_LIVE_AUTO_HOT_TOP_N=12 BFA_AI_FALLBACK_TO_QUANT_ENABLED=true BFA_OPENAI_ENABLED=false` | Completed with `status=rejected`, `submitted=false`, 12 scan symbols, 3 candidates, 1 evaluated symbol |
| Server env/service state check | `BFA_MARKET_SYMBOLS` fixed list retained; paper timer active; live timer/service inactive |
| Server health-check after dry-run | Passed, `ok=True`, `BFA_LIVE_AUTO_HOT_SYMBOLS=false` |

## Residual Risk

- This proves scanner plumbing and safety bounds, not profitability.
- Dry-run used quant fallback to avoid AI dependency; live behavior should still
  use the configured AI overlay unless an explicit fallback policy is approved.
- Live auto-hot should remain disabled in unattended server env until strategy
  evidence improves.
