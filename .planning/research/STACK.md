# Research: Stack

**Date:** 2026-06-19

## Recommended Stack

- **Language:** Python 3.11+.
- **Exchange API:** Binance USD-M Futures REST and WebSocket APIs.
- **AI provider:** OpenAI Responses API or current OpenAI Python SDK with
  structured JSON schema validation.
- **Storage:** SQLite for v1 event store; Parquet can be added later for larger
  historical data.
- **Scheduling:** systemd service plus a small CLI; avoid cron until runtime
  jobs are stable.
- **Testing:** `unittest` or `pytest`; use mocked Binance/OpenAI clients for
  deterministic safety tests.

## Why Python

Python fits the current workflow: market-data collectors, strategy scoring,
OpenAI API calls, JSON schema validation, SQLite, and simple deployment all have
good support. It also keeps the codebase close to the existing stock repository
patterns without sharing code.

## Binance Official Surfaces

Use the official Binance USD-M futures developer documentation as the primary
source:

- General REST base: `https://fapi.binance.com`.
- Market data and account/order endpoints under `/fapi/v1`.
- WebSocket market streams under Binance USD-M futures stream endpoints.
- User Data Stream for account/order updates.
- Testnet support should be represented as a config switch, even though the
  user wants live small-capital deployment.

## OpenAI Usage

The model should return validated JSON only. The strategy runtime should reject
freeform, missing fields, impossible prices, excessive leverage, or decisions
that conflict with deterministic risk limits.

Recommended decision schema fields:

- `symbol`
- `side`
- `decision`
- `confidence`
- `entry_type`
- `entry_price`
- `stop_price`
- `take_profit_price`
- `max_hold_minutes`
- `reason_codes`
- `invalidation_reasons`
- `data_quality_notes`

## Dependencies To Add During Implementation

Likely v1 dependencies:

- `httpx` or `requests`
- `websockets`
- `pydantic`
- `openai`
- `python-dotenv`
- `pandas`
- `sqlalchemy` or direct `sqlite3`

Keep the first implementation lean; add async and heavier data tooling only
when collection throughput requires it.

## Deployment Stack

Use:

- `/opt/binance-futures-agent` for application code.
- `/opt/binance-futures-agent/.venv` for Python environment.
- `/opt/binance-futures-agent/data` for SQLite and snapshots.
- `/opt/binance-futures-agent/runtime` for state and kill switch.
- `/opt/binance-futures-agent/logs` for local logs.
- `/etc/binance-futures-agent/env` for secrets and runtime config.
- `binance-futures-agent.service` as a dedicated systemd unit.

Do not reuse existing stock service names, DB containers, cron files, or runtime
paths.
