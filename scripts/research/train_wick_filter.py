"""Train an ML wick-reversal filter for the micro-grid leg (A).

Builds a feature/label dataset from real aggTrades tick-precise simulation:
for each evaluation window that produces a valid micro state + order, record
continuous features about the wick setup and label whether the simulated trade
was profitable. Trains LightGBM with time-based split, reports feature
importance + threshold sweep. The resulting filter (A) is then combined with
the spike-depth entry (B) to reject high-vol-but-non-reverting setups.

No live env/DB/service. Uses the user-provided aggTrades cache.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "micro_research", ROOT / "scripts" / "run_micro_grid_research.py"
)
research = importlib.util.module_from_spec(_spec)
sys.modules["micro_research"] = research
_spec.loader.exec_module(research)

AGG_CACHE = Path(r"D:/教青垃圾系統/binance/aggTrades-cache")
NOTIONAL = 20.0
VAL_FRACTION = 0.30  # last 30% by time is validation

FEATURE_NAMES = [
    "width_percent", "stable_width_percent", "instantaneous_vol",
    "recent_spike_depth", "close_position", "turn_count", "edge_alternation_count",
    "reversal_response_rate", "path_efficiency", "drift_to_width",
    "recent_path_efficiency", "recent_drift_to_width", "amplitude_percent",
    "bollinger_width_percent", "center_cross_count", "score",
    "long_pullback_quality", "short_pullback_quality",
    "stochastic_k", "stochastic_slope", "triple_ema_bias",
    "entry_taker_buy_ratio",
]


def ticks_to_seconds(symbol, ticks):
    from collections import defaultdict
    buckets = defaultdict(list)
    for t in ticks:
        buckets[t.time_ms // 1000].append((t.price, t.quantity, t.buyer_maker))
    if not buckets:
        return []
    bars = []
    secs = sorted(buckets)
    prev = None
    for sec in range(secs[0], secs[-1] + 1):
        tr = buckets.get(sec)
        if tr:
            ps = [t[0] for t in tr]
            qv = sum(t[0] * t[1] for t in tr)
            tbq = sum(t[0] * t[1] for t in tr if t[2])
            bars.append(research.BacktestBar(symbol=symbol, open_time=sec*1000,
                open=ps[0], high=max(ps), low=min(ps), close=ps[-1],
                volume=0.0, close_time=sec*1000+999, quote_volume=qv, taker_buy_quote_volume=tbq))
            prev = ps[-1]
        elif prev is not None:
            bars.append(research.BacktestBar(symbol=symbol, open_time=sec*1000,
                open=prev, high=prev, low=prev, close=prev,
                volume=0.0, close_time=sec*1000+999, quote_volume=0.0, taker_buy_quote_volume=0.0))
    return bars


def collect_features(symbol, day, profile, tick_source):
    """Return list of (features_dict, win_label, net_pnl) for one day."""
    stream = tick_source.load_day(day)
    if not stream.ticks:
        return []
    seconds = ticks_to_seconds(symbol, stream.ticks)
    if len(seconds) < 1500:
        return []
    rows = []
    window = 1200
    stride = 600
    for start in range(600, len(seconds) - window - 500, stride):
        chunk = seconds[start:start + window]
        if len(chunk) < window:
            continue
        state, reasons = research.build_micro_grid_state(chunk, len(chunk) - 1, profile)
        if state is None:
            continue
        orders = research.build_grid_orders(symbol, state, profile)
        if not orders:
            continue
        valid = [o for o in orders
                 if research.is_passive_entry(o.side, o.entry_price, state.current_price, profile)
                 and abs(o.target_price - o.entry_price) > 0
                 and abs(o.entry_price - o.stop_price) > 0]
        if not valid:
            continue
        best = max(valid, key=lambda o: o.size_weight)
        ot = tick_source.stream_for_order(chunk, best, profile)
        trade, status, _ = research.simulate_grid_basket(
            chunk, [best], profile, base_notional_usdt=NOTIONAL, tick_stream=ot)
        if trade is None:
            continue
        feats = {
            "width_percent": state.width_percent,
            "stable_width_percent": state.stable_width_percent,
            "instantaneous_vol": state.instantaneous_vol_percent,
            "recent_spike_depth": state.recent_spike_depth_percent,
            "close_position": state.close_position_percent,
            "turn_count": state.turn_count,
            "edge_alternation_count": state.edge_alternation_count,
            "reversal_response_rate": state.reversal_response_rate,
            "path_efficiency": state.path_efficiency,
            "drift_to_width": state.drift_to_width,
            "recent_path_efficiency": state.recent_path_efficiency,
            "recent_drift_to_width": state.recent_drift_to_width,
            "amplitude_percent": state.amplitude_percent,
            "bollinger_width_percent": state.bollinger_width_percent,
            "center_cross_count": state.center_cross_count,
            "score": state.score,
            "long_pullback_quality": state.long_pullback_quality,
            "short_pullback_quality": state.short_pullback_quality,
            "stochastic_k": state.stochastic_k,
            "stochastic_slope": state.stochastic_slope,
            "triple_ema_bias": state.triple_ema_bias,
            "entry_taker_buy_ratio": state.entry_taker_buy_ratio,
        }
        rows.append((feats, int(trade.net_pnl_usdt > 0), trade.net_pnl_usdt))
    return rows


def main():
    profile = research.MicroGridProfile(
        min_width_percent=0.08, min_edge_alternations=2, min_reversal_response_rate=0.20,
        max_drift_to_width=2.0, wick_min_samples=4, wick_model_mode="ev",
        dynamic_wick_enabled=True, precision_entry_enabled=True,
        min_turn_count=3, min_center_crosses=1, min_width_cost_ratio=0.0,
        max_path_efficiency=0.7, vol_regime_enabled=True,
        spike_depth_entry_enabled=True,  # B is on; A learns on top of B
    )
    # collect from multiple high-vol symbols/days
    jobs = [
        ("WLDUSDT", [date(2026,3,d) for d in [22,23,24,25,26,27]]),
        ("SUIUSDT", [date(2026,3,d) for d in [1,2,5,6]]),
        ("PUMPUSDT", [date(2026,3,d) for d in [1,5,6]]),
        ("1000PEPEUSDT", [date(2026,3,d) for d in [22,23,27]]),
        ("HYPEUSDT", [date(2026,3,d) for d in [2]]),
    ]
    all_rows = []
    for sym, days in jobs:
        sym_dir = AGG_CACHE / sym
        if not sym_dir.exists():
            continue
        ts = research.TickReplaySource(symbol=sym, start=days[0], end=days[-1], cache_dir=AGG_CACHE)
        for day in days:
            rows = collect_features(sym, day, profile, ts)
            print(f"  {sym} {day}: {len(rows)} samples")
            all_rows.extend(rows)
    if not all_rows:
        print("no samples collected")
        return 1
    print(f"\ntotal samples: {len(all_rows)}  win_rate={sum(r[1] for r in all_rows)/len(all_rows):.3f}")

    X = np.array([[r[0].get(k, 0.0) or 0.0 for k in FEATURE_NAMES] for r in all_rows], dtype=float)
    y = np.array([r[1] for r in all_rows], dtype=int)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    n = len(X)
    cut = int(n * (1 - VAL_FRACTION))
    Xtr, ytr = X[:cut], y[:cut]
    Xva, yva = X[cut:], y[cut:]
    print(f"train={len(Xtr)} (wr={ytr.mean():.3f})  val={len(Xva)} (wr={yva.mean():.3f})")

    dtr = lgb.Dataset(Xtr, label=ytr, feature_name=FEATURE_NAMES)
    dva = lgb.Dataset(Xva, label=yva, feature_name=FEATURE_NAMES, reference=dtr)
    params = {
        "objective": "binary", "metric": ["binary_logloss", "auc"],
        "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 10,
        "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 5,
        "lambda_l1": 1.0, "verbose": -1,
    }
    model = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dtr, dva],
                      callbacks=[lgb.log_evaluation(100), lgb.early_stopping(40)])
    proba_va = model.predict(Xva)
    auc = roc_auc_score(yva, proba_va) if len(np.unique(yva)) > 1 else float("nan")
    base = yva.mean()
    print(f"\nval AUC={auc:.4f}  base WR={base:.3f}")
    print("\nthreshold sweep (val):")
    for t in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]:
        m = proba_va >= t
        if m.sum() == 0:
            continue
        wr = yva[m].mean()
        print(f"  t>={t:.2f}: n={m.sum():4d} wr={wr:.3f} lift={wr/base:.2f}x")
    print("\nfeature importance (gain):")
    imp = dict(zip(FEATURE_NAMES, model.feature_importance(importance_type="gain").tolist()))
    for k, v in sorted(imp.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {k:28s} {v:10.1f}")
    # save model
    Path("data/research").mkdir(parents=True, exist_ok=True)
    model.save_model("data/research/wick_filter_v1.txt")
    print("\nsaved data/research/wick_filter_v1.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
