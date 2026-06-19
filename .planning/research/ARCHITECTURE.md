# Research: Architecture

**Date:** 2026-06-19

## Recommended Architecture

```text
Narrative Sources          Binance Futures APIs          Runtime Config
Square / RSS / X / TG      REST + WebSocket              .env + config JSON
          │                         │                         │
          ▼                         ▼                         ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Narrative         │     │ Market Data       │     │ Config / Secrets │
│ Collectors        │     │ Collectors        │     │ Loader           │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌──────────────────────────────────────────────────────────────────┐
│ SQLite Event Store                                                │
│ narratives, market_snapshots, candidates, ai_decisions, orders,   │
│ fills, risk_state, outcomes                                       │
└────────┬─────────────────────────────────────────────────────────┘
         ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Candidate Engine │ ──▶ │ OpenAI Decision  │ ──▶ │ Risk Gate        │
└──────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                            ▼
                                                  ┌──────────────────┐
                                                  │ Binance Executor │
                                                  │ dry_run/live     │
                                                  └────────┬─────────┘
                                                           ▼
                                                  ┌──────────────────┐
                                                  │ Journal / Replay │
                                                  └──────────────────┘
```

## Module Boundaries

- `bfa.config`: load env/config, redact secrets, validate runtime mode.
- `bfa.binance`: official REST/WebSocket clients and symbol metadata.
- `bfa.narrative`: source adapters for Square/manual/RSS/X/Telegram.
- `bfa.store`: SQLite schema, repositories, migrations.
- `bfa.features`: market/narrative feature extraction.
- `bfa.strategy`: candidate scoring and decision packet assembly.
- `bfa.ai`: OpenAI prompt, response schema, validation.
- `bfa.risk`: deterministic account, leverage, stop, loss, cooldown, and kill
  switch checks.
- `bfa.execution`: dry-run and live order orchestration.
- `bfa.replay`: historical simulation and journal review.
- `bfa.cli`: operator commands.

## Design Choices

### AI Is Advisory Until Risk Gate

The model can rank and explain, but only deterministic code can turn a decision
into an order intent. This prevents prompt drift or malformed context from
creating uncontrolled live exposure.

### Event Store First

Every candidate and decision must be persisted before an order is attempted.
This makes live behavior auditable and allows replay even when an order fails.

### Collector Interface

Narrative sources should share a common normalized record:

- source
- source_id
- url
- author
- published_at
- observed_at
- text
- symbols
- engagement fields
- raw metadata reference

This protects the strategy from Square API instability.

### Server Isolation

Use a dedicated service and path:

- App: `/opt/binance-futures-agent`
- Env: `/etc/binance-futures-agent/env`
- Unit: `binance-futures-agent.service`

No stock repo path, stock cron, stock DB container, or stock service should be
modified by deployment scripts.
