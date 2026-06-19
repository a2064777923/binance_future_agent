# Phase 9 Checkpoint: Live Activation Readiness

**Captured:** 2026-06-20T02:33:28+08:00
**Status:** Live timer enabled; candidate-driven live cycle observed; OpenAI
endpoint is intermittent and correctly enters backoff on timeout.

## Server State

- Deployed commit: `f6e613c`
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
- `BFA_MARKET_HEAT_NARRATIVE_ENABLED=true`
- `BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT=0.3`
- `binance-futures-agent-live.timer`: enabled and active
- Order intents now expose `estimated_initial_margin_usdt` so futures margin is
  not confused with contract `notional_usdt`.

No secret values were written to this checkpoint.

## Verification

- Local test suite passed: `python -m unittest discover -s tests`
  - 158 tests passed.
- Local public Binance market-heat smoke collected 1219 snapshots and produced
  3 `market_heat` fallback records for the default symbol allowlist.
- Server Binance signed account read previously passed with configured Binance
  credentials.
- Server health check with network skipped passed in live mode with fully
  redacted secret config values.
- Manual live service smoke passed after the Binance taker-flow normalization
  fix:
  - `Result=success`
  - `ExecMainStatus=0`
  - `ActiveState=inactive`
  - `SubState=dead`
- Earlier direct live runner smoke returned:
  - `mode=live`
  - `status=no_candidate`
  - `submitted=false`
  - `candidate_count=0`
  - `narrative_record_count=0`
  - `market_snapshot_count=1219`
- Timer-driven live cycle after market-heat deployment returned:
  - `mode=live`
  - `status=rejected`
  - `submitted=false`
  - `candidate_count=2`
  - `narrative_record_count=2`
  - `selected_symbol=ETHUSDT`
  - `risk_reasons=["ai_decision_pass"]`
- Direct server dry-run after redaction deployment returned:
  - `mode=dry_run`
  - `status=ai_error`
  - `submitted=false`
  - `candidate_count=3`
  - `narrative_record_count=3`
  - `selected_symbol=ETHUSDT`
  - `validation_errors=["openai_error:TimeoutError"]`
  - `runtime/openai_backoff.json` retry after
    `2026-06-19T18:37:42Z`
- Timer-driven live cycle during the backoff window returned:
  - `mode=live`
  - `status=openai_backoff`
  - `submitted=false`
  - `market_snapshot_count=0`
  - `candidate_count=0`
  - `validation_errors=["openai_retry_after:2026-06-19T18:37:42Z"]`
- Later timer-driven live cycle selected `SOLUSDT` and reached the AI step, but
  the OpenAI-compatible endpoint timed out:
  - `mode=live`
  - `status=ai_error`
  - `submitted=false`
  - `selected_symbol=SOLUSDT`
  - `validation_errors=["openai_error:TimeoutError"]`
- Follow-up deployment clarified that `notional_usdt` is contract notional, not
  initial margin. The AI context now includes `max_position_margin_usdt`, and
  order intent payloads include `estimated_initial_margin_usdt`.
- `ops live-status` was deployed as a read-only live activation evidence
  command. Server run returned:
  - `candidates=13`
  - `ai_decisions=2`
  - `order_intents=1`
  - `submitted_order_intents=0`
  - `exchange_responses=0`
  - `latest_candidate_symbol=SOLUSDT`
  - `latest_order_intent_status=rejected`
  - `openai_backoff.active=true`
  - `lva05_complete=false`

## Current Interpretation

The system is now live-scheduled and candidate-producing without Square/RSS
input. The first candidate-driven live cycle reached OpenAI and resulted in an
AI pass/no-trade decision, so no order was submitted. A later direct dry-run
observed the configured OpenAI endpoint timing out; the runner wrote
`runtime/openai_backoff.json`, skipped execution, and will retry after
`OPENAI_RETRY_AFTER_SECONDS`. The next timer cycle inside that backoff window
returned `openai_backoff` before collecting market data or creating order
intents.

## Remaining Work

- Keep the 100 USDT pilot risk caps unchanged while observing timer behavior.
- If a future live entry is submitted, verify exchange-side stop-loss and
  take-profit algo orders or emergency close behavior before changing limits.
- Monitor the OpenAI-compatible endpoint; intermittent timeouts are currently
  handled by fail-closed backoff.
- If changing toward 1 USDT-per-trade margin, make it an explicit leverage and
  notional-cap configuration change instead of treating `notional_usdt` as
  margin.
- Use `python -m bfa.cli ops live-status --env-file ... --db ...` to check
  whether a future submitted entry has protective-order evidence.
