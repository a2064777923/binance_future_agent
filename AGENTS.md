# Agent Guidance

This repository is an isolated Binance futures trading-agent project. Do not
read from or write to `F:\stock` as part of normal implementation unless the
user explicitly asks for a comparison.

## Safety Rules

- Never commit API keys, passwords, cookies, tokens, private keys, `.env` files,
  exchange account data exports, or raw trading logs.
- Do not print secret values to terminal output or generated docs.
- Live order code must be fail-closed: if config, risk checks, exchange state,
  or kill-switch checks are ambiguous, do not place an order.
- Treat Binance live trading as high-risk financial automation. Keep testnet,
  dry-run, replay, and explicit live modes separate.

## Project Shape

- Prefer Python for collectors, strategy, execution, and CLI scripts.
- Keep modules importable and testable; scripts should be thin entry points.
- Put durable runtime data under `data/`, transient state under `runtime/`, and
  logs under `logs/`; these paths are gitignored.
- Use structured JSON/SQLite records for all signals, decisions, orders, and
  trade outcomes.

## Verification

Before claiming work is complete, run the relevant verification command. Early
project defaults:

```bash
python -m unittest discover -s tests
git diff --check
```

If tests do not exist yet, verify generated planning/docs with file existence,
line counts, and secret-pattern scans.
