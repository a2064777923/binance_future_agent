# Phase 7 Research: Risk-Gated Binance Execution

**Date:** 2026-06-20
**Scope:** Binance USD-M Futures signed execution, risk gates, and local dry-run.

## Findings

1. Binance USD-M Futures signed endpoints require API-key headers and signed
   query/body parameters using HMAC SHA256. Local code should centralize signing
   behind a fakeable transport and must redact credentials.
   Source: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info

2. New futures orders use `POST /fapi/v1/order`, while `POST /fapi/v1/order/test`
   validates signature/parameters without sending to the matching engine.
   Source: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api

3. Margin type and initial leverage are separate signed trade endpoints. The
   executor should set isolated margin and leverage before order submission in
   live mode, while accepting benign "already set" responses in a later hardening
   pass if needed.

4. The existing event store already has `order_intents`, `exchange_responses`,
   `fills`, and `risk_state` artifact tables, so Phase 7 can persist execution
   evidence without schema migration.

## Implementation Direction

- Build dry-run order intents first and make live submission an explicit branch.
- Use quantity and price quantization based on exchange filters.
- Keep risk state local and deterministic: active positions, daily realized PnL,
  cooldown timestamp, and kill-switch path.
- Persist every attempted intent before live submission.
- Add reconciliation helpers that compare local event-store artifacts with fake
  account/open-order/position responses.

## Validation Architecture

- Unit tests for filter quantization and min-notional rejection.
- Unit tests for risk gates: notional, risk per trade, daily loss, max positions,
  cooldown, kill switch, and live config.
- Unit tests for signed request construction using fake transport.
- CLI tests for dry-run order intent persistence and live refusal.
- Full regression: `python -m unittest discover -s tests`.

## Known Pitfalls

- Do not use real Binance credentials in tests.
- Do not read local API key files during planning, tests, or verification.
- Do not submit live orders unless all explicit live preconditions pass.
- Avoid optimistic local state; reconciliation must report mismatch rather than
  silently assuming local records are current.
