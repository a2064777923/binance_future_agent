# Binance Futures Agent

Isolated project for a small-capital Binance USDT-M futures trading agent. The
system focuses first on hot-coin discovery from Binance Square and other
narrative sources, then combines those events with futures-market anomalies and
AI-provider structured trade decisions.

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
- AI provider: DeepSeek for live use, with OpenAI Responses still available as
  a fallback provider.
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
AI-provider structured decision validation, risk-gated Binance execution, and
dry-run-first server deployment.

## AI Decision Smoke Command

Phase 6 added a structured AI decision layer; Phase 18 added DeepSeek provider
selection. The command validates the model's JSON locally, journals redacted
request/response records, and can persist the result to `ai_decisions`. It still
does not place Binance orders.

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

## Live Outcome Reconciliation

Closed live trades can be reconstructed from signed Binance `userTrades` and
persisted into the event store. Use the sweep command after protected live
positions close; it skips already closed outcomes and writes only final closed
results when `--persist-closed` is set.

```bash
python -m bfa.cli ops reconcile-outcomes --env-file .env --db runtime/agent.sqlite --persist-closed
python -m bfa.cli ops risk-change-check --env-file .env --db runtime/agent.sqlite --target-leverage 8
```

Active live positions can also be checked against the AI decision's suggested
hold window without changing exchange state:

```bash
python -m bfa.cli ops position-hold-check --env-file .env --db runtime/agent.sqlite
python -m bfa.cli ops position-review --env-file .env --db runtime/agent.sqlite
python -m bfa.cli ops time-exit-plan --env-file .env --db runtime/agent.sqlite
```

`ops position-review` is read-only. It turns the active exchange position plus
the matching submitted trade plan into hold/watch/trail-or-reduce/close-review
recommendations with PnL percent, R multiple, target progress, hold-time
progress, protection count, and matching intent evidence.

Use the exposure status command when reviewing why the bot can or cannot open a
new position under the current live caps. It is read-only and reports current
sizing, long/short direction support, active-position capacity, and the
confirmation-gated `30u_10x_multi_dynamic` preview.

```bash
python -m bfa.cli ops exposure-status --env-file .env --db runtime/agent.sqlite --hypothetical-symbol HYPEUSDT --hypothetical-side long
```

The automated live runner also performs a read-only entry-capacity preflight, so
when the current profile is already full it exits before market collection,
candidate generation, or AI calls.

When multi-position mode has capacity, the live runner evaluates the top-N hot
candidate queue. If the first hot symbol is skipped by AI pass or retryable
symbol-level risk such as duplicate same-direction exposure, the runner can
evaluate the next candidate while still submitting at most one order per cycle.

Higher-leverage or concurrent-position profiles must also stay inside portfolio
caps. The risk layer checks total initial margin, total notional, and same-side
notional after the proposed new entry using:

- `BFA_MAX_PORTFOLIO_MARGIN_USDT`
- `BFA_MAX_PORTFOLIO_MARGIN_FRACTION`
- `BFA_MAX_PORTFOLIO_NOTIONAL_USDT`
- `BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT`

`30u_10x_multi_dynamic` is available as a preview/apply profile for a 30 USDT
account with at most two concurrent positions, but it remains confirmation-gated
and should be treated as experimental until backtests and live evidence justify
it. Profile readiness may carry a protected active position into this target
profile only when exchange-side algo protection is present and the active
exposure fits the target portfolio caps.

## Small-Capital Backtesting

The project now includes a short-window backtest harness for the hot-momentum
strategy family. It uses completed Binance USD-M candles, enters on the next
candle open, includes fees/slippage, and reports staged 100 USDT pilot-style
metrics.

```bash
python -m bfa.cli backtest fetch-klines --env-file .env --symbols BTCUSDT,ETHUSDT,SOLUSDT --interval 5m --limit 288 --output data/backtest/klines-5m-latest.json
python -m bfa.cli backtest sweep --input data/backtest/klines-5m-latest.json --window-bars 72 --step-bars 36 --output results/backtest-sweep-5m.json
python -m bfa.cli backtest matrix --env-file .env --intervals 5m,15m --limit 144 --window-bars 72 --step-bars 36 --top-n 8 --output results/backtest-hot-matrix.json
```

See `docs/backtesting.md` for the staged validation method and promotion rules.
