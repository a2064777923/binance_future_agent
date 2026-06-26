"""LDC offline training + lift-sweep validation.

Reads 5m klines under data/research/klines/ (same data train_trend_filter.py
uses), builds a 5-feature reference dataset labeled by future price direction
with a volatility-adaptive dead zone, fits a scaler, emits a persisted
artifact to data/research/ldc/, and runs a lift sweep over a time-held-out
validation segment. The release gate (lift > 1.0 with a min-passed floor)
decides whether LDC may be wired live.

No live env, DB, or service is touched. Pure local research.

Usage:
    python scripts/research/train_ldc_classifier.py
    python scripts/research/train_ldc_classifier.py --report results/research/ldc_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
KLINES_DIR = ROOT / "data" / "research" / "klines"
OUT_DIR = ROOT / "data" / "research" / "ldc"
REPORT_DIR = ROOT / "results" / "research"

FEATURE_NAMES = ("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6")
ATR_PERIOD = 14
DEFAULT_HORIZON = 36
DEFAULT_DEAD_ZONE_ATR_MULT = 0.3
DEFAULT_K = 8
DEFAULT_MIN_LOOKBACK = 30
VAL_FRACTION = 0.25


# Reuse the dependency-free indicators from train_trend_filter.py to stay DRY.
def _import_indicators():
    from scripts.research.train_trend_filter import ema, rsi, atr_percent, load_csv
    return ema, rsi, atr_percent, load_csv


def build_reference(
    klines_dir: Path,
    *,
    horizon: int = DEFAULT_HORIZON,
    dead_zone_atr_mult: float = DEFAULT_DEAD_ZONE_ATR_MULT,
    min_lookback: int = DEFAULT_MIN_LOOKBACK,
) -> dict[str, Any]:
    """Build the (X, y, split, symbols) reference dataset across all symbols."""
    ema, rsi, atr_percent, load_csv = _import_indicators()
    symbols = sorted({p.name.rsplit("_", 1)[0] for p in klines_dir.glob("*_5m.csv")})
    X_parts, y_parts, split_parts, symbol_parts = [], [], [], []
    for sym in symbols:
        p = klines_dir / f"{sym}_5m.csv"
        if not p.exists():
            continue
        k = load_csv(p)
        close, high, low = k["close"], k["high"], k["low"]
        qv, tbq = k["qv"], k["tbq"]
        n = len(close)
        if n < min_lookback + horizon + 1:
            continue
        e5 = ema(close, 5)
        e12 = ema(close, 12)
        ema_spread = (e5 - e12) / np.where(e12 == 0, np.nan, e12) * 100.0
        r = rsi(close, 14)
        atr_p = atr_percent(high, low, close)
        taker_ratio = np.where(qv > 0, tbq / qv, 0.5)
        mom6 = np.zeros(n)
        mom6[6:] = (close[6:] / close[:-6] - 1.0) * 100.0
        # time split: last VAL_FRACTION of bars is validation
        cut = int(n * (1 - VAL_FRACTION))
        for i in range(min_lookback, n - horizon):
            if not np.isfinite(atr_p[i]) or atr_p[i] <= 0:
                continue
            # no-leakage: a train point whose forward window crosses into val
            # is excluded from the reference set (its label would read val data)
            split = 1 if i >= cut else 0
            if split == 0 and i + horizon >= cut:
                continue
            entry = close[i]
            future = close[i + horizon]
            ret = (future - entry) / entry
            dz = dead_zone_atr_mult * atr_p[i] / 100.0
            if ret > dz:
                y = 1
            elif ret < -dz:
                y = -1
            else:
                y = 0
            feats = [
                ema_spread[i] if np.isfinite(ema_spread[i]) else 0.0,
                r[i] if np.isfinite(r[i]) else 50.0,
                atr_p[i],
                taker_ratio[i],
                mom6[i],
            ]
            X_parts.append(feats)
            y_parts.append(y)
            split_parts.append(split)
            symbol_parts.append(sym)
    if not X_parts:
        return {"X": np.empty((0, len(FEATURE_NAMES))), "y": np.empty(0, dtype=int),
                "split": np.empty(0, dtype=int), "symbols": [],
                "feature_names": FEATURE_NAMES}
    return {
        "X": np.array(X_parts, dtype=float),
        "y": np.array(y_parts, dtype=int),
        "split": np.array(split_parts, dtype=int),
        "symbols": symbol_parts,
        "feature_names": FEATURE_NAMES,
    }


def fit_scaler(train_x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fit mean/std on train features. Zero-std dims use std=1 to avoid div-by-0."""
    mean = train_x.mean(axis=0) if len(train_x) else np.zeros(train_x.shape[1])
    std = train_x.std(axis=0) if len(train_x) else np.ones(train_x.shape[1])
    std = np.where(std == 0, 1.0, std)
    return mean, std


def make_artifact(
    ref: dict[str, Any],
    mean: np.ndarray,
    std: np.ndarray,
    *,
    k: int,
    horizon: int,
    dead_zone_atr_mult: float,
) -> "LdcArtifact":   # type: ignore[name-defined]
    from bfa.strategy.ldc_classifier import LdcArtifact

    train_mask = ref["split"] == 0
    train_x = ref["X"][train_mask]
    train_y = ref["y"][train_mask]
    train_syms = tuple(s for s, m in zip(ref.get("symbols", []), train_mask) if m)
    distinct_syms = sorted(set(train_syms))
    meta = {
        "trained_at": "offline",
        "horizon_bars": horizon,
        "dead_zone_atr_mult": dead_zone_atr_mult,
        "k": k,
        "n_reference": int(len(train_x)),
        "symbol_set": len(distinct_syms),
        "symbols": distinct_syms,
    }
    return LdcArtifact(
        reference_x=train_x,
        reference_y=train_y,
        feature_names=tuple(ref["feature_names"]),
        scaler_mean=mean,
        scaler_std=std,
        meta=meta,
        blend_modes_supported=("linear", "asymmetric"),
        reference_symbols=train_syms,
    )


def save_ldc_artifact(artifact, path):  # thin re-export for the test import path
    from bfa.strategy.ldc_classifier import save_ldc_artifact as _save
    return _save(artifact, path)


def load_ldc_artifact(path):  # thin re-export for the test import path
    from bfa.strategy.ldc_classifier import load_ldc_artifact as _load
    return _load(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--dead-zone-atr-mult", type=float, default=DEFAULT_DEAD_ZONE_ATR_MULT)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--report", default=str(REPORT_DIR / "ldc_report.json"))
    ap.add_argument("--artifact", default=str(OUT_DIR / "ldc_reference.npz"))
    args = ap.parse_args()

    ref = build_reference(
        KLINES_DIR, horizon=args.horizon, dead_zone_atr_mult=args.dead_zone_atr_mult
    )
    if len(ref["X"]) == 0:
        print("no kline data found under", KLINES_DIR)
        return 1
    train_mask = ref["split"] == 0
    val_mask = ref["split"] == 1
    train_x, train_y = ref["X"][train_mask], ref["y"][train_mask]
    val_x, val_y = ref["X"][val_mask], ref["y"][val_mask]
    print(f"# reference: train={len(train_x)} val={len(val_x)} "
          f"dead_zone_fraction_train={float((train_y == 0).mean()):.3f}")

    mean, std = fit_scaler(train_x)
    art = make_artifact(ref, mean, std, k=args.k, horizon=args.horizon,
                        dead_zone_atr_mult=args.dead_zone_atr_mult)
    from bfa.strategy.ldc_classifier import save_ldc_artifact
    save_ldc_artifact(art, args.artifact)
    print(f"wrote artifact -> {args.artifact}")

    report = run_lift_sweep(ref, mean, std, art, args)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote report -> {args.report}")
    rec = report.get("recommended_blend", {})
    print(f"# recommended: {rec}")
    if rec.get("lift", 0.0) > 1.0:
        print("# LIFT > 1.0: LDC may proceed to shadow/testnet.")
        return 0
    print("# lift <= 1.0: LDC NOT recommended for live wiring (artifact kept).")
    return 0


def run_lift_sweep(ref, mean, std, art, args) -> dict[str, Any]:
    # Lift sweep is implemented in Task 7; placeholder returns a no-lift report.
    return {
        "schema": "bfa_ldc_research_v1",
        "artifact_path": args.artifact,
        "feature_names": list(FEATURE_NAMES),
        "horizon_bars": args.horizon,
        "dead_zone_atr_mult": args.dead_zone_atr_mult,
        "k": args.k,
        "n_train_reference": int(len(ref["X"][ref["split"] == 0])),
        "n_val": int(len(ref["X"][ref["split"] == 1])),
        "blend_sweep": [],
        "cross_symbol_diagnostic": {"measured": False, "reason": "lift_sweep_not_yet_implemented"},
        "recommended_blend": {"strength": 0.06, "mode": "linear", "lift": 0.0,
                              "reason": "lift_sweep_not_yet_implemented"},
    }


if __name__ == "__main__":
    sys.exit(main())
