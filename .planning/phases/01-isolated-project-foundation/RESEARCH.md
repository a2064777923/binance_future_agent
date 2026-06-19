# Phase 1 Research: Isolated Project Foundation

**Date:** 2026-06-19

## Summary

Phase 1 should produce the smallest useful engineering foundation for the
Binance Futures Agent: a Python package scaffold, explicit runtime modes,
config validation, secret redaction, tests, and server-isolation documentation.
It should not implement Binance connectivity, OpenAI calls, strategy, storage,
or execution yet. Those belong to later phases.

## Recommended Project Layout

```text
binance_futures_agent/
  pyproject.toml
  README.md
  AGENTS.md
  .env.example
  src/bfa/
    __init__.py
    cli.py
    config.py
    redaction.py
  tests/
    test_config.py
    test_redaction.py
  docs/
    deployment_isolation.md
```

Use `src/bfa` to avoid accidental imports from the repository root and to make
future packaging cleaner. Keep CLI thin: parse arguments, call importable
functions, print redacted results, and return exit codes.

## Runtime Modes

Use an enum-like mode value:

- `dry_run`: No exchange orders. Does not require Binance API credentials.
- `testnet`: Requires Binance credentials, but points to testnet endpoints.
- `live`: Requires Binance credentials, explicit risk caps, and kill-switch
  path. Live remains allowed by project scope but must be explicit.

Config validation should return a structured object rather than raising for
normal missing-field cases:

- `valid`: bool
- `mode`: selected mode
- `errors`: blocking issues
- `warnings`: non-blocking cautions
- `redacted`: redacted config summary

This keeps CLI behavior simple and testable.

## Secret Handling

Secret fields include:

- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `OPENAI_API_KEY`
- cookies and bearer tokens
- server passwords
- any key containing `SECRET`, `TOKEN`, `PASSWORD`, `COOKIE`, or `API_KEY`

Redaction recommendation:

- Empty values remain empty.
- Short non-empty values become `<redacted>`.
- Longer values can preserve prefix/suffix only if useful, for example
  `abcd...wxyz`, but tests should assert the original full value is never
  present.
- Redaction should work recursively for dictionaries and lists because future
  config diagnostics may become nested.

## Config Source Model

For Phase 1, load environment variables directly and optionally support a local
`.env` file through `python-dotenv` if the dependency is added. Keep `.env`
gitignored. Future deployment can use `/etc/binance-futures-agent/env`.

Recommended default risk values:

- `BFA_MODE=dry_run`
- `BFA_ACCOUNT_CAPITAL_USDT=100`
- `BFA_MAX_LEVERAGE=3`
- `BFA_MAX_POSITION_NOTIONAL_USDT=20`
- `BFA_MAX_RISK_PER_TRADE_USDT=1`
- `BFA_MAX_DAILY_LOSS_USDT=3`
- `BFA_MAX_OPEN_POSITIONS=2`

Phase 1 should validate that numeric values are parseable and positive, but it
does not need to evaluate positions or account state yet.

## Server Isolation Documentation

Document the target layout without deploying:

- App directory: `/opt/binance-futures-agent`
- Env file: `/etc/binance-futures-agent/env`
- Data: `/opt/binance-futures-agent/data`
- Runtime: `/opt/binance-futures-agent/runtime`
- Logs: `/opt/binance-futures-agent/logs`
- Unit: `binance-futures-agent.service`

The doc should state that existing services, cron jobs, databases, and stock
project files must not be modified by deployment scripts.

## Tests To Include

- `dry_run` config passes without Binance credentials.
- `testnet` config fails without Binance credentials.
- `live` config fails without Binance credentials.
- `live` config fails without kill-switch path and risk caps.
- unknown mode fails.
- invalid numeric risk values fail.
- redaction removes exact secret values from flat and nested structures.
- CLI `config-check` prints redacted output.

## Phase 1 Non-Goals

- No Binance REST/WebSocket calls.
- No OpenAI API calls.
- No SQLite event schema.
- No narrative collectors.
- No trading strategy.
- No order placement.
- No server deployment.

## Risks

- Overbuilding the foundation can delay useful market-data work. Keep the
  scaffold small.
- Underbuilding redaction now can leak secrets later when live config is added.
  Make redaction shared and tested.
- Windows paths and Linux deployment paths differ. Keep both documented but
  avoid server-specific assumptions in core config.
