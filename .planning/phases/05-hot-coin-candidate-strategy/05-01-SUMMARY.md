---
phase: 05-hot-coin-candidate-strategy
plan: 01
subsystem: candidate-scoring
tags:
  - strategy
  - candidates
  - replay
key-files:
  created:
    - src/bfa/strategy/__init__.py
    - src/bfa/strategy/candidates.py
    - src/bfa/strategy/features.py
    - tests/fixtures/strategy/replay_packet.json
    - tests/test_strategy_features.py
    - tests/test_strategy_candidates.py
metrics:
  tests: "python -m unittest tests.test_strategy_features tests.test_strategy_candidates -v"
  test_count: 5
  requirements:
    - STR-01
    - STR-02
    - STR-03
    - STR-04
requirements-completed:
  - STR-01
  - STR-02
  - STR-03
  - STR-04
---

# Summary: Plan 01 - Candidate Features And Scoring

## Result

Added pure deterministic hot-coin candidate feature extraction and scoring over
Phase 4 replay packets. The generator ranks confirmed hot symbols, emits reason
codes and data-quality notes, preserves source/market event IDs, and explicitly
reports rejected symbols.

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_strategy_features tests.test_strategy_candidates -v` | Passed, 5 tests |
| `git diff --check` | Passed |

## Self-Check

PASSED. Candidate generation is replay-deterministic and does not call OpenAI,
Binance private APIs, source collectors, wall-clock time, or order endpoints.

