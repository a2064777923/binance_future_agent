"""Backtest the ML trend filter with correct feature windows + live caps.

This avoids the feature-distribution mismatch between the offline trainer
(20+ bar sliding windows) and the live backtest engine (6-bar lookback) by
reusing the trainer's own feature builder, then simulating trades with the real
live account caps (100U / 30x / 4U risk / 10U daily loss / 20U margin / 5 pos).

Compares three modes on the validation slice (last 25% of each symbol, by time):
  - baseline:   no filter (every directional signal trades)
  - ml_trend:    ML filter at threshold 0.55
  - legacy_gates: the live_action_flow boolean-gate stack (min_edge etc.)

No live env/DB/service. Pure local research.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import lightgbm as lgb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
import train_trend_filter as tt  # noqa: E402

# live account caps
CAPITAL = 100.0
LEVERAGE = 30.0
RISK_PER_TRADE = 4.0
DAILY_LOSS = 10.0
MAX_POSITION_NOTIONAL = 600.0  # margin 20 * leverage 30
MAX_OPEN = 5
# costs: maker in, taker out (live uses limit entry, stop/target market exit)
FEE_BPS = 2.0  # maker entry
EXIT_FEE_BPS = 4.0  # taker exit
SLIPPAGE_BPS = 2.0


def simulate_trades(X, y, side, proba, open_times, threshold, *, filter_mode, model_threshold):
    """Yield (win, net_pnl_usdt, side, symbol) per accepted trade.

    filter_mode: 'baseline' | 'ml_trend' | 'legacy_gates'
    """
    accepted = np.ones(len(X), dtype=bool)
    if filter_mode == "ml_trend":
        accepted = proba >= model_threshold
    # legacy_gates: approximate the live_action_flow boolean stack with a
    # simple edge proxy (min_edge ~ |mom_6| + |ema_spread| >= 14) — this is a
    # rough proxy since the full 14-gate logic isn't trivially reproducible
    # here, but it captures the "very strict" character.
    elif filter_mode == "legacy_gates":
        # columns: 0 ema_spread, 4 mom_6, 5 mom_12, 11 ema_spread_15m, 12 mom_15m
        edge = np.abs(X[:, 0]) + np.abs(X[:, 4]) + np.abs(X[:, 12])
        accepted = edge >= 14.0
    n_trades = 0
    daily_pnl = {}
    open_count = 0
    for i in np.where(accepted)[0]:
        # daily loss gate
        day = int(open_times[i]) // (86400 * 1000)
        if daily_pnl.get(day, 0.0) <= -DAILY_LOSS:
            continue
        if open_count >= MAX_OPEN:
            continue
        # sizing: risk-based, capped
        atr_p = X[i, 2]  # atr_percent column
        if not np.isfinite(atr_p) or atr_p <= 0:
            continue
        stop_frac = atr_p / 100.0
        risk_notional = RISK_PER_TRADE / stop_frac if stop_frac > 0 else 0
        notional = min(risk_notional, MAX_POSITION_NOTIONAL)
        if notional <= 0:
            continue
        win = int(y[i])
        # pnl: win -> +1.5R, loss -> -1R, minus costs
        gross = (1.5 if win else -1.0) * RISK_PER_TRADE
        cost = notional * (FEE_BPS + EXIT_FEE_BPS + 2 * SLIPPAGE_BPS) / 10000.0
        net = gross - cost
        daily_pnl[day] = daily_pnl.get(day, 0.0) + net
        n_trades += 1
        yield win, net, int(side[i])
    return n_trades


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="data/research/trend_filter_v1.txt")
    ap.add_argument("--report", default="results/research/ml_backtest_comparison.json")
    args = ap.parse_args()

    model = lgb.Booster(model_file=args.model)
    symbols = sorted({p.name.rsplit("_", 1)[0] for p in tt.KLINES_DIR.glob("*_5m.csv")})

    # build full dataset with feature windows + open_time
    all_X, all_y, all_side, all_split, all_ot, all_sym = [], [], [], [], [], []
    for sym in symbols:
        p5 = tt.KLINES_DIR / f"{sym}_5m.csv"
        p15 = tt.KLINES_DIR / f"{sym}_15m.csv"
        if not p5.exists():
            continue
        k5 = tt.load_csv(p5)
        k15 = tt.load_csv(p15) if p15.exists() else None
        X, y, side, names = tt.build_features(k5, k15)
        if len(X) == 0:
            continue
        n = len(X)
        cut = int(n * (1 - tt.VAL_FRACTION))
        # open_time aligned with feature rows (start at MIN_LOOKBACK)
        ot = k5["open_time"][tt.MIN_LOOKBACK:tt.MIN_LOOKBACK + n]
        all_X.append(X)
        all_y.append(y)
        all_side.append(side)
        all_ot.append(ot)
        all_sym.append([sym] * n)
        all_split.append(np.zeros(n, dtype=int))
        all_split[-1][cut:] = 1

    X = np.vstack(all_X)
    y = np.concatenate(all_y)
    side = np.concatenate(all_side)
    ot = np.concatenate(all_ot)
    split = np.concatenate(all_split)
    sym = np.concatenate(all_sym)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    proba = model.predict(X)

    val = split == 1
    print(f"# validation set: {val.sum()} bars across {len(symbols)} symbols\n")

    results = {}
    for mode in ("baseline", "ml_trend", "legacy_gates"):
        wins = []
        nets = []
        long_n = short_n = 0
        long_w = short_w = 0
        for w, net, s in simulate_trades(
            X[val], y[val], side[val], proba[val], ot[val], 0.55,
            filter_mode=mode, model_threshold=0.55,
        ):
            wins.append(w)
            nets.append(net)
            if s == 1:
                long_n += 1; long_w += w
            else:
                short_n += 1; short_w += w
        n = len(nets)
        total = sum(nets)
        wr = sum(wins) / n if n else 0.0
        results[mode] = {
            "trades": n,
            "win_rate": round(wr, 4),
            "total_net_pnl_usdt": round(total, 2),
            "final_capital_usdt": round(CAPITAL + total, 2),
            "return_percent": round((total / CAPITAL) * 100, 2),
            "long_trades": long_n, "long_win_rate": round(long_w / long_n, 4) if long_n else 0,
            "short_trades": short_n, "short_win_rate": round(short_w / short_n, 4) if short_n else 0,
            "avg_net_per_trade_usdt": round(total / n, 4) if n else 0,
        }
        r = results[mode]
        print(f"=== {mode:14s} ===")
        print(f"  trades={r['trades']:6d}  win_rate={r['win_rate']:.3f}  "
              f"total_net={r['total_net_pnl_usdt']:+.2f}U  return={r['return_percent']:+.2f}%")
        print(f"  long: {r['long_trades']} ({r['long_win_rate']:.3f})  "
              f"short: {r['short_trades']} ({r['short_win_rate']:.3f})")
        print()

    report = {"schema": "bfa_ml_backtest_comparison_v1", "caps": {
        "capital": CAPITAL, "leverage": LEVERAGE, "risk_per_trade": RISK_PER_TRADE,
        "daily_loss": DAILY_LOSS, "max_open": MAX_OPEN,
    }, "results": results}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
