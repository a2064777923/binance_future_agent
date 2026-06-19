# Binance Futures Agent

Isolated project for a small-capital Binance USDT-M futures trading agent. The
system focuses first on hot-coin discovery from Binance Square and other
narrative sources, then combines those events with futures-market anomalies and
OpenAI-structured trade decisions.

The first live target is a 100 USDT pilot account. The project must default to
dry-run/test modes until explicit live mode, API credentials, leverage limits,
loss limits, and the server kill switch are all configured.

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

Next step:

```bash
$gsd-plan-phase 1
```
