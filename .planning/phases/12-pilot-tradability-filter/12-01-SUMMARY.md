# Summary 12-01: Pilot Tradability Filter

## Completed

- Added Binance execution-filter features to hot-coin candidate extraction:
  `min_qty`, `step_size`, `min_notional`, and computed
  `min_executable_notional`.
- Passed `BFA_MAX_POSITION_NOTIONAL_USDT` into strategy candidate generation
  from both the live runner and the strategy CLI.
- Rejected candidates whose computed minimum executable notional is above the
  pilot cap with `min_executable_notional_exceeds_cap`.
- Added `min_executable_notional` to compact AI context and tightened AI
  instructions around fitting both executable minimum and max cap.
- Added deterministic AI validation error `notional_below_min_executable`.
- Added tests for cap-incompatible candidate rejection, agent AI-call skipping,
  compact AI context, and AI validation.

## Evidence

- Current public Binance USD-M filter check during implementation showed:
  - BTCUSDT minimum executable notional was above the 20 USDT cap.
  - ETHUSDT minimum executable notional was slightly above the 20 USDT cap.
  - SOLUSDT was below the 20 USDT cap.
- `python -m unittest tests.test_ai_decision tests.test_strategy_candidates tests.test_agent_runner tests.test_execution_filters tests.test_execution_risk`
  passed 27 tests.
- `python -m unittest discover -s tests` passed 187 tests.
- `git diff --check` passed with Windows LF-to-CRLF warnings only.

## Follow-Up

- Keep the pilot caps unchanged unless the operator explicitly approves a new
  risk profile after backtests and live evidence.
- After deployment, observe timer cycles for either `no_candidate` when all hot
  candidates are cap-incompatible or AI calls only for pilot-tradable symbols.
- LVA-05 still depends on a future submitted live entry and remains untriggered.
