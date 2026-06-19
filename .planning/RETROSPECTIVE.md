# Retrospective

## Milestone: v1.0 — Dry-Run Binance Futures Agent

**Shipped:** 2026-06-19
**Phases:** 8
**Plans:** 28

### What Was Built

- Independent crypto futures repo, config contract, secret hygiene, and dry-run
  diagnostics.
- Binance USD-M public market-data access, narrative ingestion, event store,
  replay packet generation, and review metrics.
- Hot-coin candidate ranking, OpenAI structured decision validation, and
  secret-safe decision journaling.
- Risk-gated Binance execution helpers, server deployment assets, and isolated
  health checks.

### What Worked

- Building horizontal layers made each high-risk component testable before
  connecting it to live trading.
- Keeping execution deterministic made it possible to add live automation later
  without giving the LLM direct control over safety gates.
- Isolated deployment paths prevented the new project from touching the existing
  stock system.

### What Was Inefficient

- The first milestone closed as dry-run even though the real product goal is
  live automated trading, so v1.1 now exists specifically to finish live
  activation.
- GSD milestone archival was started before live activation planning was
  explicit, leaving a short cleanup pass necessary.

### Patterns Established

- LLM is slow-path analyst/veto only; order placement, protective orders, and
  kill switch stay deterministic.
- Server timers should remain disabled until one manual service cycle is
  reviewed.
- Credentials are configured out of band and never emitted in repo output.

### Key Lessons

- Futures automation needs protective orders in the same execution path as live
  entries, not just a separate risk document.
- AI latency must fail closed; timeout is a risk control, not only a performance
  tweak.
- GSD state should distinguish "dry-run deployed" from "live pilot activated" so
  progress is honest.

## Cross-Milestone Trends

| Trend | Evidence | Next Action |
|-------|----------|-------------|
| Safety gates are moving from docs into code | Protective orders, kill switch, AI timeout | Verify on server during Phase 9 |
| External credentials remain the activation bottleneck | Binance key configured, OpenAI key missing | Configure OpenAI key out of band |

