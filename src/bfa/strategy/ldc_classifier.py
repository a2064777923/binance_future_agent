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
