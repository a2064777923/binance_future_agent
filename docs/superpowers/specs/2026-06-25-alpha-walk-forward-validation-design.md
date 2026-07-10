# Alpha Walk-Forward Validation Framework — Design

**Created:** 2026-06-25
**Status:** Design (pending implementation)
**Motivation:** Post-GSD live iterations established competent safety/execution/
observability engineering (isolated deploy, kill switch, pending-limit watchdog,
position sentinel, protective-order -4130 handling). The unresolved problem is
purely at the alpha layer: no edge has survived out-of-sample, post-cost scrutiny.
This framework establishes a reusable, fail-closed validation pipeline that
produces an auditable OOS verdict per strategy leg before any leg is allowed to
resume live trading.

## Requirements (operator-specified, in priority order)

1. **True walk-forward.** Split data into non-overlapping month segments. Select
   parameters only on the training segment; evaluate only on the held-out
   segment. The evaluation must run the FULL candidate flow (not a post-hoc
   subset of e.g. 25 trades) and be post-cost positive.
2. **Tighten the reward/cost gate.** Raise `min_reward_cost_ratio` well above
   1.0 (at least 1.8–2.5) so edge genuinely covers stop-loss probability.
3. **Funding cost in all backtests.** Accumulate funding payments over each
   position's hold time across funding intervals.
4. **<30 trades = unverified.** Any configuration that is only positive on
   fewer than 30 trades is treated as unverified and must not go live.

## Decisions (from brainstorming)

- **Scope:** All three legs in one framework — trend (`quant_setup_live_action_flow`),
  micro-grid (RANGE), limit-range. Produce a verdict matrix for all legs.
- **Walk-forward data:** Pull additional months (Dec 2025 + Jan + Feb 2026
  aggTrades) to form true multi-month non-overlapping folds. Trend leg uses
  kline + funding history and may span more months.
- **Framework location:** First-class citizen in `src/bfa/backtest`. The verdict
  is a report consumed by the operator (human gate) before live resume. The
  existing `min_trade_count=5` defaults are NOT changed and the verdict is NOT
  auto-wired into `strategy_promotion` / `live_resume_readiness` / 
  `operator_resume_decision`. The gate is enforced by documented operator policy
  plus an auditable artifact, not by code.
- **Parameter selection:** Grid search key knobs on the training segment; the
  held-out segment evaluates only the single best combination selected on train.

## Architecture (Approach C: shared cost/funding library + per-leg adapters +
walk-forward orchestrator)

```
src/bfa/backtest/
├── cost.py            NEW  unified CostModel: per-symbol fees + slippage + funding
├── walk_forward.py    NEW  WalkForwardValidator: fold split, grid search, verdict
├── adapters.py        NEW  per-leg FoldRunner adapters behind a unified interface
├── engine.py          MINOR  taker-both-legs cost delegates to CostModel
├── models.py          MINOR  BacktestConfig/Result accept CostModel + FoldResult
└── matrix.py          UNCHANGED  may consume verdict artifact, no auto-gate

src/bfa/market/
└── funding_history.py NEW  fapi/v1/fundingRate history loader + cache

scripts/research/
└── run_alpha_validation.py  NEW  thin CLI entry -> WalkForwardValidator -> verdict
```

### Unified adapter contract

```python
@dataclass(frozen=True)
class FoldRange:
    leg: str                       # "trend" | "micro" | "limit_range"
    symbols: tuple[str, ...]
    train_start: pd.Timestamp
    train_end:   pd.Timestamp
    test_start:  pd.Timestamp
    test_end:    pd.Timestamp

@dataclass(frozen=True)
class FoldResult:
    leg: str
    fold_id: str
    split: str                      # "train" | "test"
    trades: list[dict]             # each: net_pnl (post fee+slip+funding), entry/exit ts, symbol
    candidate_accounting: dict     # evaluated_windows / orders_created / filled / rejected_reasons / fill_rate
    funding_paid: float
    params: dict

class FoldRunner(Protocol):
    def run_fold(self, range: FoldRange, params: dict) -> FoldResult: ...
```

Three adapters:
- `TrendFoldRunner` wraps `strategy.setup.build_trade_setup` + the backtest
  engine runner, fed by kline + funding history.
- `MicroGridFoldRunner` wraps the callable core of
  `scripts/run_micro_grid_research.py` (full candidate flow with
  `evaluated_windows -> orders_created -> filled -> fill_rate` accounting), fed
  by `TickReplaySource` over the aggTrades cache.
- `LimitRangeFoldRunner` wraps the callable core of
  `scripts/run_limit_range_research.py`.

Adding a leg = adding an adapter; the orchestrator does not change.

## Unified CostModel (per-symbol tiers + funding)

```python
@dataclass(frozen=True)
class SymbolFeeTier:
    maker_fee_bps: float
    taker_fee_bps: float

@dataclass(frozen=True)
class CostModel:
    fee_tiers: dict[str, SymbolFeeTier]   # per-symbol, curated from public schedule
    default_tier: SymbolFeeTier           # fallback for unlisted symbols (maker 2.0 / taker 4.0 bps)
    slippage_bps: float = 5.0             # taker legs
    maker_slippage_bps: float = 1.0       # passive limit fills still have micro slip
    funding_interval_hours: int = 8       # Binance USD-M default 0/8/16 UTC
    funding_on_long: bool = True

    def tier(self, symbol) -> SymbolFeeTier
    def round_trip_cost_percent(self, symbol, entry_is_maker, exit_is_maker) -> float
    def trade_fees_usdt(self, symbol, entry_price, exit_price, qty, entry_is_maker, exit_is_maker) -> float
    def trade_slippage_usdt(self, symbol, ref_entry, ref_exit, qty, entry_is_maker, exit_is_maker) -> float
    def funding_cost_usdt(self, symbol, entry_time_ms, exit_time_ms, side, notional,
                          funding_rates: list[tuple[int, float]]) -> float
```

**Unified net PnL (all legs identical):**
```
net_pnl = gross_pnl(ref fills, no slip baked in)
        - trade_fees_usdt(...)
        - trade_slippage_usdt(...)
        - funding_cost_usdt(...)
```
This fixes the existing engine bug where slippage was recorded but not subtracted
from `net_pnl` (`engine.py:274,452`): slippage becomes explicit, fill prices use
reference prices, costs are transparent and auditable.

**Per-leg maker/taker attribution (reflects real order type):**
- trend: entry taker, exit taker (market / stop-triggered).
- micro-grid: entry maker (post-only limit), exit taker (stop / market close).
- limit-range: reversion entry maker, continuation entry taker, exit taker
  (script's existing logic at `run_limit_range_research.py:92` passes through
  `entry_is_maker`).

So `round_trip_cost_percent` (the denominator of `min_reward_cost_ratio`) is
correct per-leg: micro's maker entry costs less than trend's taker entry.

**Funding cost method:**
- Funding times = UTC 0/8/16 (USD-M default).
- For each funding time `t_k` in `[entry, exit]`:
  `cost += side_sign * notional * rate_k`, with `notional` held constant at the
  entry notional (simplifying, conservative; mark-price-per-interval refinement
  is a later option).
- Position shorter than one interval and not crossing a time -> funding = 0
  (the common micro case).
- funding rate history from the new loader.

**Fee tier data source:** `fee_tiers.json` is a committed, human-curated config
seeded from Binance's public USD-M fee schedule. Each entry carries a source URL
+ query date. The structure is designed so the data source can later be swapped
to an authenticated `commissionRate` snapshot without changing `CostModel`'s
interface. **Known limitation:** the public schedule excludes the operator's VIP
tier + BNB discount, so OOS cost may diverge from live actuals; documented in
the verdict artifact's `cost_model_snapshot`.

**Change sites:**
- `engine.py:245-274` taker-both-legs cost -> call `CostModel`; `engine.py:509`
  `funding_rate:0.0` -> inject real funding and subtract into net_pnl.
- `setup.py:1338,1586` `round_trip_cost_percent` + `_post_cost_diagnostics`
  -> reference `CostModel`; live behavior unchanged (still allows
  `min_post_cost_edge_ratio=0.0`).
- micro/limit-range adapters: recompute net_pnl on top of the script's net using
  `CostModel` (including funding) WITHOUT mutating the 4400-line scripts'
  internal cost constants.
- NEW `tests/test_backtest_cost.py`.

## Walk-forward split + grid search

**Expanding-window walk-forward (non-overlapping train/test):**
```
Fold 1:  train = 2025-12            test = 2026-01
Fold 2:  train = 2025-12..2026-01   test = 2026-02
Fold 3:  train = 2025-12..2026-02   test = 2026-03   <- final holdout, never in train
```
- Train only selects params; test only evaluates the selected best combination.
- Train/test never overlap; each test month is evaluated once.
- March is the final OOS holdout and never enters any fold's training — the
  strongest out-of-sample evidence.
- If a symbol-month lacks ticks/klines after the pull, that cell is flagged
  `insufficient_data` and does not count as a pass.

**Grid search (training segment, key knobs per leg):**
| leg | knob | grid |
|---|---|---|
| trend | min_reward_cost_ratio | 1.0 / 1.8 / 2.2 / 2.5 |
| trend | take_profit mult / stop mult | 2 geometries |
| micro | min_reward_cost_ratio | 1.0 / 1.8 / 2.2 / 2.5 |
| micro | target fraction (0.5/0.8/1.0 x spike) | 0.5 / 0.8 / 1.0 |
| micro | wick depth gate | current / strict (deepest only) |
| limit-range | min_reward_cost_ratio | 1.0 / 1.8 / 2.2 / 2.5 |
| limit-range | target/stop geometry | 2 geometries |

- ~16 combos/leg; 3 folds x 3 legs x 16 x 26 symbols ~ 3700 fold-runs.
- Training objective: post-cost+funding `net_pnl > 0` AND highest
  `profit_factor`, AND training trade count >= 10 (anti-overfit on a "2 wins"
  fluke; permissive enough to allow selection on a single dense month, strict
  enough to reject tiny-sample luck). A combo with <10 training trades is not
  eligible to be selected even if its profit_factor is highest.
- The best combination is fixed, then run once on the test segment.
- Anti-overfit rule enforced in code: the test runner receives only the selected
  params, never the grid; test results cannot feed back into selection.

## Verdict artifact + pass bar

JSON artifact under `data/research/alpha_validation/` (gitignored runtime); a
small redacted summary may be committed to docs. Structure:
- `folds`, `data_months`, `cost_model_snapshot` (fee source, default tier, the
  VIP/BNB-discount caveat).
- per leg: `selected_params_per_fold`, `oos_test_results` (per fold: trades,
  net_pnl, win_rate, profit_factor, funding_paid, candidate_accounting),
  `oos_aggregate` (total_trades, agg_net_pnl, agg_profit_factor, worst_fold_pf),
  `verdict`.

**Pass bar (all four must pass for `oos_positive`; any miss downgrades):**
1. OOS post-cost+funding positive: `agg_net_pnl > 0` AND `agg_profit_factor > 1.0`.
2. Full candidate flow, not post-hoc filtered: every test fold's
   `candidate_accounting` complete (evaluated_windows -> orders_created ->
   filled -> rejected) with real `fill_rate`; must not report only fills.
3. Edge covers stop probability: the leg's selected `min_reward_cost_ratio >= 1.8`.
4. Sufficient sample: OOS `total_trades >= 30`. `<30 -> unverified`, must not go
   live. Hard rule: if ANY fold's test segment is positive only on `<30` trades,
   the whole leg is `unverified` even if the aggregate is >= 30 (no "5-win fluke
   inflates aggregate" loophole).

**Verdict levels:** `oos_positive` (all 4), `oos_positive_thin` (1+2+4 pass but
`agg_profit_factor in (1.0, 1.3]`), `oos_negative` (condition 1 fails),
`unverified` (condition 4 fails or insufficient data).

**Human-gate enforcement:**
- No change to `min_trade_count=5` defaults; no auto-wiring into
  `strategy_promotion` / `live_resume_readiness` / `operator_resume_decision`.
- NEW read-only CLI `ops alpha-verdict` prints the verdict summary; the operator
  reviews it before resuming live.
- `docs/agent-handoff.md`, `POST-GSD-LIVE-ITERATIONS.md`, and an `AGENTS.md`
  safety rule record the policy: a leg without an `oos_positive` /
  `oos_positive_thin` verdict must not resume live. The verdict artifact is the
  auditable evidence.

## Data acquisition

- aggTrades pull (Dec 2025 + Jan + Feb 2026): reuse
  `run_second_agg_compound_backtest.py:260 fetch_zip` (Binance Vision,
  cache-first, auto-download on miss) + `read_aggtrade_zip:279`.
- funding rate history: NEW `src/bfa/market/funding_history.py` pulling
  `fapi/v1/fundingRate` (already used live at `binance_rest.py:110`), persisted
  to a gitignored cache.
- trend kline: reuse `scripts/research/fetch_history.py` (5m/15m), more months.

## Compute & phasing

- Full grid x folds x legs x 26 symbols is heavy, especially micro tick-precise.
- Phase 1: trend leg full (kline cheap; it is the live main leg; highest stakes)
  -> produce the first real verdict.
- Phase 2: micro / limit-range on the 7 high-density symbols
  (BTC/ETH/SOL/SUI/HYPE/ONDO/PUMP) to validate the framework, then expand.
- Verdict is produced per-leg incrementally; the trend verdict is the first
  "result".

## Testing

- unit: `cost.py` (per-symbol tier lookup, funding accrual across intervals,
  long/short sign, no-cross-interval = 0), fold split (non-overlap, expanding),
  grid search (test segment never sees grid), verdict 4 pass-bar conditions
  (<30 -> unverified, any-fold <30 -> unverified).
- adapter contract tests: each adapter returns FoldResult with complete
  `candidate_accounting`.
- regression: `python -m unittest discover -s tests` stays green after the
  `engine.py` cost refactor.
- the actual run producing the verdict artifact IS the deliverable result.

## Out of scope

- No live trading, no server mutation, no env changes, no order placement.
- No auto-gating of live resume (human gate by policy + artifact).
- No new strategy logic; this only VALIDATES existing legs under a rigorous
  OOS/post-cost/funding regime.
- VIP/BNB-discount-accurate fees are a future enhancement (swap data source, not
  interface).
