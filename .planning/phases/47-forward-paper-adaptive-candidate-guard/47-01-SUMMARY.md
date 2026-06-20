---
phase: 47
plan: 01
name: Adaptive Forward-Paper Guard
status: complete
completed: 2026-06-21
---

# Summary: Adaptive Forward-Paper Guard

## What Changed

- Added `bfa.strategy.paper_guard`, a read-only adaptive guard built from local
  `paper_signals` and `paper_outcomes`.
- Added guard config defaults for outcome thresholds, symbol/side/factor loss
  thresholds, and guard enablement.
- Wired the guard into `agent run-once`:
  - blocked symbols are rejected during candidate generation before AI or
    execution
  - guarded side/factor blocks are passed into deterministic setup profiles
  - run output includes `paper_guard`
- Wired the guard into `ops forward-paper-run`:
  - blocked symbols are skipped before new paper signals are generated
  - output includes `paper_guard` and `guarded_symbols`
  - no order intents or exchange mutations are introduced
- Added focused coverage for guard no-op behavior, symbol/factor blocking,
  agent pre-AI rejection, forward-paper guarded skips, config defaults, and
  deploy examples.

## Verification

- `python -m py_compile src\bfa\strategy\paper_guard.py src\bfa\strategy\setup.py src\bfa\agent.py src\bfa\ops\forward_paper.py src\bfa\cli.py src\bfa\config.py` passed.
- `python -m unittest tests.test_strategy_paper_guard tests.test_ops_forward_paper tests.test_agent_runner tests.test_config tests.test_deploy_assets` passed: 45 tests.
- `python -m unittest discover -s tests` passed: 339 tests.
- `git diff --check` passed.
- Secret scan over the diff found no committed API keys/passwords.

## Operational Notes

- The guard is evidence-gated. Empty or low-evidence DBs return
  `insufficient_evidence` and do not change selection behavior.
- The guard does not enable live automation, live auto-hot, risk-profile
  switching, or adjustment execution.
- Server code-only deployment is still required before claiming server
  completion.
