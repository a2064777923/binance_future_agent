# Phase 7: Risk-Gated Binance Execution - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Source:** Project roadmap, Phase 6 verification, Binance USD-M Futures docs

<domain>
## Phase Boundary

Phase 7 turns validated AI decisions into dry-run order intents and explicit
live Binance USD-M futures order submissions. It must preserve the 100 USDT
pilot risk envelope and must fail closed whenever live safety preconditions are
missing.

</domain>

<decisions>
## Implementation Decisions

### Execution Modes

- D-01: Dry-run remains the default and must never call Binance private order
  endpoints.
- D-02: Live execution requires `BFA_MODE=live`, Binance credentials, OpenAI
  decision acceptance, missing kill-switch file, and all risk caps present.
- D-03: Testnet is allowed for signed-client smoke behavior, but Phase 7 tests
  must use fake transports only.

### Risk Gates

- D-04: Enforce max 3x leverage, max 20 USDT notional per position, max 1 USDT
  risk per trade, max 3 USDT daily loss, max two open positions, and cooldown.
- D-05: Reject order intents that fail Binance symbol filters, especially
  quantity step size, price tick size, and minimum notional.
- D-06: Live orders must use isolated margin and configured leverage before
  submitting the order.

### Order Shape

- D-07: The first order intent should be a single market entry with recorded
  protective stop/target metadata. Automatic bracket/OCO behavior is deferred
  unless explicitly implemented behind tests.
- D-08: Every dry-run or live execution attempt must persist an `order_intents`
  artifact. Live responses must also persist `exchange_responses`.

### Reconciliation

- D-09: Startup/stream-interruption reconciliation should compare local
  order-intent state with Binance account/open-order/position state through
  fakeable signed-client calls.

### the agent's Discretion

- Choose module names that match the current `bfa` package style.
- Use standard-library HTTP/HMAC helpers and fake transports rather than adding
  dependencies.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project

- `.planning/PROJECT.md` - project risk and isolation posture.
- `.planning/REQUIREMENTS.md` - EXE-01 through EXE-05 definitions.
- `.planning/phases/06-openai-decision-layer/06-VERIFICATION.md` - validated
  AI decision boundary.

### Code

- `src/bfa/config.py` - runtime mode, credentials, risk caps, kill-switch path.
- `src/bfa/ai/schema.py` and `src/bfa/ai/decision.py` - validated AI decision
  model.
- `src/bfa/event_store/store.py` - `order_intents` and `exchange_responses`
  persistence.
- `src/bfa/market/binance_rest.py` and `src/bfa/market/models.py` - existing
  fakeable REST client style and exchange filters.

### Official Binance Docs

- `https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`
- `https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api`

</canonical_refs>

<specifics>
## Specific Ideas

- Add `bfa.execution` modules for order intent models, symbol filters, risk
  gate, signed Binance client, executor, persistence, and reconciliation.
- Extend CLI with `execution decide` or `execution run` using a validated AI
  decision JSON file and optional DB path.
- Tests must verify that dry-run never calls fake transport.
- Tests must verify live mode refuses active kill switch and excessive risk.

</specifics>

<deferred>
## Deferred Ideas

- Server deployment is Phase 8.
- Web dashboard and notification loops are v2.
- More advanced protective order automation can be a follow-up after first
  dry-run/live pilot behavior is audited.

</deferred>

---

*Phase: 07-risk-gated-binance-execution*
*Context gathered: 2026-06-20*
