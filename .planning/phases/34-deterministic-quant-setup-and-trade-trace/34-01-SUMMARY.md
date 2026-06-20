# Summary 34-01: Deterministic Quant Setup And Trade Trace

## Completed

- Added `bfa.strategy.setup`, a deterministic multi-factor setup engine that
  produces side, entry, stop, target, notional, hold time, confidence, factor
  scores, reasons, and warnings.
- Extended strategy feature extraction with kline-window momentum, micro
  momentum, average/max range, close-position-in-range, quote-volume impulse,
  and taker-flow change.
- Added `quant_setup` to AI decision context and tightened AI validation so
  trade responses must echo setup side, prices, notional, and hold time exactly.
- Added `BFA_AI_FALLBACK_TO_QUANT_ENABLED`, defaulting off, for explicit
  quant-only fallback when the AI layer is unavailable or in backoff.
- The automated runner now persists `trade_setups` before AI evaluation and
  skips candidates whose deterministic setup passes.
- Added read-only `ops trade-trace` to reconstruct the decision chain from the
  event store.
- Deployed the source and tests to `/opt/binance-futures-agent/app` without
  restoring the live timer or changing the live risk profile.

## Evidence

- Local full suite passed: `299` tests.
- Local whitespace check passed: `git diff --check`.
- Server full suite passed: `299` tests.
- Server focused trade-trace CLI test passed.
- Server live service and timer remained `inactive` after deployment.
- Server read-only `ops trade-trace --symbol SOLUSDT` returned
  `trace_ready` for the existing SOLUSDT live order, reconstructing the old
  chain: candidate ranking, AI overlay, risk/order intent, and exchange
  response.

## Operational Result

The existing SOLUSDT live order was confirmed to have been created before this
phase, so it has no persisted `trade_setup`. That trace validates the
operator's concern: the old order path used hot-candidate evidence plus AI
price generation. New cycles now have deterministic setup persistence and AI
veto-only semantics before execution.

No live order, close, profile apply, timer resume, or exchange mutation was
performed in this phase.
