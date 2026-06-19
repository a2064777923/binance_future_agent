# Phase 6: OpenAI Decision Layer - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning
**Source:** User direction + completed Phases 1-5

<domain>
## Phase Boundary

Phase 6 converts deterministic hot-coin candidates into structured, validated
OpenAI trade decisions. It does not place Binance orders, manage live positions,
deploy to the server, or bypass future risk gates.

</domain>

<decisions>
## Implementation Decisions

### AI Provider

- D-01: Use OpenAI as the decision provider for candidate evaluation.
- D-02: Use the Responses API with a strict JSON schema so model output is
  machine-validated before any downstream execution layer sees it.

### Trading Boundary

- D-03: Phase 6 may produce an auditable order-intent-like decision, but must
  not submit orders or call Binance private/account endpoints.
- D-04: Invalid, incomplete, or risk-inconsistent AI responses must be rejected
  deterministically.

### Risk Envelope

- D-05: Decision validation must retain the pilot envelope from project context:
  100 USDT capital, max 3x leverage, max 20 USDT notional, max 1 USDT risk per
  trade, max 3 USDT daily loss, and max two open positions.

### Observability

- D-06: Every AI request and response must be journaled with redaction before it
  can be persisted or reviewed.
- D-07: Tests must use fake OpenAI transports and fixtures only. No live OpenAI,
  Binance, social, or server calls are allowed in Phase 6 verification.

### the agent's Discretion

- Choose standard-library HTTP or a light wrapper rather than adding the OpenAI
  SDK if the local codebase remains dependency-free.
- Choose exact CLI flags and module names that match existing `bfa.cli` patterns.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project State

- `.planning/PROJECT.md` - project boundary, safety posture, and current state.
- `.planning/REQUIREMENTS.md` - AI-01 through AI-04 requirement definitions.
- `.planning/ROADMAP.md` - Phase 6 success criteria.

### Existing Code Patterns

- `src/bfa/config.py` - config loading, OpenAI env keys, risk defaults.
- `src/bfa/redaction.py` - secret-safe diagnostics.
- `src/bfa/cli.py` - CLI command style and test injection pattern.
- `src/bfa/event_store/store.py` - generic event artifact persistence.
- `src/bfa/strategy/candidates.py` - candidate payload model.
- `tests/test_cli.py` - CLI fake dependency pattern.

### Official API Docs

- `https://developers.openai.com/api/docs/guides/structured-outputs`
- `https://developers.openai.com/api/reference/resources/responses/methods/create/`

</canonical_refs>

<specifics>
## Specific Ideas

- Build compact candidate packets from `CandidateSignal.to_dict()` or a plain
  candidate JSON payload.
- Include source event IDs, market event IDs, reason codes, features, risk caps,
  and a deterministic generated/decided timestamp in the model context.
- Return `decision`, `side`, `confidence`, `entry_price`, `stop_price`,
  `target_price`, `notional_usdt`, `hold_time_minutes`, and `reasons`.
- Journal request and response JSONL locally, and persist accepted/rejected
  decisions to the `ai_decisions` event-store category when a DB path is given.

</specifics>

<deferred>
## Deferred Ideas

- Binance order submission is Phase 7.
- Server deployment and systemd setup are Phase 8.
- LLM judges, prompt self-improvement, and dashboard review are v2 ideas.

</deferred>

---

*Phase: 06-openai-decision-layer*
*Context gathered: 2026-06-19*
