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

## Deployment Status

Deployment verification is still pending. Phase 18 should remain in progress
until the server env is switched to DeepSeek, server tests and health checks
pass, and one live service/timer cycle is observed.

## Follow-Up

- Fund or transfer USDT into the Binance USD-M futures account before expecting
  a real entry submission.
- LVA-05 remains pending until an actual live entry is submitted and protective
  order evidence is present.
