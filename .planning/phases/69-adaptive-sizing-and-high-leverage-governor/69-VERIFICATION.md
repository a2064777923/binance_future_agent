---
phase: 69-adaptive-sizing-and-high-leverage-governor
status: passed
verified_at: 2026-06-21T02:30:30Z
requirements:
  - SIZE-01
  - SIZE-02
  - SIZE-03
  - SIZE-04
---

# Phase 69 Verification

## Result

Status: passed.

Phase 69 delivers local execution-risk, sizing, diagnostics, config, and test changes. It does not deploy code to the server, place orders, cancel orders, or manage `BTWUSDT`. Server env cap widening during this phase was an operator-directed live env action and remains Phase 70's canary subject.

## Requirement Evidence

| Requirement | Status | Evidence |
|-------------|--------|----------|
| SIZE-01 | Passed | `apply_adaptive_sizing_governor` raises or lowers final notional within hard caps using signal quality, stop distance, liquidity, volatility, available balance, manual pressure, and paper-guard health. Covered by `tests.test_execution_sizing`. |
| SIZE-02 | Passed | High-leverage stop/liquidation, stop-distance, liquidity, and volatility checks block or downsize unsafe setups. Covered by `tests.test_execution_sizing`. |
| SIZE-03 | Passed | `RiskState` separates bot and manual exposures, risk checks include account available balance and total initial margin, and exposure status reports manual margin pressure without counting manual slots. Covered by `tests.test_agent_runner`, `tests.test_execution_risk`, and `tests.test_ops_exposure_status`. |
| SIZE-04 | Passed | Governor settings are included in risk-profile preview/apply allowlists and env examples, preserving explicit preview/rollback gates for risk increases. Covered by `tests.test_ops_risk_profile`. |

## Automated Checks

- `python -m unittest tests.test_agent_runner tests.test_execution_sizing tests.test_execution_risk tests.test_ops_exposure_status tests.test_ops_risk_profile -v`
  - Passed: 47 tests.
- `python -m unittest discover -s tests`
  - Passed: 420 tests.
- `git diff --check`
  - Passed: no whitespace errors.
- `node "$HOME/.codex/gsd-core/bin/gsd-tools.cjs" query audit-open --json`
  - Passed: `has_open_items=false`, total open items `0`.

## Behavior Smoke

Synthetic tests verify that:

- Strong setups can scale up only inside configured hard caps.
- Weak setups downsize and cannot upsize solely because capacity is wide.
- High-leverage stop/liquidation geometry can block a trade before AI.
- Manual `BTWUSDT` margin pressure can block entry capacity without consuming a bot-managed slot.
- Candidate diagnostics include `bfa_adaptive_sizing_governor_v1` under both candidate evaluation and setup price basis.

## Residual Risk

This phase improves sizing safety and traceability; it does not prove profitability. Live behavior still depends on Phase 70 deployment, current Binance account state, live timers, exchange filters, and real market slippage.
