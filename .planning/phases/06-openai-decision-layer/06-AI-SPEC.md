# AI-SPEC: Phase 6 OpenAI Decision Layer

**Phase:** 06 - OpenAI Decision Layer
**System Type:** Structured single-model decision support
**Selected Framework:** Direct OpenAI Responses API wrapper
**Alternative Considered:** OpenAI Agents SDK

## 1. Domain Contract

The model evaluates a hot-coin futures candidate and returns a structured trade
decision. Its output is advisory until deterministic code validates schema,
price geometry, notional, and risk. It must not place orders.

Good output is compact, concrete, risk-aware, and explainable. Bad output is
free-form text, missing prices for a trade, ambiguous side, oversized notional,
or a stop/target layout that contradicts the side.

## 2. Framework Rationale

Use a direct Responses API wrapper because Phase 6 is a single structured call,
not a multi-agent workflow. This keeps the dependency-free project shape from
Phases 1-5 and makes fake transport tests straightforward.

## 3. Entry Point Pattern

```text
candidate JSON -> context packet -> Responses API structured output
               -> local validator -> journal -> optional ai_decisions event
```

## 4. Output Contract

The model must return JSON with these fields:

- `decision`: `trade` or `pass`
- `side`: `long`, `short`, or `flat`
- `confidence`: number from `0` to `1`
- `entry_price`: number or null
- `stop_price`: number or null
- `target_price`: number or null
- `notional_usdt`: number or null
- `hold_time_minutes`: integer or null
- `reasons`: array of short reason strings

## 4b. Local Validation Example

```python
result = validate_decision_payload(payload, context)
if not result.accepted:
    # reject before any execution layer can consume it
    return result
```

## 5. Evaluation Strategy

| Dimension | Method | Pass Condition |
|-----------|--------|----------------|
| Schema validity | Code-based | Required fields present; no unknown keys accepted |
| Price geometry | Code-based | Long: stop < entry < target; short: target < entry < stop |
| Risk envelope | Code-based | Notional <= 20 USDT and estimated risk <= 1 USDT |
| Redaction | Code-based | Journal does not contain exact secret values |
| Replayability | Code-based | Same candidate and response produce same decision record |

## 6. Guardrails

- Reject invalid JSON.
- Reject trade decisions missing entry, stop, target, notional, or hold time.
- Reject confidence outside `[0, 1]`.
- Reject notional above configured cap.
- Reject estimated stop-loss risk above configured cap.
- Journal only redacted request/response payloads.
- Do not call Binance private/order endpoints in this phase.

## 7. Production Monitoring

Phase 6 stores request/response/validation records for later review. Full
trade-outcome monitoring arrives after Phase 7 execution and Phase 8 deployment.

## Checklist

- [x] Framework selected
- [x] Structured schema defined
- [x] Risk validation defined
- [x] Journal redaction defined
- [x] Test-only fake transport requirement defined
