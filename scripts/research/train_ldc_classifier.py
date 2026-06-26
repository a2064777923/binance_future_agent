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
SRC_DIR = ROOT / "src"
SCRIPTS_RESEARCH_DIR = ROOT / "scripts" / "research"
for _path in (SRC_DIR, SCRIPTS_RESEARCH_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

KLINES_DIR = ROOT / "data" / "research" / "klines"
OUT_DIR = ROOT / "data" / "research" / "ldc"
REPORT_DIR = ROOT / "results" / "research"

FEATURE_NAMES = ("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6")
ATR_PERIOD = 14
DEFAULT_HORIZON = 36
DEFAULT_DEAD_ZONE_ATR_MULT = 0.3
DEFAULT_K = 8
DEFAULT_MIN_LOOKBACK = 30
DEFAULT_MAX_VAL_POINTS = 6000
VAL_FRACTION = 0.25


# Reuse the dependency-free indicators from train_trend_filter.py to stay DRY.
def _import_indicators():
    try:
        from train_trend_filter import ema, rsi, atr_percent, load_csv
        return ema, rsi, atr_percent, load_csv
    except ModuleNotFoundError:
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
    ap.add_argument(
        "--max-val-points",
        type=int,
        default=DEFAULT_MAX_VAL_POINTS,
        help="bounded, deterministic validation sample for the lift sweep",
    )
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
    """Lift sweep over the validation segment.

    For each val point, run kNN against the TRAIN reference set (train is
    entirely time-before val per symbol, so this is leak-free), assume a
    proxy setup side from the features (mirror train_trend_filter side
    logic), compute agreement, adjust a virtual base_confidence, and measure
    whether the realized direction matched. Report win-rate lift of
    adjusted-vs-unadjusted passing sets, plus net rejected/promoted. The
    release gate is lift > 1.0 with a min-passed floor.
    """
    from bfa.strategy.ldc_classifier import lorentzian_distance

    train_mask = ref["split"] == 0
    val_mask = ref["split"] == 1
    train_x, train_y = ref["X"][train_mask], ref["y"][train_mask]
    val_x, val_y = ref["X"][val_mask], ref["y"][val_mask]
    std_safe = np.where(std == 0, 1.0, std)

    # Fraction of val points that had a real direction (non-dead-zone).
    base_win_rate = float((val_y != 0).mean()) if len(val_y) else 0.0

    blend_strengths = [0.03, 0.05, 0.06, 0.08, 0.10]
    blend_modes = ["linear", "asymmetric"]
    base_confs = [0.50, 0.58, 0.66]
    min_conf_gate = 0.55
    min_passed = max(1, int(len(val_y) * 0.005))
    sweep = []

    if len(val_x) == 0 or len(train_x) == 0:
        return {
            "schema": "bfa_ldc_research_v1", "artifact_path": args.artifact,
            "feature_names": list(FEATURE_NAMES), "horizon_bars": args.horizon,
            "dead_zone_atr_mult": args.dead_zone_atr_mult, "k": args.k,
            "n_train_reference": int(len(train_x)), "n_val": int(len(val_x)),
            "val_base_win_rate": round(base_win_rate, 4),
            "blend_sweep": [],
            "cross_symbol_diagnostic": {"measured": False, "reason": "empty_val_or_train"},
            "recommended_blend": {"strength": 0.06, "mode": "linear", "lift": 0.0,
                                  "reason": "no_sweep_meets_min_passed"},
        }

    val_indices = _validation_indices(len(val_x), int(getattr(args, "max_val_points", DEFAULT_MAX_VAL_POINTS)))
    sampled_val_x = val_x[val_indices]
    sampled_val_y = val_y[val_indices]
    val_symbols_all = ref.get("symbols", [])
    val_syms_all = [s for s, m in zip(val_symbols_all, ref["split"]) if m] if len(val_symbols_all) == len(ref["split"]) else []
    sampled_val_syms = [val_syms_all[i] for i in val_indices] if len(val_syms_all) == len(val_x) else []
    train_x_std = (train_x - mean) / std_safe

    # Precompute each val point's agreement + proxy side + neighbor symbols once.
    agreements = np.zeros(len(sampled_val_x))
    proxy_sides = []
    neighbor_symbol_counts = []   # per val point: how many neighbors share its symbol
    train_symbols = ref.get("symbols", [])
    for i in range(len(sampled_val_x)):
        row = sampled_val_x[i]
        # proxy side: mom_6 sign (simplified direction hint, like train_trend_filter)
        side = "long" if row[FEATURE_NAMES.index("mom_6")] >= 0 else "short"
        proxy_sides.append(side)
        q = (row - mean) / std_safe
        d = lorentzian_distance(q, train_x_std)
        k = min(args.k, len(train_x))
        idx = np.argpartition(d, k - 1)[:k]
        labels = train_y[idx]
        same = 1 if side == "long" else -1
        voters = int(np.count_nonzero(labels != 0))
        if voters == 0:
            agreements[i] = 0.0
        else:
            same_votes = int(np.count_nonzero(labels == same))
            agreements[i] = (same_votes - (voters - same_votes)) / voters
        # cross-symbol diagnostic: of the k neighbors, how many came from the
        # SAME symbol as the val point (None if val symbol unknown / no train syms)
        if train_symbols and i < len(sampled_val_syms) and sampled_val_syms[i]:
            neigh_syms = [train_symbols[j] if j < len(train_symbols) else "" for j in idx]
            same_sym = sum(1 for s in neigh_syms if s == sampled_val_syms[i])
            neighbor_symbol_counts.append({"same_symbol": same_sym, "k": int(k)})
        else:
            neighbor_symbol_counts.append(None)

    correct = np.array([
        (sampled_val_y[i] == 1 and proxy_sides[i] == "long")
        or (sampled_val_y[i] == -1 and proxy_sides[i] == "short")
        for i in range(len(sampled_val_x))
    ])

    for strength in blend_strengths:
        for mode in blend_modes:
            for base in base_confs:
                from bfa.strategy.ldc_classifier import _blend_delta
                adjusted = np.array([
                    min(max(base + _blend_delta(agreements[i],
                                                blend_strength=strength,
                                                blend_mode=mode), 0.0), 0.95)
                    for i in range(len(sampled_val_x))
                ])
                unadj_pass = np.full(len(sampled_val_x), base) >= min_conf_gate
                adj_pass = adjusted >= min_conf_gate
                # win = the proxy side matched realized direction
                # (proxy long correct when val_y == 1; proxy short when val_y == -1)
                n_unadj = int(unadj_pass.sum())
                n_adj = int(adj_pass.sum())
                wr_unadj = float(correct[unadj_pass].mean()) if n_unadj else 0.0
                wr_adj = float(correct[adj_pass].mean()) if n_adj else 0.0
                lift = wr_adj / wr_unadj if wr_unadj > 0 else 0.0
                sweep.append({
                    "blend_strength": strength, "blend_mode": mode, "base_conf": base,
                    "n_passed_unadjusted": n_unadj,
                    "win_rate_unadjusted": round(wr_unadj, 4),
                    "n_passed_adjusted": n_adj,
                    "win_rate_adjusted": round(wr_adj, 4),
                    "lift": round(lift, 4),
                    "net_rejected": int((unadj_pass & ~adj_pass).sum()),
                    "net_promoted": int((~unadj_pass & adj_pass).sum()),
                })

    candidates = [s for s in sweep if s["n_passed_adjusted"] >= min_passed and s["lift"] > 1.0]
    if not candidates:
        rec = {"strength": 0.06, "mode": "linear", "lift": 0.0,
               "reason": "no_sweep_meets_min_passed"}
    else:
        best = max(candidates, key=lambda s: s["lift"])
        rec = {"strength": best["blend_strength"], "mode": best["blend_mode"],
               "lift": best["lift"], "reason": "max_lift_subject_to_min_n_passed"}
    # Cross-symbol neighbor diagnostic: of val points with known symbol, mean
    # fraction of neighbors from the SAME symbol. High = kNN is intra-symbol
    # (global scaler fine); low = neighbors come from other symbols' regimes
    # (per-symbol scaling may be needed). Measure before solving (YAGNI).
    measured = [c for c in neighbor_symbol_counts if c is not None]
    if measured:
        same_sym_frac = float(np.mean([c["same_symbol"] / c["k"] for c in measured]))
        cross_diag = {
            "measured": True, "n_val_points_measured": len(measured),
            "mean_same_symbol_neighbor_fraction": round(same_sym_frac, 4),
            "interpretation": (
                "high = kNN largely intra-symbol, global scaler adequate; "
                "low = neighbors span other symbols' regimes, consider per-symbol scaling"
            ),
        }
    else:
        cross_diag = {"measured": False, "reason": "no_val_symbol_metadata"}
    return {
        "schema": "bfa_ldc_research_v1", "artifact_path": args.artifact,
        "feature_names": list(FEATURE_NAMES), "horizon_bars": args.horizon,
        "dead_zone_atr_mult": args.dead_zone_atr_mult, "k": args.k,
        "n_train_reference": int(len(train_x)), "n_val": int(len(val_x)),
        "n_val_sampled_for_lift": int(len(sampled_val_x)),
        "val_base_win_rate": round(base_win_rate, 4),
        "blend_sweep": sweep, "cross_symbol_diagnostic": cross_diag,
        "recommended_blend": rec,
    }


def _validation_indices(n: int, max_points: int) -> np.ndarray:
    """Return a deterministic spread sample over validation rows."""
    if max_points <= 0 or n <= max_points:
        return np.arange(n, dtype=int)
    return np.linspace(0, n - 1, max_points, dtype=int)


if __name__ == "__main__":
    sys.exit(main())
