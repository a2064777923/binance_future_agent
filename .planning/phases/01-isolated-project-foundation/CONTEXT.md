# Phase 1 Context: Isolated Project Foundation

**Phase:** 1
**Name:** Isolated Project Foundation
**Created:** 2026-06-19

## Phase Goal

Establish the independent repository, config contract, secret hygiene, and
developer workflow for Binance Futures Agent.

## Requirements In Scope

- **ISO-01**: The project exists in `F:\binance_futures_agent` as an independent git repository.
- **ISO-02**: The project includes gitignore rules that exclude secrets, runtime data, logs, local databases, and raw exports.
- **ISO-03**: The project documents server deployment paths that do not overlap existing projects.
- **CFG-01**: User can configure Binance, OpenAI, runtime mode, risk limits, and data paths through env/config files without committing secret values.
- **CFG-02**: The system can validate required config for dry-run, testnet, and live modes.
- **CFG-03**: The system can redact secret values in logs, diagnostics, and config-check output.

## Decisions

- **D-01 | isolation**: Phase 1 must stay inside `F:\binance_futures_agent` and must not read, import, mutate, or deploy files from `F:\stock`.
- **D-02 | stack**: Use a Python package layout with thin CLI entry points so config and redaction logic are importable and testable.
- **D-03 | config**: Use `.env.example` plus typed runtime config loading. Real secrets live only in `.env` locally or `/etc/binance-futures-agent/env` on the server.
- **D-04 | modes**: Support explicit `dry_run`, `testnet`, and `live` modes. `live` must require Binance credentials, OpenAI credentials where AI is enabled, risk caps, and a kill-switch path.
- **D-05 | redaction**: All config dumps, errors, and diagnostics must pass through a shared redaction helper before display or logging.
- **D-06 | deployment docs**: Server isolation should be documented early, but Phase 1 should not deploy to the server yet.

## Constraints

- Do not include secret values in planning docs, source code, test fixtures, or output.
- Do not read the Binance API key file during Phase 1 implementation unless a later execution phase explicitly needs to import secrets into an env file.
- Default runtime mode must be safe (`dry_run`).
- Keep Phase 1 focused on foundation only; no Binance order placement, OpenAI calls, or trading strategy logic yet.

## Expected Deliverables

- Python package scaffold.
- Typed config loader and validation result objects.
- Secret redaction utility.
- CLI command for `config-check`.
- Tests for mode validation and redaction.
- Deployment isolation notes for future server setup.

## Verification Intent

- Unit tests prove dry-run/testnet/live config behavior.
- Unit tests prove sensitive values are redacted.
- `git diff --check` passes.
- Secret-pattern scan over tracked files finds no credential-shaped values.
