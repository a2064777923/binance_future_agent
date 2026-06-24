"""ML-learned trend-leg filter (probability threshold).

Replaces the 14 ad-hoc boolean gates of quant_setup_live_action_flow with a
single LightGBM probability threshold, calibrated from 6 months of 23-symbol
data. The model output is P(win) given continuous features; a trade is allowed
only when P(win) >= threshold.

The feature set is deliberately small (14 features) and mirrors what the live
indicator layer already computes, so this can drop into setup.py with minimal
plumbing. The model is trained offline and shipped as a persisted booster; this
module provides the inference + threshold gate.

No live env, DB, or service is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

# Default threshold chosen from the validation precision-recall sweep: at
# threshold 0.55 the model passes ~954 trades over 6 months / 23 symbols
# (~2/symbol/day) with precision 58.5% and lift 1.49x over the 39.1% base.
# Lower = more trades / lower precision; higher = fewer / higher precision.
DEFAULT_THRESHOLD = 0.55

FEATURE_NAMES = [
    "ema_spread", "rsi", "atr_percent", "realized_vol",
    "mom_6", "mom_12", "micro_mom",
    "close_position", "vol_change", "taker_ratio",
    "rsi_15m", "ema_spread_15m", "mom_15m",
    "hour_of_day",
]


def ml_trend_filter_verdict(
    features: Mapping[str, float | None],
    *,
    model: Any,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[bool, float, list[str]]:
    """Return (accept, probability, reasons).

    ``model`` is a trained LightGBM booster (or any object with .predict on a
    2D array). ``features`` must contain the FEATURE_NAMES keys (None/NaN ok,
    coerced to 0). Reasons explain a rejection.
    """
    row = []
    missing = []
    for name in FEATURE_NAMES:
        val = features.get(name)
        if val is None or not isinstance(val, (int, float)):
            row.append(0.0)
            if val is None:
                missing.append(name)
        else:
            f = float(val)
            row.append(f if f == f else 0.0)  # NaN -> 0
    import numpy as np

    proba = float(model.predict(np.array([row], dtype=float))[0])
    reasons = []
    if missing:
        reasons.append(f"ml_trend_missing_features:{','.join(missing)}")
    if proba < threshold:
        reasons.append(f"ml_trend_below_threshold:{proba:.4f}/{threshold}")
        return False, proba, reasons
    reasons.append(f"ml_trend_accepted:{proba:.4f}")
    return True, proba, reasons


def load_persisted_model(path: str | Path) -> Any:
    """Load a LightGBM booster persisted with model.save_model()."""
    import lightgbm as lgb

    return lgb.Booster(model_file=str(path))


def calibrate_threshold_from_report(report_path: str | Path) -> dict:
    """Pick the threshold that maximizes precision subject to a minimum
    passed-count, so the filter stays tradeable instead of collapsing to N=1.
    """
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    sweep = report.get("threshold_sweep", [])
    # require at least ~1 trade/symbol/day over the validation window
    min_passed = max(1, int(report.get("n_val", 0) * 0.005))
    candidates = [s for s in sweep if s["n_passed"] >= min_passed]
    if not candidates:
        return {"threshold": DEFAULT_THRESHOLD, "reason": "no_sweep_meets_min_passed"}
    best = max(candidates, key=lambda s: s["precision"])
    return {
        "threshold": best["threshold"],
        "precision": best["precision"],
        "n_passed": best["n_passed"],
        "lift": best.get("lift_vs_base"),
        "val_auc": report.get("val_auc"),
        "base_win_rate": report.get("win_rate_val"),
        "reason": "max_precision_subject_to_min_passed",
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="results/research/trend_filter_report.json")
    args = ap.parse_args()
    calib = calibrate_threshold_from_report(args.report)
    print(json.dumps(calib, indent=2))
