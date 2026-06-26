"""Lorenzian Distance Classifier (LDC) trend-leg confidence modifier.

Instance-based future-direction predictor: kNN over Lorentzian distance on a
small standardized feature subset. The agreement between the kNN vote and the
setup side retunes confidence symmetrically (aligned lifts, opposed
depresses). Stateless inference over a persisted artifact built offline by
scripts/research/train_ldc_classifier.py. No live env, DB, or service here.

This is a confidence modifier, NOT a hard gate: it never rejects a trade on
its own. Every failure path returns delta=0 + a reason code and never raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class LdcArtifact:
    """Persisted LDC reference dataset + scaler + metadata."""

    reference_x: np.ndarray        # (N, D) standardized reference features
    reference_y: np.ndarray        # (N,) labels in {-1, 0, +1}
    feature_names: tuple[str, ...]
    scaler_mean: np.ndarray        # (D,)
    scaler_std: np.ndarray         # (D,)
    meta: dict[str, Any]
    blend_modes_supported: tuple[str, ...]
    # Diagnostic-only: source symbol per reference point. The kNN vote is
    # mixed-universe; this lets the offline report measure cross-symbol
    # neighbor distribution (decides whether per-symbol scaling is needed).
    reference_symbols: tuple[str, ...] = ()


def lorentzian_distance(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Lorentzian (log) distance from a 1-D query to each row of reference.

    ``query`` shape (D,), ``reference`` shape (N, D). Returns (N,) distances:
    d_i = sum_d ln(1 + |query_d - reference_{i,d}|).
    """
    diff = np.abs(reference - query)
    return np.sum(np.log1p(diff), axis=1)


def _knn_agreement(
    query: np.ndarray,
    artifact: LdcArtifact,
    *,
    k: int,
    side: str,
) -> tuple[float, int, int]:
    """Return (agreement, voters, dead_zone_neighbors) for a standardized query.

    ``agreement`` in [-1, +1]: (same-direction votes - opposite votes) / voters.
    Dead-zone neighbors (label 0) do not vote but do occupy a k slot. If no
    neighbors vote, returns (0.0, 0, dead_zone_neighbors).
    """
    distances = lorentzian_distance(query, artifact.reference_x)
    k = min(k, len(artifact.reference_x))
    if k <= 0:
        return 0.0, 0, 0
    nearest_idx = np.argpartition(distances, k - 1)[:k]
    labels = artifact.reference_y[nearest_idx]
    same = 1 if side == "long" else -1   # label that matches the setup side
    voters = int(np.count_nonzero(labels != 0))
    if voters == 0:
        return 0.0, 0, int(np.count_nonzero(labels == 0))
    same_votes = int(np.count_nonzero(labels == same))
    opposite_votes = voters - same_votes
    agreement = (same_votes - opposite_votes) / voters
    dead = int(np.count_nonzero(labels == 0))
    return float(agreement), voters, dead


ASymmetric_PENALTY_MULT = 1.6   # validated offline before asymmetric is enabled live


def _blend_delta(agreement: float, *, blend_strength: float, blend_mode: str) -> float:
    """Map agreement in [-1, +1] to a confidence delta, clipped to the blend range.

    Aligned reward is capped at +blend_strength. The opposed penalty is capped
    at -blend_strength for "linear"; for "asymmetric" it may reach
    -blend_strength * ASYMMETRIC_PENALTY_MULT (steeper penalty), so the clip
    must be asymmetric too — otherwise the penalty collapses back to the
    linear floor and the mode is a no-op.
    """
    if blend_mode == "asymmetric" and agreement < 0:
        delta = blend_strength * agreement * ASymmetric_PENALTY_MULT
        floor = -blend_strength * ASymmetric_PENALTY_MULT
    else:
        delta = blend_strength * agreement
        floor = -blend_strength
    return float(max(floor, min(blend_strength, delta)))


def save_ldc_artifact(artifact: LdcArtifact, path: str | "Path") -> None:
    """Persist an artifact to .npz. Dicts/lists stored as JSON strings."""
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        reference_x=artifact.reference_x,
        reference_y=artifact.reference_y,
        feature_names=np.array(artifact.feature_names, dtype=object),
        scaler_mean=artifact.scaler_mean,
        scaler_std=artifact.scaler_std,
        meta=np.array(json.dumps(artifact.meta), dtype=object),
        blend_modes_supported=np.array(artifact.blend_modes_supported, dtype=object),
        reference_symbols=np.array(artifact.reference_symbols, dtype=object),
    )


def load_ldc_artifact(path: str | "Path") -> LdcArtifact:
    """Load a persisted artifact. Raises on missing/corrupt file (caller wraps)."""
    from pathlib import Path

    # Read arrays inside the context manager so the underlying file handle is
    # closed promptly; np.load returns a lazy NpzFile that otherwise keeps the
    # .npz open until GC, which leaks ResourceWarnings into the test process.
    with np.load(Path(path), allow_pickle=True) as data:
        meta = json.loads(str(data["meta"].item()))
        ref_syms = tuple() if "reference_symbols" not in data else tuple(
            str(x) for x in data["reference_symbols"].tolist()
        )
        return LdcArtifact(
            reference_x=np.asarray(data["reference_x"], dtype=float),
            reference_y=np.asarray(data["reference_y"], dtype=int),
            feature_names=tuple(str(x) for x in data["feature_names"].tolist()),
            scaler_mean=np.asarray(data["scaler_mean"], dtype=float),
            scaler_std=np.asarray(data["scaler_std"], dtype=float),
            meta=meta,
            blend_modes_supported=tuple(str(x) for x in data["blend_modes_supported"].tolist()),
            reference_symbols=ref_syms,
        )


def ldc_confidence_modifier(
    features: Mapping[str, float | None],
    *,
    side: str,
    artifact: LdcArtifact,
    blend_strength: float = 0.06,
    blend_mode: str = "linear",
    min_voters: int = 3,
    fallback_agreement: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """Return (confidence_delta, diagnostics). Never raises.

    ``confidence_delta`` is symmetric for "linear" and clipped to
    [-blend_strength, +blend_strength]. Missing features are 0-filled and
    flagged; dead-zone neighbors do not vote; below min_voters -> delta=0.
    """
    reasons: list[str] = []
    row: list[float] = []
    missing: list[str] = []
    for name in artifact.feature_names:
        val = features.get(name)
        if val is None or not isinstance(val, (int, float)):
            row.append(0.0)
            if val is None:
                missing.append(name)
        else:
            f = float(val)
            row.append(f if f == f else 0.0)   # NaN -> 0
    if missing:
        reasons.append(f"ldc_missing_features:{','.join(missing)}")

    query = np.array(row, dtype=float)
    std = np.where(artifact.scaler_std == 0, 1.0, artifact.scaler_std)
    query_std = (query - artifact.scaler_mean) / std

    k = int(artifact.meta.get("k", 8))
    agreement, voters, dead = _knn_agreement(
        query_std, artifact, k=k, side=side,
    )
    predict_dir = "up" if agreement >= 0 else "down"
    if voters < min_voters:
        delta = 0.0
        reasons.append("ldc_insufficient_voters")
        matching = "neutral"
    else:
        delta = _blend_delta(agreement, blend_strength=blend_strength, blend_mode=blend_mode)
        if agreement > 1e-9:
            matching = "aligned"
            reasons.append("ldc_aligned")
        elif agreement < -1e-9:
            matching = "opposed"
            reasons.append("ldc_opposed")
        else:
            matching = "neutral"
            reasons.append("ldc_neutral")

    diag = {
        "ldc_enabled": True,
        "ldc_agreement": round(agreement, 6),
        "ldc_predict_direction": predict_dir,
        "ldc_setup_side": side,
        "ldc_matching": matching,
        "ldc_voters": voters,
        "ldc_k": k,
        "ldc_k_total": k,
        "ldc_dead_zone_neighbors": dead,
        "ldc_confidence_delta": round(delta, 8),
        "ldc_blend_strength": blend_strength,
        "ldc_blend_mode": blend_mode,
        "ldc_artifact_meta": {
            "trained_at": artifact.meta.get("trained_at"),
            "symbol_set": artifact.meta.get("symbol_set"),
            "horizon_bars": artifact.meta.get("horizon_bars"),
            "n_reference": int(len(artifact.reference_x)),
            "feature_names": list(artifact.feature_names),
        },
        "ldc_reason_codes": reasons,
    }
    return float(delta), diag
