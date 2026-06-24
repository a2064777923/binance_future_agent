"""Trend-leg feature engineering + ML filter training.

Reads long-history klines (5m + 15m) produced by fetch_history.py, builds a
row-per-bar feature dataset that mirrors the live trend-leg signals but uses
*continuous* feature values (not boolean gates), labels each bar by whether a
long/short entry would have hit +1.5R before -1R within a forward window, then
trains a LightGBM classifier and reports feature importance + univariate
significance. Train/validation are split by *time* (last 25% of each symbol is
held out) to avoid leakage.

No live env, DB, or service is touched. Pure local research.

Usage:
    python scripts/research/train_trend_filter.py
    python scripts/research/train_trend_filter.py --report results/research/trend_filter_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
KLINES_DIR = ROOT / "data" / "research" / "klines"
OUT_DIR = ROOT / "results" / "research"

# --- label geometry ---
R_MULT_TARGET = 1.5      # take-profit in R units
R_MULT_STOP = 1.0        # stop-loss in R units
ATR_PERIOD = 14
FORWARD_BARS = 36        # 3h of 5m bars to resolve the trade
MIN_LOOKBACK = 30        # need enough history for indicators

# time-based validation split: last 25% of each symbol is validation
VAL_FRACTION = 0.25


# ---------------------------------------------------------------------------
# Indicators (dependency-free, mirror bfa.strategy.indicators)
# ---------------------------------------------------------------------------

def ema(values: np.ndarray, period: int) -> np.ndarray:
    if period <= 0 or len(values) == 0:
        return np.full_like(values, np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    out = np.empty(len(values), dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * alpha + out[i - 1] * (1 - alpha)
    return out


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full(len(closes), np.nan, dtype=float)
    if len(closes) < 2:
        return out
    deltas = np.diff(closes)
    for i in range(period, len(closes)):
        chunk = deltas[i - period:i]
        gains = np.where(chunk > 0, chunk, 0.0).mean()
        losses = np.where(chunk < 0, -chunk, 0.0).mean()
        if losses == 0:
            out[i] = 100.0 if gains > 0 else 50.0
        else:
            rs = gains / losses
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def atr_percent(highs, lows, closes, period: int = ATR_PERIOD) -> np.ndarray:
    n = len(closes)
    out = np.full(n, np.nan, dtype=float)
    if n == 0:
        return out
    tr = np.empty(n, dtype=float)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    for i in range(period, n):
        out[i] = tr[i - period:i].mean() / closes[i] * 100.0 if closes[i] > 0 else np.nan
    return out


def rolling_mean(a: np.ndarray, w: int) -> np.ndarray:
    if w <= 1:
        return a.copy()
    c = np.cumsum(np.insert(a, 0, 0.0))
    return (c[w:] - c[:-w]) / w


def realized_vol(closes: np.ndarray, w: int = 20) -> np.ndarray:
    n = len(closes)
    out = np.full(n, np.nan, dtype=float)
    if n < 3:
        return out
    rets = np.zeros(n, dtype=float)
    rets[1:] = (closes[1:] / closes[:-1] - 1.0) * 100.0
    for i in range(w, n):
        chunk = rets[i - w:i]
        out[i] = chunk.std(ddof=1)
    return out


# ---------------------------------------------------------------------------
# Load klines
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> dict:
    opens = []
    highs = []
    lows = []
    closes = []
    qvs = []
    tbqs = []
    opens_t = []
    with path.open(encoding="utf-8") as fh:
        r = csv.reader(fh)
        next(r, None)  # header
        for row in r:
            if len(row) < 11:
                continue
            opens.append(float(row[1]))
            highs.append(float(row[2]))
            lows.append(float(row[3]))
            closes.append(float(row[4]))
            qvs.append(float(row[7]))
            tbqs.append(float(row[10]))
            opens_t.append(int(row[0]))
    return {
        "open": np.array(opens, dtype=float),
        "high": np.array(highs, dtype=float),
        "low": np.array(lows, dtype=float),
        "close": np.array(closes, dtype=float),
        "qv": np.array(qvs, dtype=float),
        "tbq": np.array(tbqs, dtype=float),
        "open_time": np.array(opens_t, dtype=np.int64),
    }


# ---------------------------------------------------------------------------
# Feature construction + labeling
# ---------------------------------------------------------------------------

def build_features(k5: dict, k15: dict | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (X, y, side) where each row is one bar (entry on next open)."""
    close = k5["close"]
    high = k5["high"]
    low = k5["low"]
    qv = k5["qv"]
    tbq = k5["tbq"]
    openp = k5["open"]
    n = len(close)

    ema5 = ema(close, 5)
    ema12 = ema(close, 12)
    ema_spread = (ema5 - ema12) / np.where(ema12 == 0, np.nan, ema12) * 100.0
    r = rsi(close, 14)
    atr_p = atr_percent(high, low, close)
    rvol = realized_vol(close, 20)

    # momentum features
    mom6 = np.zeros(n)
    mom12 = np.zeros(n)
    mom6[6:] = (close[6:] / close[:-6] - 1.0) * 100.0
    mom12[12:] = (close[12:] / close[:-12] - 1.0) * 100.0
    micro_mom = np.zeros(n)
    micro_mom[1:] = (close[1:] / close[:-1] - 1.0) * 100.0

    # close position in recent range (0-100)
    roll_min = np.full(n, np.nan)
    roll_max = np.full(n, np.nan)
    for i in range(20, n):
        roll_min[i] = low[i - 20:i].min()
        roll_max[i] = high[i - 20:i].max()
    rng = roll_max - roll_min
    close_pos = np.where(rng > 0, (close - roll_min) / rng * 100.0, 50.0)

    # volume features
    qv_ma = np.full(n, np.nan)
    for i in range(20, n):
        qv_ma[i] = qv[i - 20:i].mean()
    vol_change = np.where(qv_ma > 0, (qv - qv_ma) / qv_ma * 100.0, 0.0)
    taker_ratio = np.where(qv > 0, tbq / qv, 0.5)

    # 15m alignment features (resample not needed; just align by time)
    rsi15 = np.full(n, np.nan)
    emaspread15 = np.full(n, np.nan)
    mom15 = np.full(n, np.nan)
    if k15 is not None:
        c15 = k15["close"]
        e5 = ema(c15, 5)
        e12 = ema(c15, 12)
        es15 = (e5 - e12) / np.where(e12 == 0, np.nan, e12) * 100.0
        r15 = rsi(c15, 14)
        m15 = np.zeros(len(c15))
        m15[12:] = (c15[12:] / c15[:-12] - 1.0) * 100.0
        # build a 15m open_time -> index map, then forward-fill onto 5m grid
        ot15 = k15["open_time"]
        idx_map = {int(t): i for i, t in enumerate(ot15)}
        for i in range(n):
            t = int(k5["open_time"][i])
            # floor to 15m
            t15 = t - (t % (15 * 60 * 1000))
            j = idx_map.get(t15)
            if j is not None:
                rsi15[i] = r15[j]
                emaspread15[i] = es15[j]
                mom15[i] = m15[j]

    feature_names = [
        "ema_spread", "rsi", "atr_percent", "realized_vol",
        "mom_6", "mom_12", "micro_mom",
        "close_position", "vol_change", "taker_ratio",
        "rsi_15m", "ema_spread_15m", "mom_15m",
        "hour_of_day",
    ]

    X_list = []
    y_list = []
    side_list = []
    for i in range(MIN_LOOKBACK, n - FORWARD_BARS):
        if not np.isfinite(atr_p[i]) or atr_p[i] <= 0:
            continue
        # direction from primary momentum + trend (mirrors live direction logic, simplified)
        long_score = (ema_spread[i] if ema_spread[i] > 0 else 0) + (mom6[i] if mom6[i] > 0 else 0) + (mom12[i] if mom12[i] > 0 else 0)
        short_score = (-ema_spread[i] if ema_spread[i] < 0 else 0) + (-mom6[i] if mom6[i] < 0 else 0) + (-mom12[i] if mom12[i] < 0 else 0)
        if long_score - short_score >= 1.0:
            side = 1  # long
        elif short_score - long_score >= 1.0:
            side = -1  # short
        else:
            continue
        # label: entry at close[i], resolve over forward bars
        entry = close[i]
        stop_dist = atr_p[i] / 100.0 * entry * R_MULT_STOP
        target_dist = atr_p[i] / 100.0 * entry * R_MULT_TARGET
        if side == 1:
            stop = entry - stop_dist
            target = entry + target_dist
        else:
            stop = entry + stop_dist
            target = entry - target_dist
        win = 0
        for j in range(i + 1, min(i + 1 + FORWARD_BARS, n)):
            if side == 1:
                if low[j] <= stop:
                    win = 0
                    break
                if high[j] >= target:
                    win = 1
                    break
            else:
                if high[j] >= stop:
                    win = 0
                    break
                if low[j] <= target:
                    win = 1
                    break
        hour = (int(k5["open_time"][i]) // (3600 * 1000)) % 24
        feats = [
            ema_spread[i], r[i], atr_p[i], rvol[i],
            mom6[i], mom12[i], micro_mom[i],
            close_pos[i], vol_change[i], taker_ratio[i],
            rsi15[i], emaspread15[i], mom15[i],
            float(hour),
        ]
        X_list.append(feats)
        y_list.append(win)
        side_list.append(side)

    if not X_list:
        return np.empty((0, len(feature_names))), np.empty(0, dtype=int), np.empty(0, dtype=int)
    return np.array(X_list, dtype=float), np.array(y_list, dtype=int), np.array(side_list, dtype=int), feature_names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    ap.add_argument("--quantile-bins", type=int, default=0,
                    help="if >0, binarize features into this many quantile bins for chi-square")
    args = ap.parse_args()

    symbols = sorted({p.name.rsplit("_", 1)[0] for p in KLINES_DIR.glob("*_5m.csv")})
    if not symbols:
        print("no kline data found under", KLINES_DIR)
        return 1
    print(f"# {len(symbols)} symbols with 5m data")

    all_X = []
    all_y = []
    all_side = []
    all_split = []  # 0=train, 1=val
    feature_names = None
    for sym in symbols:
        p5 = KLINES_DIR / f"{sym}_5m.csv"
        p15 = KLINES_DIR / f"{sym}_15m.csv"
        if not p5.exists():
            continue
        k5 = load_csv(p5)
        k15 = load_csv(p15) if p15.exists() else None
        X, y, side, names = build_features(k5, k15)
        if feature_names is None:
            feature_names = names
        if len(X) == 0:
            continue
        # time-based split: last VAL_FRACTION rows are validation
        n = len(X)
        cut = int(n * (1 - VAL_FRACTION))
        split = np.zeros(n, dtype=int)
        split[cut:] = 1
        all_X.append(X)
        all_y.append(y)
        all_side.append(side)
        all_split.append(split)
        print(f"  {sym}: rows={n} train={cut} val={n-cut} win_rate={y.mean():.3f}")

    if not all_X:
        print("no features built")
        return 1

    X = np.vstack(all_X)
    y = np.concatenate(all_y)
    side = np.concatenate(all_side)
    split = np.concatenate(all_split)

    train_mask = split == 0
    val_mask = split == 1
    Xtr, ytr = X[train_mask], y[train_mask]
    Xva, yva = X[val_mask], y[val_mask]
    print(f"\n# total: train={len(Xtr)} (win_rate={ytr.mean():.3f}) val={len(Xva)} (win_rate={yva.mean():.3f})")

    # replace nan/inf
    Xtr = np.nan_to_num(Xtr, nan=0.0, posinf=0.0, neginf=0.0)
    Xva = np.nan_to_num(Xva, nan=0.0, posinf=0.0, neginf=0.0)

    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, precision_recall_curve

    dtr = lgb.Dataset(Xtr, label=ytr, feature_name=feature_names)
    dva = lgb.Dataset(Xva, label=yva, feature_name=feature_names, reference=dtr)

    params = {
        "objective": "binary",
        "metric": ["binary_logloss", "auc"],
        "learning_rate": 0.03,
        "num_leaves": 31,
        "min_child_samples": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 0.5,
        "verbose": -1,
    }
    model = lgb.train(params, dtr, num_boost_round=600, valid_sets=[dtr, dva],
                      callbacks=[lgb.log_evaluation(100), lgb.early_stopping(50)])

    # --- univariate significance (point-biserial correlation with win) ---
    print("\n# univariate: point-biserial corr(feature, win) on TRAIN")
    corr = {}
    for j, name in enumerate(feature_names):
        col = Xtr[:, j]
        if col.std() == 0:
            corr[name] = 0.0
            continue
        m1 = col[ytr == 1].mean()
        m0 = col[ytr == 0].mean()
        pooled = np.sqrt(0.5 * (col[ytr == 1].var() + col[ytr == 0].var()))
        corr[name] = (m1 - m0) / pooled if pooled > 0 else 0.0

    # --- LightGBM importance ---
    imp = dict(zip(feature_names, model.feature_importance(importance_type="gain").tolist()))
    imp_shap_like = dict(zip(feature_names, model.feature_importance(importance_type="split").tolist()))

    # --- validation AUC + threshold sweep ---
    proba_va = model.predict(Xva)
    auc_va = roc_auc_score(yva, proba_va) if len(np.unique(yva)) > 1 else float("nan")
    prec, rec, thr = precision_recall_curve(yva, proba_va)

    print(f"\n# validation AUC = {auc_va:.4f}")
    print(f"# base win rate (val) = {yva.mean():.4f}")
    print("\n# threshold sweep on validation (precision / recall / n_passed / lift):")
    base = yva.mean()
    sweep = []
    for t in [0.40, 0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.65]:
        pred = proba_va >= t
        n_pass = int(pred.sum())
        if n_pass == 0:
            continue
        wp = yva[pred].mean()
        sweep.append({"threshold": t, "n_passed": n_pass, "precision": round(float(wp), 4),
                      "lift_vs_base": round(float(wp / base), 4) if base > 0 else None})
        print(f"  t>={t:.2f}: passed={n_pass:6d} precision={wp:.3f} lift={wp/base:.2f}x" if base > 0 else f"  t>={t:.2f}: passed={n_pass}")

    print("\n# feature importance (gain, top):")
    for name, gain in sorted(imp.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {name:18s} gain={gain:12.1f}  split={imp_shap_like[name]:6d}  corr_win={corr[name]:+.4f}")

    report = {
        "schema": "bfa_trend_filter_research_v1",
        "n_train": int(len(Xtr)), "n_val": int(len(Xva)),
        "win_rate_train": round(float(ytr.mean()), 4),
        "win_rate_val": round(float(yva.mean()), 4),
        "val_auc": round(float(auc_va), 4),
        "feature_names": feature_names,
        "feature_corr_with_win": {k: round(v, 4) for k, v in sorted(corr.items(), key=lambda kv: -abs(kv[1]))},
        "feature_importance_gain": {k: round(v, 1) for k, v in sorted(imp.items(), key=lambda kv: -kv[1])},
        "threshold_sweep": sweep,
        "best_iteration": int(model.best_iteration),
    }
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
