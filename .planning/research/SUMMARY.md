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

**v1.25 update:** The public Lana/Square/X material remains incomplete and
cannot prove profitability. The useful reproducible pattern is a hot-symbol
engine with broad observation, deterministic multi-factor setup scoring,
paper/backtest promotion gates, and fast post-trade review. Screenshots of
small-capital gains should be treated as unverified narrative inputs, not as
strategy evidence.

## Implications For Roadmap

1. Build isolated project scaffolding and secret hygiene first.
2. Build official Binance market/account client before strategy logic.
3. Build narrative collection as adapters so Square limitations do not block the
   whole project.
4. Build storage and replay before live execution.
5. Add OpenAI decisions only after candidate packets are deterministic.
6. Add live execution last, behind risk gates and server isolation.
7. For live resume, clear manual/unattributed exposure first, then require
   post-change paper outcomes and a separate operator confirmation before any
   timer/profile mutation.
8. Keep AI on the slow path as an overlay/veto. Entry side, point geometry,
   sizing, stop, target, and hold-time must remain deterministic and traceable.

## Sources

- Binance USD-M Futures official documentation:
  `https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info`
- Binance USD-M order, market stream, user data stream, and market data
  documentation under `developers.binance.com`.
- OpenAI official docs should be used during implementation for the current
  recommended structured-output API shape.
- Existing stock repository codebase map used only as architectural inspiration,
  not as an implementation dependency.
- User-provided June 2026 screenshot of Square/X discussion around Lana-style
  AI futures trading, used only for design themes: hot narratives, AI overlay,
  small-capital compounding claims, and operator-visible review.
