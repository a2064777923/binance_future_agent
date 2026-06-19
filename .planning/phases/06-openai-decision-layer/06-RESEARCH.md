# Phase 6 Research: OpenAI Decision Layer

**Date:** 2026-06-19
**Scope:** Responses API structured outputs, validation, and local integration.

## Findings

1. OpenAI Structured Outputs support JSON Schema constrained responses. The
   decision layer should request strict schema output and still validate locally
   because downstream trading code must fail closed.
   Source: https://developers.openai.com/api/docs/guides/structured-outputs

2. The current Responses API accepts response creation requests through the
   `/v1/responses` API surface. The local codebase can keep its dependency-free
   pattern by wrapping `urllib.request` behind a fakeable transport.
   Source: https://developers.openai.com/api/reference/resources/responses/methods/create/

3. This repo already has the important safety primitives for Phase 6:
   config-loaded OpenAI key/model values, redaction helpers, generic event-store
   artifact tables including `ai_decisions`, and deterministic strategy
   candidate dictionaries.

4. Risk validation should be deterministic and independent of the model. The
   model may propose a trade, but code must reject bad side/price geometry,
   missing required fields, confidence outside bounds, notional above cap, or
   stop-loss risk above the configured max risk per trade.

## Implementation Direction

- Add `bfa.ai` modules for schema/context building, Responses API transport,
  decision validation, and journaling.
- Use strict JSON schema with all properties required and nullable price fields
  for pass decisions.
- Parse both `output_text` and nested Responses API output message content so
  tests stay robust against response shape differences.
- Store secret-safe request/response journal records as JSONL and optionally
  persist AI decisions through `EventStore.insert_artifact("ai_decisions", ...)`.

## Validation Architecture

- Unit tests for schema shape and deterministic context packets.
- Unit tests for fake OpenAI transport request construction and response parsing.
- Unit tests for valid trade, pass, schema failure, price-geometry failure, and
  risk-cap failure.
- CLI tests with fake AI client only.
- Full regression: `python -m unittest discover -s tests`.

## Known Pitfalls

- Structured output does not remove the need for local validation.
- Never log `OPENAI_API_KEY` or authorization headers in journals.
- Do not introduce live order submission in this phase.
- Do not require the OpenAI SDK unless the project intentionally adds runtime
  dependencies later.
