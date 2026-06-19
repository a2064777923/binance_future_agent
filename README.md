# Binance Futures Agent

Isolated project for a small-capital Binance USDT-M futures trading agent. The
system focuses first on hot-coin discovery from Binance Square and other
narrative sources, then combines those events with futures-market anomalies and
OpenAI-structured trade decisions.

The first live target is a 100 USDT pilot account. The project must default to
dry-run/test modes until explicit live mode, API credentials, leverage limits,
loss limits, and the server kill switch are all configured.

In this project, `notional_usdt` means contract position notional, not the
initial margin consumed by a futures position. Approximate initial margin is
`notional_usdt / leverage`, before fees, funding, and exchange-specific margin
rules.

## Scope

- Exchange: Binance USD-M futures.
- Initial account size: 100 USDT.
- Initial strategy family: hot narrative coin + futures anomaly confirmation.
- AI provider: OpenAI.
- Deployment target: isolated service on server `64.83.34.222` as root, under
  `/opt/binance-futures-agent`.

## Safety Defaults

- No secret values are tracked in git.
- Live execution must use isolated margin and capped leverage.
- Default mode is `dry_run`.
- A filesystem kill switch must be checked before order placement.
- Existing services on the deployment server must not be modified.

## Planning

GSD project artifacts live in `.planning/`.

## Local Development

Work from this repository only:

```bash
cd F:\binance_futures_agent
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m unittest discover -s tests
git diff --check
```

The package uses a `src/bfa` layout so application imports come from this
repository, not from adjacent projects. Do not import from `F:\stock`.

Local secrets belong in `.env`, which is ignored by git. `.env.example` documents
variable names only.

Phases 1-8 implement the isolated project foundation, public market data,
narrative ingestion, event-store replay, hot-coin candidate scoring,
OpenAI-structured decision validation, risk-gated Binance execution, and
dry-run-first server deployment.

## OpenAI Decision Smoke Command

Phase 6 adds a structured OpenAI decision layer. It validates the model's JSON
locally, journals redacted request/response records, and can persist the result
to `ai_decisions`. It still does not place Binance orders.

```bash
python -m bfa.cli ai decide ^
  --env-file .env ^
  --candidate runtime/candidate.json ^
  --decided-at 2026-06-19T10:00:00Z ^
  --journal runtime/ai-decisions.jsonl ^
  --db runtime/agent.sqlite
```

Deployment health check:

```bash
python -m bfa.cli ops health-check --env-file .env --db runtime/agent.sqlite --skip-network
```

The server deployment lives under `/opt/binance-futures-agent` with env at
`/etc/binance-futures-agent/env` and a dedicated
`binance-futures-agent.service` oneshot health-check unit.
