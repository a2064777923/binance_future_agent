# Project Research Summary

**Date:** 2026-06-19

## Key Findings

**Stack:** Python 3.11+, Binance USD-M futures official REST/WebSocket APIs,
OpenAI structured decisions, SQLite event store, systemd deployment.

**Strategy:** The Lana / "棍哥" public material suggests a hot-narrative,
AI-assisted, high-turnover futures approach rather than a fully disclosed
technical strategy. The reproducible form is: collect hot coin narratives,
confirm with futures-market anomalies, have AI produce structured decisions,
and constrain execution through deterministic risk code.

**Data:** Official Binance futures data can cover market structure and
execution. Narrative data must be pluggable because Binance Square reading
access is less stable than futures market APIs.

**Risk:** With 100 USDT capital, the system must be designed around survival:
small notional, low leverage, daily loss stop, kill switch, and complete
journaling.

## Implications For Roadmap

1. Build isolated project scaffolding and secret hygiene first.
2. Build official Binance market/account client before strategy logic.
3. Build narrative collection as adapters so Square limitations do not block the
   whole project.
4. Build storage and replay before live execution.
5. Add OpenAI decisions only after candidate packets are deterministic.
6. Add live execution last, behind risk gates and server isolation.

## Sources

- Binance USD-M Futures official documentation:
  `https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`
- Binance USD-M order, market stream, user data stream, and market data
  documentation under `developers.binance.com`.
- OpenAI official docs should be used during implementation for the current
  recommended structured-output API shape.
- Existing stock repository codebase map used only as architectural inspiration,
  not as an implementation dependency.
