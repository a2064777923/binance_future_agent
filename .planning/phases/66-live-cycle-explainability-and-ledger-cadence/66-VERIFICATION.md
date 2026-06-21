---
phase: 66-live-cycle-explainability-and-ledger-cadence
status: passed
verified: 2026-06-21
requirements: [OPS-03, LEARN-04]
---

# Phase 66 Verification: Live Cycle Explainability And Ledger Cadence

## Result

Phase 66 passes local verification. The new command reconstructs submitted and
no-order live cycles, explains candidate/setup/AI/risk/sizing evidence, keeps
manual symbols visible but non-bot-managed, and reuses the live ledger cadence
with explicit non-mutation proof.

## Requirement Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| OPS-03: Operator can inspect the latest live cycles and see every evaluated symbol, skip reason, factor score, AI decision, risk decision, sizing cap, and whether an order was submitted. | Satisfied | `tests/test_ops_live_cycle_explainability.py` verifies submitted SOLUSDT, AI-pass ADAUSDT, risk-blocked WLDUSDT, missing-artifact BNBUSDT, and manual lifecycle evidence. The report emits `candidate`, `trade_setup.factor_scores`, `ai_decision`, `risk.reason_codes`, `order.submitted`, `exchange_responses`, and `sizing_explanation`. |
| LEARN-04: Closed live outcome reconciliation and live ledger reporting can run on a scheduled or single-command path without placing orders, changing env files, or applying guard/risk changes. | Satisfied | `build_live_cycle_explainability_report()` reuses `build_live_outcome_ledger_report()` and CLI tests verify `--reconcile --persist-closed` routes through a fake signed client, persists local closed outcome evidence, and keeps `places_orders=false`, `writes_env_files=false`, `raises_risk=false`, and `applies_guard_changes=false`. |

## Plan Success Criteria

| Criterion | Status | Evidence |
|-----------|--------|----------|
| A read-only command/report lists recent live cycles with evaluated symbols, skip reasons, factor scores, AI decisions, risk decisions, sizing caps, and submitted-order status. | Satisfied | `ops live-cycle-explainability` is wired in `src/bfa/cli.py`; focused tests assert the JSON shape and per-cycle fields. |
| The report explains small notional choices when stop distance, risk cap, margin cap, filters, or portfolio caps constrain size. | Satisfied | `sizing_explanation.limiting_factors` includes sizing reasons/warnings and risk cap reasons; tests assert `stop_risk_cap`, `margin_fraction_cap`, `effective_notional_cap`, `below_min_executable_notional`, `risk_exceeds_cap`, and `portfolio_notional_cap_reached`. |
| Closed live outcome reconciliation and ledger reporting can run on a single scheduled/single-command path with mutation proof. | Satisfied | CLI reconciliation test asserts ledger `reconciliation.closed=1`, `summary.outcome_count=1`, and optional local persistence true while exchange/env/systemd/risk/guard mutation flags remain false. |
| Manual symbols remain visible in diagnostics without being treated as bot-managed evidence. | Satisfied | Manual lifecycle fixture verifies `BTWUSDT` appears in `manual_diagnostics` with `bot_managed=false` and `manual_position_ignored`. |

## Automated Checks

| Check | Status | Evidence |
|-------|--------|----------|
| Focused local tests | Passed | `python -m unittest tests.test_ops_live_cycle_explainability tests.test_cli` -> 60 tests OK. |
| Full local tests | Passed | `python -m unittest discover -s tests` -> 409 tests OK. |
| Local diff check | Passed | `git diff --check` produced only CRLF warnings. |
| GSD audit | Passed | `audit-open --json` returned `has_open_items=false` and `total=0`. |
| CLI smoke | Passed | Temporary DB smoke returned `schema=bfa_live_cycle_explainability_v1`, `status=explainability_ready`, `cycle_count=1`, `risk_reasons=["risk_exceeds_cap"]`, and mutation flags false. |

## Residual Risk

This phase improves operator visibility and ledger cadence; it does not improve
strategy profitability by itself and was not deployed to the server. Phase 70
remains responsible for server canary verification under the isolated
`/opt/binance-futures-agent` and `/etc/binance-futures-agent` paths.
