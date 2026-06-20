# Summary 18-01: DeepSeek Provider Switch

## Completed Locally

- Added `BFA_AI_PROVIDER` with validated `openai` and `deepseek` choices.
- Added `OpenAIChatCompletionsClient` for DeepSeek `/chat/completions`.
- Configured DeepSeek JSON object mode, disabled thinking output, and schema
  grounded prompts.
- Kept OpenAI Responses API support available behind the same provider builder.
- Routed the agent, CLI, and ops health check through shared AI provider
  construction.
- Added fenced/prefixed JSON extraction before strict decision schema
  validation.
- Added provider-aware AI decision source naming for persisted decision
  artifacts.
- Updated env examples and deployment docs without real secret values.

## Local Evidence

- Targeted provider/decision/config/health/CLI tests passed: 76 tests.
- Full local unit suite passed: 209 tests.
- `git diff --check` passed with Windows LF-to-CRLF warnings only.
- A local DeepSeek smoke test with the key held only in process environment
- returned `decision=trade`, `accepted=true`, and no validation errors.
- Secret scan over changed files and docs found no real API key or password
  values.

## Deployment Evidence

- Deployed committed HEAD to `/opt/binance-futures-agent` and kept env under
  `/etc/binance-futures-agent/env`.
- Updated only selected AI provider values to DeepSeek; pilot caps stayed at
  100 USDT capital, 20 USDT max notional, 3x leverage, 1 USDT max trade risk,
  and 3 USDT max daily loss.
- Server focused tests passed 76 tests.
- Server health check with `--skip-network` passed in live mode with redacted
  secrets.
- Server AI network health check passed with detail `deepseek AI API reachable`.
- Manual live service cycle after clearing stale backoff exited 0; DeepSeek
  returned a validated pass decision and no order was submitted.
- Live status showed `submitted_order_intents=0`,
  `openai_backoff.active=false`, and `lva05_complete=false`.
- Re-enabled `binance-futures-agent-live.timer`; timer is active and a
  timer-start cycle also exited 0 with a validated DeepSeek pass decision and
  `submitted=false`.

## Follow-Up

- Fund or transfer USDT into the Binance USD-M futures account before expecting
  a real entry submission.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
