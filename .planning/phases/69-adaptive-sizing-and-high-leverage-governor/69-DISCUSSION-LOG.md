---
phase: 69
name: Adaptive Sizing And High-Leverage Governor
status: captured
created: 2026-06-21
---

# Phase 69 Discussion Log

The user confirmed the live pilot should keep running with broader scanning,
multi-factor quant logic, dynamic sizing, higher-leverage handling, and multiple
bot positions. The latest operator instruction is that `BTWUSDT` is manual and
must not be managed by the bot, while bot position count and notional capacity
may be loosened.

Captured decisions:
- Keep manual symbols outside bot management and capacity counting.
- Include manual margin pressure in portfolio/account risk checks.
- Make sizing adaptive to signal quality and account state, not just hot-coin
  rank or AI approval.
- Keep guard/outcome feedback risk-reducing only.
- Keep server deployment and canary verification in Phase 70.
