# Research: Features

**Date:** 2026-06-19

## Table Stakes For This Project

### Exchange Connectivity

- Fetch exchange metadata and symbol filters.
- Fetch klines, tickers, funding, open interest, long/short ratios, and taker
  buy/sell data.
- Maintain listen-key / user-data stream once live execution begins.
- Place, cancel, and inspect USD-M futures orders.
- Normalize Binance errors into structured failure reasons.

### Hot-Coin Discovery

- Collect Binance Square hot posts or exports where available.
- Support manual import and browser/export based ingestion before relying on
  unstable unofficial read APIs.
- Add fallback narrative sources: RSS/news, X if credentials are available,
  Telegram channel exports if configured, and exchange listing/announcement
  pages.
- Extract symbol mentions, narrative tags, timestamp, source, engagement, and
  duplicate clusters.

### Candidate Scoring

- Compute narrative heat.
- Compute liquidity and tradeability filters.
- Compute price momentum, volume spike, volatility, OI change, taker-flow bias,
  funding pressure, and long/short crowding.
- Rank candidates and emit reasons, not just scores.

### AI Decision Layer

- Build a compact context packet per candidate.
- Ask OpenAI for structured JSON decisions.
- Validate all model outputs against schema and deterministic risk constraints.
- Keep model output advisory until execution checks pass.

### Risk And Execution

- Default to dry-run.
- Support live mode for a 100 USDT account.
- Enforce isolated margin, leverage cap, notional cap, stop order or immediate
  exit plan, daily loss cap, position count cap, cooldown, and kill switch.
- Record exact order intents, exchange requests, responses, fills, and errors.

### Replay And Learning

- Replay historical candidates and decisions.
- Compare AI decision vs outcome.
- Produce strategy review reports showing win rate, expectancy, drawdown,
  slippage, fee impact, and reason-code performance.

### Deployment

- Deploy as an isolated server service.
- Provide health CLI commands: config check, exchange connectivity check,
  OpenAI check, dry-run one cycle, risk state, and kill-switch status.
- Avoid modifying existing server projects.

## Differentiators

- Multi-source narrative collector with pluggable adapters.
- AI decision journal that can improve prompts/config without automatic unsafe
  self-modification.
- Very small account sizing model designed for 100 USDT rather than theoretical
  institutional position sizing.

## Deferred Features

- Portfolio-level multi-strategy allocation.
- Cross-exchange execution.
- High-frequency market making.
- Full UI dashboard.
- Telegram/Feishu push layer.
- Automatic strategy config promotion.
