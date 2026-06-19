# Phase 9 Checkpoint: Live Activation Readiness

**Captured:** 2026-06-20T02:20:52+08:00
**Status:** Live timer enabled; OpenAI-compatible endpoint degraded under the
configured 5 second timeout.

## Server State

- Deployed commit: `79b44a1`
- App root: `/opt/binance-futures-agent`
- Env file: `/etc/binance-futures-agent/env`
- Env file permissions: managed as `600 root:root`
- `BFA_MODE=live`
- `BFA_OPENAI_ENABLED=true`
- `BFA_REQUIRE_PROTECTIVE_ORDERS=true`
- `OPENAI_BASE_URL` configured out of band
- `OPENAI_TIMEOUT_SECONDS=5`
- `OPENAI_MAX_OUTPUT_TOKENS=400`
- `OPENAI_RETRY_AFTER_SECONDS=300`
- `binance-futures-agent-live.timer`: enabled and active

No secret values were written to this checkpoint.

## Verification

- Local test suite passed: `python -m unittest discover -s tests`
  - 155 tests passed.
- Server Binance signed account read previously passed with configured Binance
  credentials.
- Server OpenAI health check reached the configured endpoint but timed out under
  the 5 second timeout. This is intentionally treated as degraded, not as a
  reason to remove live automation.
- Manual live service smoke passed after the Binance taker-flow normalization
  fix:
  - `Result=success`
  - `ExecMainStatus=0`
  - `ActiveState=inactive`
  - `SubState=dead`
- Direct live runner smoke returned:
  - `mode=live`
  - `status=no_candidate`
  - `submitted=false`
  - `candidate_count=0`
  - `narrative_record_count=0`
  - `market_snapshot_count=1219`

## Current Interpretation

The system is now live-scheduled but currently has no narrative candidates. If
the OpenAI-compatible endpoint is slow or unavailable when a candidate appears,
the runner is expected to return `ai_error`, write
`runtime/openai_backoff.json`, skip order execution, and retry after
`OPENAI_RETRY_AFTER_SECONDS`.

## Remaining Work

- Add or automate narrative/hot-coin source inputs so live cycles can produce
  candidates.
- Observe one candidate-driven OpenAI decision on the server.
- If an entry is submitted, verify exchange-side stop-loss and take-profit algo
  orders or emergency close behavior.
- Review the first candidate-driven live cycle before increasing any limits.

