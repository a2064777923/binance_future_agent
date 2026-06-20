---
phase: 53
plan: 01
name: Server Live-Resume Readiness Evidence
status: complete
completed: 2026-06-21
requirements_completed:
  - SRV-01
  - SRV-02
  - SRV-03
---

# Summary: Server Live-Resume Readiness Evidence

## What Changed

- Added `scripts/run-server-readiness.ps1`, a preview-first helper for running
  `ops live-resume-readiness` on the isolated server.
- The helper:
  - defaults to preview mode and requires `-Run` before connecting;
  - restricts paths to `/opt/binance-futures-agent` and
    `/etc/binance-futures-agent`;
  - defaults to `quant_setup_selective_guarded`;
  - marks `ETHUSDT` as manual exposure by default;
  - accepts readiness exit code `0` or `1` only when stdout parses as
    `bfa_live_resume_readiness_v1`;
  - writes parsed JSON stdout to local `runtime/` when executed.
- Added deployment docs for read-only live-resume readiness checks.
- Extended deploy asset tests to lock preview-first and no-live-mutation
  behavior.

## Server Evidence

- Initial server probe showed the deployed CLI did not yet include
  `ops live-resume-readiness`.
- A code-only isolated deployment was performed from git `HEAD` using the
  existing `/opt/binance-futures-agent` deployment path and bootstrap script.
- Post-deploy server units:
  - `binance-futures-agent-live.timer`: `inactive`
  - `binance-futures-agent-live.service`: `inactive`
  - `binance-futures-agent-paper.timer`: `active`
  - `binance-futures-agent-paper.service`: `inactive`
- Server health-check with `--skip-network` returned exit code `0`.
- Server `ops live-resume-readiness` returned exit code `1` with schema
  `bfa_live_resume_readiness_v1`, status `keep_live_paused`, and
  `live_resume_allowed=false`.
- Local artifact: `runtime/server-live-resume-readiness-20260620T181006Z.json`
  (runtime evidence, not committed).

Readiness blockers:

- `matrix`: `matrix_report_not_provided`
- `strategy_evidence`: `paper_signals_missing`
- `exchange_state`: `manual_or_unattributed_exchange_exposure_present`
- `risk_profile`: `submitted_intents_missing_outcomes`
- `confirmation`: `operator_confirmation_required`

Exposure classification:

- Manual/unattributed symbols: `ETHUSDT`
- Agent-managed symbols: none

Read-only flags:

- `places_orders=false`
- `applies_risk_profiles=false`
- `writes_env_files=false`
- `changes_systemd_state=false`
- `mutates_exchange_state=false`
- `creates_order_intents=false`
- `restores_live_timer=false`

## Verification

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-server-readiness.ps1`
  passed in preview mode and did not connect to the server.
- `python -m unittest tests.test_deploy_assets tests.test_ops_live_resume_readiness`
  passed: 11 tests.
- `python -m unittest discover -s tests` passed: 354 tests.
- `git diff --check` passed with only existing CRLF normalization warnings.
- Runtime readiness artifact secret scan passed.
- Strict changed-file secret-value scan passed; existing docs contain placeholder
  examples such as `OPENAI_API_KEY=...`, not real values.

## Operational Notes

- Live automation remains paused.
- The readiness result is intentionally fail-closed and does not authorize live
  timer restore, risk-profile apply, or Binance order submission.
- The next phase should collect guarded paper evidence and provide a matrix
  report path so readiness can move past `matrix_report_not_provided` and
  `paper_signals_missing`.
