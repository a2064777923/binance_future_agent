---
phase: 58
plan: 01
status: complete
completed: 2026-06-21
commit: pending
---

# Summary: Phase 58 Plan 01

## What Changed

- Extended `ops strategy-promotion-check` output with explicit
  `promotion_stage` values for `collect_more_paper`,
  `forward_paper_allowed`, and `live_resume_eligible`.
- Added promotion evidence boundaries so public Lana/Square/X claims are
  design inputs only, never promotion proof.
- Added read-only `ops manual-loss-review`.
  - Loads append-only `manual_loss_incident` artifacts.
  - Compares each incident against max leverage, protective stop requirement,
    liquidation-distance warning, and adaptive forward-paper symbol/side
    blocks.
  - Reports whether the incident would be blocked by risk guard, blocked by
    paper guard, warned/reduced, or not caught.
- Exposed the new command through CLI with `--skip-paper-guard`.

## Server Evidence

- Deployed read-only Phase 58 code to `/opt/binance-futures-agent/app`.
- Paused and restored both live and paper timers during deploy.
- Final server state after deploy:
  - `binance-futures-agent-live.timer=active`
  - `binance-futures-agent-live.service=inactive`
  - `binance-futures-agent-paper.timer=active`
  - `binance-futures-agent-paper.service=inactive`
- Server current-data matrix artifact:
  `/opt/binance-futures-agent/app/runtime/phase58-current-matrix.json`.
  - Selected 40 hot symbols.
  - Intervals: `5m`, `15m`.
  - Variants: `quant_setup_selective`,
    `quant_setup_selective_guarded`, `quant_setup_loss_recalibrated`.
  - Overall: `mixed_candidate_collect_more_data`.
  - `quant_setup_selective`: total net PnL `0.4862443`, worst drawdown
    `0.62845092`, verdict `mixed_candidate_collect_more_data`.
  - `quant_setup_selective_guarded`: total net PnL `0.87008078`, worst
    drawdown `0.59906869`, verdict `mixed_candidate_collect_more_data`.
- Server promotion checks:
  - all intervals: `keep_live_paused`, `promotion_stage=collect_more_paper`,
    `promotion_allowed=false`, `live_resume_allowed=false`.
  - selected `5m`: `keep_live_paused`,
    `promotion_stage=collect_more_paper`, `promotion_allowed=false`,
    `live_resume_allowed=false`.
- Server production DB `manual-loss-review` currently reports
  `no_manual_loss_incidents`.

## Files Changed

- `src/bfa/ops/strategy_promotion.py`
- `src/bfa/ops/manual_loss_review.py`
- `src/bfa/cli.py`
- `tests/test_ops_strategy_promotion.py`
- `tests/test_ops_manual_loss_review.py`
- `tests/test_cli.py`

## Notes

This phase improves evidence quality and reviewability, but it does not promote
the strategy to live-resume eligibility. The latest current-data evidence says
to keep collecting paper and continue iterating rather than treating public
claims or one positive aggregate as proof.
