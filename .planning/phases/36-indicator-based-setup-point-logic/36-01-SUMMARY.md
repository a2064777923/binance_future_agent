# Summary 36-01: Indicator-Based Setup Point Logic

## Completed

- Added `bfa.strategy.indicators`, a small dependency-free indicator module
  for kline-derived market structure.
- Live feature extraction now stores indicator-derived ATR, VWAP, EMA spread,
  RSI, support/resistance, realized volatility, momentum, and volume impulse
  when kline snapshots are available.
- The `quant_setup` backtest path now builds candidates with the same
  indicator helper used by live feature extraction.
- Deterministic setup scoring now includes trend structure, RSI regime, and
  volume impulse factors in addition to the existing setup factors.
- Setup output now includes `price_basis`, showing entry reference, stop
  anchor, target anchor, support/resistance, ATR, EMA, RSI, and risk/reward
  geometry.
- AI compact context and `ops trade-trace` expose the new indicators and
  `price_basis`, while AI remains overlay/veto only.

## Evidence

- Focused tests passed for indicators, feature extraction, setup, AI schema,
  backtest, and trade trace.
- Agent runner regression tests passed.
- A manual setup smoke produced a traceable long setup with factor scores,
  support-based stop basis, structure-aware target basis, and no warnings.

## Operational Result

This phase makes the strategy materially less thin than the old SOLUSDT path:
new setups can explain factor contributions and point geometry before AI is
consulted. It still does not prove profitability; the next step is broader
recent-market matrix backtesting and forward-paper observation.

No live service, timer, exchange order, position adjustment, or risk profile was
changed.
