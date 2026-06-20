---
phase: 54
name: Guarded Paper Evidence Promotion
created: 2026-06-21
source: inline-gsd-fallback
---

# Context: Phase 54

## Goal

Collect and evaluate current guarded setup evidence before any live resume
discussion.

## Requirements

- PEV-01: Operator can rerun the current-data hot-symbol matrix suite on the
  server or locally for `quant_setup_selective_guarded` and compare the result
  against the archived Phase 50 candidate evidence.
- PEV-02: Server paper collection can run or preview the selected guarded
  variant without creating live order intents, restoring live automation, or
  changing exchange state.
- PEV-03: Post-change forward-paper performance can be evaluated from a clear
  variant/timestamp boundary with minimum outcomes, positive PnL, minimum win
  rate, minimum profit factor, and drawdown caps.

## Decisions

- Use `quant_setup_selective_guarded`, the Phase 50 best candidate, as the
  evidence variant.
- Live timer and live service must remain inactive.
- Paper evidence may mutate only paper tables/artifacts; it must not create
  `order_intents` or signed Binance order calls.
- A fail-closed result is acceptable when samples are insufficient or negative.
- Runtime JSON evidence is not committed, but summary/verification must record
  the secret-safe result shape and paths.

## Existing Entry Points

- `python -m bfa.cli backtest matrix-suite`
- `python -m bfa.cli ops forward-paper-run`
- `python -m bfa.cli ops forward-paper-performance-check`
- `python -m bfa.cli ops live-resume-readiness`

## Expected Output

- A current matrix-suite report for `quant_setup_selective_guarded`.
- A server guarded forward-paper run or preview.
- A post-change performance gate using an explicit timestamp boundary.
- Updated Phase 54 summary/verification that says whether evidence is promoted,
  blocked, or needs more samples.
