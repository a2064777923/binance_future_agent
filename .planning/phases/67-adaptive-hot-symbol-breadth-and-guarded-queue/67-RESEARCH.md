---
phase: 67
name: Adaptive Hot-Symbol Breadth And Guarded Queue
status: research
created: 2026-06-21
mode: inline-gsd-fallback
---

# Phase 67 Research: Adaptive Hot-Symbol Breadth And Guarded Queue

## Research Complete

Automatic GSD subagent spawning was not used because this Codex session only
permits subagents when the user explicitly requests delegated agent work. This
research was completed inline against the current codebase.

## Phase Scope

Phase 67 should make the live runner observe a broader hot-symbol universe,
report source health, suppress repeated weak evidence, and continue through
retryable candidate skips while preserving the one-order-per-cycle default and
manual-symbol exclusions.

## Existing Implementation

### Live Auto-Hot Selection

- `src/bfa/agent.py::_agent_scan_symbols()` already supports
  `BFA_LIVE_AUTO_HOT_SYMBOLS`, `BFA_LIVE_AUTO_HOT_TOP_N`, quote-volume floors,
  absolute price-change floors, fallback to `BFA_MARKET_SYMBOLS`, and
  `BFA_MANUAL_POSITION_SYMBOLS` exclusion.
- `src/bfa/backtest/matrix.py::select_hot_usdt_symbols()` already filters
  Binance 24h ticker rows to non-stable USDT symbols and ranks by change,
  volume, and symbol.
- `src/bfa/config.py` currently defaults `BFA_LIVE_AUTO_HOT_TOP_N` to `40`.
  Phase 67 can raise the local default and examples to `80` without requiring
  server mutation in this phase.

### Candidate And Guard Path

- `src/bfa/strategy/candidates.py::generate_candidates()` already rejects
  symbols that are not allowed, lack narrative/market confirmation, fail
  liquidity, exceed volatility bounds, exceed min-executable-notional caps, or
  match `ForwardPaperGuard` symbol blocks.
- `src/bfa/strategy/paper_guard.py` already derives weak-evidence symbol,
  side, and factor blocks from stored forward-paper signals/outcomes.
- `src/bfa/strategy/setup.py` consumes side/factor guard overrides through
  `merge_guard_profile()`.

### Queue Behavior

- `src/bfa/agent.py::_evaluate_candidate_queue()` already loops over generated
  candidates, persists setup and AI evidence, and records `evaluated_symbols`.
- It already continues after quant/setup pass and AI pass, and after selected
  retryable risk reasons through `_should_try_next_candidate()`.
- It does not yet expose a rich per-candidate evaluation path in the final
  `AgentRunResult`, so operator explainability still has to infer why the queue
  moved to a later symbol.

### Source Health Patterns

- `src/bfa/cli.py::_forward_paper_source_health()` already reports selected
  symbols, ticker payload count, filter parameters, selected ticker rows, and
  configured narrative source state for forward-paper runs.
- `src/bfa/ops/forward_paper.py::ForwardPaperRunReport` includes
  `source_health` in its `to_dict()` payload and augments it with
  event-store narrative availability.
- `src/bfa/market/collector.py` already collects klines, funding,
  open interest, open-interest history, and taker buy/sell flow snapshots. The
  live runner can summarize the collected snapshot event types rather than
  adding new exchange endpoints.

## Recommended Implementation

1. Add a live-runner source-health helper in `src/bfa/agent.py` or a small
   strategy/ops-neutral helper module. Avoid importing CLI helpers into the
   runner if that creates awkward layering.
2. Change the default `BFA_LIVE_AUTO_HOT_TOP_N` from `40` to `80` in config and
   env examples, and update README wording.
3. Replace `_agent_scan_symbols()` with a helper that returns both selected
   symbols and source-health metadata, while preserving the existing public
   function behavior for tests if needed.
4. Add `source_health` and `candidate_evaluations` to `AgentRunResult`.
5. Populate source-health after market and narrative collection:
   ticker selection, market snapshot counts by event type, covered symbols,
   narrative records by source, configured Square/RSS state, market-heat
   fallback count, manual-symbol exclusions, and paper-guard status summary.
6. Add queue evaluation items for each candidate with symbol, setup decision,
   setup reasons, AI status, execution status, risk reasons, and whether the
   runner continued to the next candidate.
7. Expand retryable candidate-level risk handling only for symbol/setup-local
   failures. Keep global/account blockers non-retryable:
   - retryable examples: AI pass, quant/setup pass, duplicate same-symbol
     direction, missing symbol filters, min quantity/notional filter failures,
     notional/risk cap rejection caused by candidate/AI geometry.
   - non-retryable examples: daily loss cap, cooldown, kill switch, missing
     credentials, max open positions, multi-position disabled, portfolio margin
     cap, portfolio notional cap, same-direction cap.
8. Add focused tests in `tests/test_agent_runner.py`, `tests/test_config.py`,
   and `tests/test_deploy_assets.py`. Extend CLI tests only if output shape is
   exposed through a CLI-specific path.

## Risks And Constraints

- Broad scanning increases public API calls because `MarketDataCollector`
  collects several endpoints per symbol. The implementation should keep top-N
  configurable and should not make auto-hot unbounded.
- Source health must never include secrets.
- `BTWUSDT` and any configured manual symbols must remain excluded before
  market collection, candidate generation, AI, execution, entry capacity, and
  auto-management.
- This phase must not deploy to the server or mutate `/etc/binance-futures-agent/env`;
  Phase 70 owns server canary verification.

## Verification Targets

- Focused runner tests prove:
  - auto-hot can select 80 symbols.
  - manual symbols are excluded from the 80-symbol scan.
  - live/dry-run result includes source health for ticker, market snapshots,
    narrative sources, market-heat fallback, and paper guard.
  - retryable candidate skips continue to later candidates.
  - non-retryable global/account blockers stop the cycle.
- Full suite remains green.
- `git diff --check` and GSD audit report no open issues.
