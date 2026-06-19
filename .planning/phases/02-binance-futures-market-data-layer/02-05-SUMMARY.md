---
phase: 02-binance-futures-market-data-layer
plan: 05
subsystem: market-collector-cli
tags:
  - binance
  - futures
  - collector
  - cli
key-files:
  created:
    - src/bfa/market/collector.py
    - tests/test_market_collector.py
  modified:
    - .env.example
    - src/bfa/config.py
    - src/bfa/cli.py
    - tests/test_config.py
    - tests/test_cli.py
metrics:
  tests: "python -m unittest discover -s tests"
  test_count: 53
  requirements:
    - MKT-01
    - MKT-02
    - MKT-03
    - MKT-04
requirements-completed:
  - MKT-01
  - MKT-02
  - MKT-03
  - MKT-04
---

# Summary: Plan 05 - Market Collector, CLI Smoke, And Boundary Checks

## Result

Wired Phase 2 market data into a controlled symbol allowlist, selected-symbol
REST snapshot collector, and thin CLI smoke commands. The collector assembles
exchange metadata plus ticker, kline, funding, open-interest, long/short, and
taker-flow snapshots through injectable clients and normalizers; the CLI can
print exchangeInfo JSON or write snapshot JSONL with fake-client unit tests.

## Commits

| Commit | Description |
|--------|-------------|
| `afe169d` | Added `BFA_MARKET_SYMBOLS` config/defaults and allowlist parsing. |
| `cf2d152` | Added `MarketDataCollector` with selected-symbol REST metric orchestration and symbol caps. |
| `0c50811` | Added `market-data exchange-info` and `market-data snapshot` CLI smoke commands with injectable fake-client tests. |

## Files Changed

| File | Change |
|------|--------|
| `.env.example` | Documented safe default `BFA_MARKET_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT`. |
| `src/bfa/config.py` | Added allowlist default, `AppConfig.get_list`, and `market_symbols`. |
| `src/bfa/market/collector.py` | Added selected-symbol REST snapshot collector with empty/excessive symbol safeguards. |
| `src/bfa/cli.py` | Added public market-data smoke commands while preserving `config-check`. |
| `tests/test_config.py` | Added market symbol allowlist parsing and dry-run credential independence coverage. |
| `tests/test_market_collector.py` | Added fake-client collector coverage for metric orchestration and caps. |
| `tests/test_cli.py` | Added fake-client CLI tests for exchangeInfo output and snapshot JSONL writing. |

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_config.ConfigTests -v` | Passed, 11 tests |
| `python -m unittest tests.test_market_collector -v` | Passed, 3 tests |
| `python -m unittest tests.test_cli tests.test_market_collector -v` | Passed, 9 tests |
| `python -m unittest discover -s tests` | Passed, 53 tests |
| `git diff --check` | Passed |
| `git grep -n "F:\\\\stock" -- . ":(exclude).planning/**"` | Only matched `AGENTS.md` and `README.md` isolation guidance. |
| `git grep -nE "listenKey|userData|account|order|OPENAI|Square|sqlite|sqlite3" -- src tests` | Only matched Phase 1 config/redaction constants, long/short payload fields, and explicit private-stream rejection tests/code. |
| `git grep -nE "API_KEY|API_SECRET|SECRET|TOKEN|COOKIE" -- src tests .env.example` | Only matched documented empty config keys and synthetic redaction/config tests; no committed secret values. |

## Deviations

None - plan executed exactly as written.

## Issues Encountered

The initial CLI implementation placed `--env-file` on the parent
`market-data` parser, while the plan contract used
`market-data exchange-info --env-file ...`. This was corrected before commit
so the CLI matches the documented command shape.

## Self-Check

PASSED. MKT-01 through MKT-04 are covered by automated tests: exchange metadata
and filters are fetchable, selected-symbol REST metrics are available, public
WebSocket stream utilities parse live-style market events, normalized snapshots
can be written as JSONL, and CLI smoke commands exercise the layer without
unit-test live network calls, secrets, private streams, AI, narrative ingestion,
order placement, server deployment, SQLite event storage, or `F:\stock` access.
