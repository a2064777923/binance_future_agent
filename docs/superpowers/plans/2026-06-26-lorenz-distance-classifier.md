# Lorenzian Distance Classifier (LDC) Trend-Leg Confidence Modifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an instance-based (kNN + Lorentzian distance) future-direction predictor that retunes trend-leg confidence based on agreement with the setup side, mirroring the existing LightGBM `ml_trend_filter` deployment shape.

**Architecture:** Offline-trained persisted artifact (reference dataset + scaler) → stateless inference module `ldc_classifier.py` → additive, flag-default-off wiring into `setup.py` confidence chain → diagnostics into `price_basis`. Enablement is via a `built_in_variants` entry (mirroring `quant_setup_ml_trend`), selected live by `BFA_LIVE_QUANT_SETUP_VARIANT`. An offline training script produces the artifact and a lift-sweep report; release is gated on `lift > 1.0`.

**Tech Stack:** Python, numpy (already used in `scripts/research/train_trend_filter.py`), unittest. No new heavy dependencies — kNN over D=5 is pure numpy.

**Spec:** `docs/superpowers/specs/2026-06-26-lorenz-distance-classifier-design.md`

---

## File Structure

- **Create** `src/bfa/strategy/ldc_classifier.py` — stateless inference: artifact dataclass + loader, Lorentzian distance, kNN voting, blend modes, `ldc_confidence_modifier()`. One responsibility: turn features + side into a confidence delta + diagnostics.
- **Modify** `src/bfa/strategy/setup.py` — add `ldc_*` fields to `TradeSetupProfile`, add `_ldc_confidence_modifier()` helper + lazy-load cache, wire one block into `build_trade_setup` after the confidence recompute, inject diagnostics into `price_basis`.
- **Modify** `src/bfa/backtest/models.py` — add `quant_setup_ldc` variant to `built_in_variants`.
- **Create** `scripts/research/train_ldc_classifier.py` — offline training + lift-sweep validation, emits artifact + report.
- **Create** `tests/test_strategy_ldc_classifier.py` — inference-layer unit tests.
- **Create** `tests/test_strategy_setup_ldc.py` — wiring unit tests.
- **Create** `tests/test_train_ldc_classifier_script.py` — training-script smoke test on synthetic data.

`data/research/ldc/*.npz` artifacts and `results/research/ldc_report.json` are build outputs (gitignored under `data/` and `results/`), **not committed**.

---

## Task 1: LDC inference core — Lorentzian distance, kNN voting, artifact

**Files:**
- Create: `src/bfa/strategy/ldc_classifier.py`
- Test: `tests/test_strategy_ldc_classifier.py`

- [ ] **Step 1: Write the failing test for Lorentzian distance**

Create `tests/test_strategy_ldc_classifier.py`:

```python
import unittest

import numpy as np

from bfa.strategy.ldc_classifier import lorentzian_distance, LdcArtifact


class LorentzianDistanceTests(unittest.TestCase):
    def test_single_dimension_log_compression(self):
        # d = ln(1 + |x - ref|); a difference of e-1 (~1.718) maps to ln(2)=0.693
        d = lorentzian_distance(np.array([0.0]), np.array([[1.0]]))
        self.assertAlmostEqual(float(d[0]), np.log(2.0), places=6)

    def test_multi_dimension_sums(self):
        # two dims, each diff 1 -> 2 * ln(2)
        d = lorentzian_distance(np.array([0.0, 0.0]), np.array([[1.0, 1.0]]))
        self.assertAlmostEqual(float(d[0]), 2.0 * np.log(2.0), places=6)

    def test_zero_difference_is_zero(self):
        d = lorentzian_distance(np.array([1.0, 2.0]), np.array([[1.0, 2.0]]))
        self.assertAlmostEqual(float(d[0]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bfa.strategy.ldc_classifier'`

- [ ] **Step 3: Write minimal `ldc_classifier.py` with distance + artifact dataclass**

Create `src/bfa/strategy/ldc_classifier.py`:

```python
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


def lorentzian_distance(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Lorentzian (log) distance from a 1-D query to each row of reference.

    ``query`` shape (D,), ``reference`` shape (N, D). Returns (N,) distances:
    d_i = sum_d ln(1 + |query_d - reference_{i,d}|).
    """
    diff = np.abs(reference - query)
    return np.sum(np.log1p(diff), axis=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: PASS (3 distance tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/strategy/ldc_classifier.py tests/test_strategy_ldc_classifier.py
git commit -m "feat(ldc): add Lorentzian distance + LdcArtifact dataclass"
```

---

## Task 2: kNN voting + agreement

**Files:**
- Modify: `src/bfa/strategy/ldc_classifier.py`
- Test: `tests/test_strategy_ldc_classifier.py`

- [ ] **Step 1: Write failing tests for kNN voting / agreement**

Append to `tests/test_strategy_ldc_classifier.py` (before the `if __name__` block):

```python
class KnnVotingTests(unittest.TestCase):
    def _artifact(self, ref_x, ref_y, feature_names=("a", "b")):
        return LdcArtifact(
            reference_x=np.array(ref_x, dtype=float),
            reference_y=np.array(ref_y, dtype=int),
            feature_names=tuple(feature_names),
            scaler_mean=np.zeros(2),
            scaler_std=np.ones(2),
            meta={},
            blend_modes_supported=("linear",),
        )

    def test_all_aligned_long_yields_full_agreement(self):
        art = self._artifact([[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]], [1, 1, 1])
        agg, voters, dead = _knn_agreement(
            np.array([0.0, 0.0]), art, k=3, side="long"
        )
        self.assertEqual(voters, 3)
        self.assertEqual(dead, 0)
        self.assertAlmostEqual(agg, 1.0, places=6)

    def test_all_opposed_short_yields_full_agreement(self):
        # short setup; neighbor label -1 (future down) is "same direction"
        art = self._artifact([[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]], [-1, -1, -1])
        agg, voters, dead = _knn_agreement(
            np.array([0.0, 0.0]), art, k=3, side="short"
        )
        self.assertAlmostEqual(agg, 1.0, places=6)

    def test_half_half_yields_zero_agreement(self):
        art = self._artifact([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
                             [1, -1, 1, -1])
        agg, voters, dead = _knn_agreement(
            np.array([0.0, 0.0]), art, k=4, side="long"
        )
        self.assertEqual(voters, 4)
        self.assertAlmostEqual(agg, 0.0, places=6)

    def test_dead_zone_neighbors_do_not_vote_but_count_as_neighbors(self):
        # nearest 3: one is dead-zone (label 0), two aligned
        art = self._artifact([[0.0, 0.0], [0.05, 0.05], [0.1, 0.1], [5.0, 5.0]],
                             [0, 1, 1, 1])
        agg, voters, dead = _knn_agreement(
            np.array([0.0, 0.0]), art, k=3, side="long"
        )
        self.assertEqual(voters, 2)
        self.assertEqual(dead, 1)
        self.assertAlmostEqual(agg, 1.0, places=6)
```

Also add the import at the top of the test file:

```python
from bfa.strategy.ldc_classifier import lorentzian_distance, LdcArtifact, _knn_agreement
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: FAIL with `ImportError: cannot import name '_knn_agreement'`

- [ ] **Step 3: Implement `_knn_agreement`**

Append to `src/bfa/strategy/ldc_classifier.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: PASS (all distance + voting tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/strategy/ldc_classifier.py tests/test_strategy_ldc_classifier.py
git commit -m "feat(ldc): add kNN voting with dead-zone non-vote semantics"
```

---

## Task 3: Artifact loader + inference function + blend modes + fail-closed

**Files:**
- Modify: `src/bfa/strategy/ldc_classifier.py`
- Test: `tests/test_strategy_ldc_classifier.py`

- [ ] **Step 1: Write failing tests for blend modes + the inference function**

Append to `tests/test_strategy_ldc_classifier.py`:

```python
import json
import tempfile
from pathlib import Path

from bfa.strategy.ldc_classifier import (
    load_ldc_artifact,
    save_ldc_artifact,
    ldc_confidence_modifier,
)


def _write_artifact(tmpdir: Path) -> Path:
    art = LdcArtifact(
        reference_x=np.array([[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]], dtype=float),
        reference_y=np.array([1, 1, 1], dtype=int),
        feature_names=("a", "b"),
        scaler_mean=np.array([0.0, 0.0]),
        scaler_std=np.array([1.0, 1.0]),
        meta={"trained_at": "2026-06-26", "horizon_bars": 36, "k": 3},
        blend_modes_supported=("linear", "asymmetric"),
    )
    path = tmpdir / "ldc.npz"
    save_ldc_artifact(art, path)
    return path


class BlendModeTests(unittest.TestCase):
    def test_linear_aligned_clipped_to_blend_strength(self):
        delta = _blend_delta(1.0, blend_strength=0.06, blend_mode="linear")
        self.assertAlmostEqual(delta, 0.06, places=8)

    def test_linear_opposed_clipped_negative(self):
        delta = _blend_delta(-1.0, blend_strength=0.06, blend_mode="linear")
        self.assertAlmostEqual(delta, -0.06, places=8)

    def test_asymmetric_penalizes_opposed_more_than_aligned(self):
        aligned = _blend_delta(1.0, blend_strength=0.06, blend_mode="asymmetric")
        opposed = _blend_delta(-1.0, blend_strength=0.06, blend_mode="asymmetric")
        self.assertAlmostEqual(aligned, 0.06, places=8)
        self.assertLess(opposed, -0.06)   # steeper penalty
        self.assertAlmostEqual(opposed, -0.06 * 1.6, places=8)


class InferenceFunctionTests(unittest.TestCase):
    def test_aligned_long_lifts_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = load_ldc_artifact(_write_artifact(Path(tmp)))
            feats = {"a": 0.0, "b": 0.0}
            delta, diag = ldc_confidence_modifier(
                feats, side="long", artifact=art,
                blend_strength=0.06, blend_mode="linear", min_voters=2,
            )
            self.assertGreater(delta, 0.0)
            self.assertEqual(diag["ldc_matching"], "aligned")
            self.assertEqual(diag["ldc_predict_direction"], "up")
            self.assertEqual(diag["ldc_voters"], 3)

    def test_opposed_long_depresses_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            # all neighbors predict down -> opposed for a long
            art = LdcArtifact(
                reference_x=np.array([[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]], dtype=float),
                reference_y=np.array([-1, -1, -1], dtype=int),
                feature_names=("a", "b"),
                scaler_mean=np.zeros(2), scaler_std=np.ones(2),
                meta={"k": 3}, blend_modes_supported=("linear",),
            )
            save_ldc_artifact(art, Path(tmp) / "x.npz")
            art = load_ldc_artifact(Path(tmp) / "x.npz")
            delta, diag = ldc_confidence_modifier(
                {"a": 0.0, "b": 0.0}, side="long", artifact=art,
                blend_strength=0.06, blend_mode="linear", min_voters=2,
            )
            self.assertLess(delta, 0.0)
            self.assertEqual(diag["ldc_matching"], "opposed")

    def test_insufficient_voters_yields_zero_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = LdcArtifact(
                reference_x=np.array([[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]], dtype=float),
                reference_y=np.array([0, 0, 0], dtype=int),   # all dead-zone
                feature_names=("a", "b"),
                scaler_mean=np.zeros(2), scaler_std=np.ones(2),
                meta={"k": 3}, blend_modes_supported=("linear",),
            )
            save_ldc_artifact(art, Path(tmp) / "x.npz")
            art = load_ldc_artifact(Path(tmp) / "x.npz")
            delta, diag = ldc_confidence_modifier(
                {"a": 0.0, "b": 0.0}, side="long", artifact=art,
                blend_strength=0.06, blend_mode="linear", min_voters=3,
            )
            self.assertAlmostEqual(delta, 0.0, places=8)
            self.assertIn("ldc_insufficient_voters", diag["ldc_reason_codes"])

    def test_missing_features_filled_with_zero_and_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = load_ldc_artifact(_write_artifact(Path(tmp)))
            delta, diag = ldc_confidence_modifier(
                {"a": None, "b": 0.0}, side="long", artifact=art,
                blend_strength=0.06, blend_mode="linear", min_voters=2,
            )
            self.assertTrue(
                any("ldc_missing_features" in r for r in diag["ldc_reason_codes"])
            )
```

Add the import for `_blend_delta`:

```python
from bfa.strategy.ldc_classifier import (
    lorentzian_distance, LdcArtifact, _knn_agreement, _blend_delta,
    load_ldc_artifact, save_ldc_artifact, ldc_confidence_modifier,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: FAIL with `ImportError: cannot import name '_blend_delta'` (and the others)

- [ ] **Step 3: Implement save/load, blend, and the inference function**

Append to `src/bfa/strategy/ldc_classifier.py`:

```python
ASymmetric_PENALTY_MULT = 1.6   # validated offline before asymmetric is enabled live


def _blend_delta(agreement: float, *, blend_strength: float, blend_mode: str) -> float:
    """Map agreement in [-1, +1] to a confidence delta, clipped to blend range."""
    if blend_mode == "asymmetric" and agreement < 0:
        delta = blend_strength * agreement * ASymmetric_PENALTY_MULT
    else:
        delta = blend_strength * agreement
    return float(max(-blend_strength, min(blend_strength, delta)))


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
    )


def load_ldc_artifact(path: str | "Path") -> LdcArtifact:
    """Load a persisted artifact. Raises on missing/corrupt file (caller wraps)."""
    from pathlib import Path

    data = np.load(Path(path), allow_pickle=True)
    meta = json.loads(str(data["meta"].item()))
    return LdcArtifact(
        reference_x=np.asarray(data["reference_x"], dtype=float),
        reference_y=np.asarray(data["reference_y"], dtype=int),
        feature_names=tuple(str(x) for x in data["feature_names"].tolist()),
        scaler_mean=np.asarray(data["scaler_mean"], dtype=float),
        scaler_std=np.asarray(data["scaler_std"], dtype=float),
        meta=meta,
        blend_modes_supported=tuple(str(x) for x in data["blend_modes_supported"].tolist()),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_strategy_ldc_classifier -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/strategy/ldc_classifier.py tests/test_strategy_ldc_classifier.py
git commit -m "feat(ldc): add artifact save/load, blend modes, inference function"
```

---

## Task 4: Wire LDC into `setup.py` — profile fields, helper, confidence chain

**Files:**
- Modify: `src/bfa/strategy/setup.py` (profile dataclass ~L215-217, helper near `_ml_trend_filter_rejection` ~L1290, wiring at ~L330, `price_basis` injection)
- Test: `tests/test_strategy_setup_ldc.py`

- [ ] **Step 1: Write failing wiring tests**

Create `tests/test_strategy_setup_ldc.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from bfa.ai.schema import RiskLimits
from bfa.strategy.setup import build_trade_setup
from bfa.strategy.ldc_classifier import save_ldc_artifact, LdcArtifact


def _aligned_artifact(path: Path) -> None:
    # neighbors predict up -> aligned with a long
    art = LdcArtifact(
        reference_x=np.array([[0.0], [0.1], [0.2]], dtype=float),
        reference_y=np.array([1, 1, 1], dtype=int),
        feature_names=("ema_spread",),
        scaler_mean=np.array([0.0]), scaler_std=np.array([1.0]),
        meta={"k": 3, "trained_at": "2026-06-26", "horizon_bars": 36},
        blend_modes_supported=("linear",),
    )
    save_ldc_artifact(art, path)


def _opposed_artifact(path: Path) -> None:
    art = LdcArtifact(
        reference_x=np.array([[0.0], [0.1], [0.2]], dtype=float),
        reference_y=np.array([-1, -1, -1], dtype=int),
        feature_names=("ema_spread",),
        scaler_mean=np.array([0.0]), scaler_std=np.array([1.0]),
        meta={"k": 3, "trained_at": "2026-06-26", "horizon_bars": 36},
        blend_modes_supported=("linear",),
    )
    save_ldc_artifact(art, path)


class LdcWiringTests(unittest.TestCase):
    def risk_limits(self):
        return RiskLimits(
            account_capital_usdt=30, max_leverage=10,
            max_position_notional_usdt=25, max_risk_per_trade_usdt=0.6,
            max_daily_loss_usdt=2, max_open_positions=2,
        )

    def candidate(self, **overrides):
        features = {
            "price_change_percent": 5.5, "quote_volume": 25_000_000,
            "open_interest_value": 15_000_000, "taker_buy_sell_ratio": 1.35,
            "taker_buy_sell_ratio_change": 0.08, "funding_rate": -0.0001,
            "kline_range_mean_percent": 1.1, "kline_range_max_percent": 2.0,
            "kline_momentum_percent": 1.8, "kline_micro_momentum_percent": 0.4,
            "kline_close_position_percent": 78, "kline_quote_volume_change_percent": 35,
            "support_price": 97.8, "resistance_price": 103.2, "vwap": 99.4,
            "atr_percent": 1.05, "ema_fast": 100.8, "ema_slow": 99.6,
            "ema_spread_percent": 1.2, "rsi": 68.0, "indicator_sample_size": 12,
            "reference_price": 100.0, "min_executable_notional": 5.0,
            "strategy_leg": "trend",
        }
        features.update(overrides)
        return {"symbol": "BTCUSDT", "score": 80,
                "reason_codes": ["narrative_heat", "price_momentum"],
                "features": features}

    def _ldc_profile(self, artifact_path: str):
        return {
            "name": "ldc_test", "min_edge": 6.0, "min_confidence": 0.0,
            "min_risk_reward": 1.0, "max_stop_distance_percent": 4.2,
            "min_indicator_sample_size": 5, "entry_order_type": "limit",
            "use_ldc_confidence_modifier": True,
            "ldc_artifact_path": artifact_path,
            "ldc_blend_strength": 0.06, "ldc_blend_mode": "linear",
            "ldc_min_voters": 2, "ldc_confidence_ceiling": 0.95,
        }

    def test_flag_off_no_ldc_diagnostics(self):
        setup = build_trade_setup(
            self.candidate(), risk_limits=self.risk_limits(),
            profile={"name": "no_ldc", "min_edge": 6.0, "min_confidence": 0.0,
                     "min_risk_reward": 1.0, "max_stop_distance_percent": 4.2,
                     "min_indicator_sample_size": 5, "entry_order_type": "limit"},
        )
        self.assertNotIn("ldc_diagnostics", setup.price_basis)

    def test_aligned_lifts_confidence_and_records_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ldc.npz"
            _aligned_artifact(p)
            setup = build_trade_setup(
                self.candidate(ema_spread_percent=0.0),
                risk_limits=self.risk_limits(), profile=self._ldc_profile(str(p)),
            )
            diag = setup.price_basis["ldc_diagnostics"]
            self.assertEqual(diag["ldc_matching"], "aligned")
            self.assertGreater(diag["ldc_confidence_delta"], 0.0)
            self.assertIn("ldc_aligned", diag["ldc_reason_codes"])

    def test_opposed_depresses_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ldc.npz"
            _opposed_artifact(p)
            setup = build_trade_setup(
                self.candidate(ema_spread_percent=0.0),
                risk_limits=self.risk_limits(), profile=self._ldc_profile(str(p)),
            )
            diag = setup.price_basis["ldc_diagnostics"]
            self.assertEqual(diag["ldc_matching"], "opposed")
            self.assertLess(diag["ldc_confidence_delta"], 0.0)

    def test_live_feature_name_mapped_to_artifact_short_name(self):
        # The helper must read ema_spread_percent (live field) and feed it to an
        # artifact keyed on the short name ema_spread. Set the live field to a
        # value that lands at the center of the aligned reference points so the
        # kNN vote is all-aligned; if mapping were broken, the value would be
        # 0-filled and the vote could differ.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ldc.npz"
            _aligned_artifact(p)
            setup = build_trade_setup(
                self.candidate(ema_spread_percent=0.1),
                risk_limits=self.risk_limits(), profile=self._ldc_profile(str(p)),
            )
            diag = setup.price_basis["ldc_diagnostics"]
            self.assertEqual(diag["ldc_matching"], "aligned")
            self.assertEqual(diag["ldc_voters"], 3)

    def test_empty_artifact_path_delta_zero_no_crash(self):
        setup = build_trade_setup(
            self.candidate(), risk_limits=self.risk_limits(),
            profile=self._ldc_profile(""),
        )
        diag = setup.price_basis["ldc_diagnostics"]
        self.assertEqual(diag["ldc_confidence_delta"], 0.0)
        self.assertTrue(any("ldc_artifact_path_missing" in r
                            for r in diag["ldc_reason_codes"]))

    def test_non_trend_leg_skips_ldc(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ldc.npz"
            _aligned_artifact(p)
            setup = build_trade_setup(
                self.candidate(strategy_leg="micro_grid"),
                risk_limits=self.risk_limits(), profile=self._ldc_profile(str(p)),
            )
            diag = setup.price_basis["ldc_diagnostics"]
            self.assertEqual(diag["ldc_confidence_delta"], 0.0)
            self.assertTrue(any("ldc_leg_not_trend" in r
                                for r in diag["ldc_reason_codes"]))

    def test_opposed_can_trigger_min_confidence_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ldc.npz"
            _opposed_artifact(p)
            prof = self._ldc_profile(str(p))
            prof["min_confidence"] = 0.95   # force the gate to bind
            setup = build_trade_setup(
                self.candidate(ema_spread_percent=0.0),
                risk_limits=self.risk_limits(), profile=prof,
            )
            self.assertEqual(setup.decision, "pass")
            self.assertIn("confidence_below_profile_min", setup.reasons)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_strategy_setup_ldc -v`
Expected: FAIL — `ldc_diagnostics` not in price_basis / `use_ldc_confidence_modifier` not a known profile field.

- [ ] **Step 3: Add `ldc_*` fields to `TradeSetupProfile`**

In `src/bfa/strategy/setup.py`, find the `ml_trend_threshold: float = 0.55` line (around L217) and add after it:

```python
    # Lorenzian Distance Classifier confidence modifier for the trend leg: when
    # enabled, a kNN-over-Lorentzian-distance model predicts the future price
    # direction from a small feature subset, and the agreement between that
    # prediction and the setup side shifts confidence symmetrically (aligned
    # lifts, opposed depresses). It does NOT short-circuit the decision like
    # the ML trend filter; it only retunes confidence, so existing
    # min_confidence gates absorb the effect. The artifact (reference dataset
    # + scaler) is built offline by scripts/research/train_ldc_classifier.py.
    # Additive and defaults off; enabled via a built_in_variants entry selected
    # by BFA_LIVE_QUANT_SETUP_VARIANT (mirrors quant_setup_ml_trend).
    use_ldc_confidence_modifier: bool = False
    ldc_artifact_path: str = ""
    ldc_blend_strength: float = 0.06
    ldc_blend_mode: str = "linear"          # "linear" | "asymmetric"
    ldc_min_voters: int = 3
    ldc_confidence_ceiling: float = 0.95
```

- [ ] **Step 4: Add the `_ldc_confidence_modifier` helper + lazy-load cache**

In `src/bfa/strategy/setup.py`, find the `_ML_TREND_MODEL_CACHE` definition (around L1290) and add after it:

```python
# Cached LDC artifact so repeated setup calls do not re-read the .npz file.
_LDC_ARTIFACT_CACHE: dict[str, Any] = {}


def _ldc_confidence_modifier(
    features: Mapping[str, Any],
    side: str,
    profile: TradeSetupProfile,
) -> tuple[float, dict[str, Any]]:
    """Run the LDC confidence modifier; return (delta, diagnostics).

    Only applies to the trend leg. Fail-closed: any failure returns delta=0
    and a reason code, never raises. The artifact is loaded lazily and cached
    by path. Diagnostics are merged into price_basis by the caller.
    """
    zero = (0.0, {"ldc_enabled": True, "ldc_reason_codes": []})
    if str(features.get("strategy_leg") or "trend").lower() != "trend":
        return 0.0, {"ldc_enabled": True, "ldc_confidence_delta": 0.0,
                     "ldc_reason_codes": ["ldc_leg_not_trend"]}
    if not profile.ldc_artifact_path:
        return 0.0, {"ldc_enabled": True, "ldc_confidence_delta": 0.0,
                     "ldc_reason_codes": ["ldc_artifact_path_missing"]}
    try:
        from bfa.strategy.ldc_classifier import ldc_confidence_modifier, load_ldc_artifact
    except Exception as exc:  # pragma: no cover - defensive
        return 0.0, {"ldc_enabled": True, "ldc_confidence_delta": 0.0,
                     "ldc_reason_codes": [f"ldc_unavailable:{exc.__class__.__name__}"]}
    artifact = _LDC_ARTIFACT_CACHE.get(profile.ldc_artifact_path)
    if artifact is None:
        try:
            artifact = load_ldc_artifact(profile.ldc_artifact_path)
            _LDC_ARTIFACT_CACHE[profile.ldc_artifact_path] = artifact
        except Exception as exc:
            return 0.0, {"ldc_enabled": True, "ldc_confidence_delta": 0.0,
                         "ldc_reason_codes": [
                             f"ldc_artifact_load_failed:{exc.__class__.__name__}"]}
    # Map live feature field names -> the artifact's short feature names, mirroring
    # how _ml_trend_filter_rejection builds its feature_snapshot. The inference
    # module reads by artifact.feature_names, so it stays field-name agnostic.
    feature_snapshot = {
        "ema_spread": _float(features.get("ema_spread_percent")),
        "rsi": _float(features.get("rsi")),
        "atr_percent": _float(features.get("atr_percent")),
        "taker_ratio": _float(features.get("taker_buy_sell_ratio")),
        "mom_6": _float(features.get("kline_momentum_percent")),
    }
    try:
        return ldc_confidence_modifier(
            feature_snapshot, side=side, artifact=artifact,
            blend_strength=profile.ldc_blend_strength,
            blend_mode=profile.ldc_blend_mode,
            min_voters=profile.ldc_min_voters,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return 0.0, {"ldc_enabled": True, "ldc_confidence_delta": 0.0,
                     "ldc_reason_codes": [f"ldc_unavailable:{exc.__class__.__name__}"]}
```

- [ ] **Step 5: Wire the modifier into `build_trade_setup` + inject diagnostics into `price_basis`**

In `src/bfa/strategy/setup.py`, find the confidence recompute line:

```python
    confidence = _confidence(edge, factor_scores)
    if edge < setup_profile.min_edge:
```

Replace it with:

```python
    confidence = _confidence(edge, factor_scores)
    # LDC confidence modifier retunes confidence from a Lorentzian kNN direction
    # prediction. Additive and fail-closed: any failure leaves confidence
    # untouched. Only the trend leg. Diagnostics are merged into price_basis.
    if setup_profile.use_ldc_confidence_modifier:
        ldc_delta, ldc_diag = _ldc_confidence_modifier(features, side, setup_profile)
        confidence = min(
            max(confidence + ldc_delta, 0.0),
            setup_profile.ldc_confidence_ceiling,
        )
        price_basis["ldc_diagnostics"] = ldc_diag
        reasons = _dedupe([*reasons, *ldc_diag.get("ldc_reason_codes", [])])
    if edge < setup_profile.min_edge:
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m unittest tests.test_strategy_setup_ldc -v`
Expected: PASS (all 6 wiring tests)

- [ ] **Step 7: Run the full existing setup suite to confirm zero regression**

Run: `python -m unittest tests.test_strategy_setup -v`
Expected: PASS (no existing test broke)

- [ ] **Step 8: Commit**

```bash
git add src/bfa/strategy/setup.py tests/test_strategy_setup_ldc.py
git commit -m "feat(ldc): wire confidence modifier into trend-leg setup chain"
```

---

## Task 5: Add `quant_setup_ldc` variant

**Files:**
- Modify: `src/bfa/backtest/models.py` (after the `quant_setup_ml_trend` variant ~L708)
- Test: `tests/test_strategy_setup_ldc.py`

- [ ] **Step 1: Write failing test that the variant exists and enables LDC**

Append to `tests/test_strategy_setup_ldc.py`:

```python
class LdcVariantTests(unittest.TestCase):
    def test_quant_setup_ldc_variant_enables_ldc(self):
        from bfa.backtest.models import built_in_variants
        variants = built_in_variants()
        self.assertIn("quant_setup_ldc", variants)
        profile = variants["quant_setup_ldc"].setup_profile
        self.assertTrue(profile.get("use_ldc_confidence_modifier"))
        self.assertEqual(profile.get("ldc_blend_mode"), "linear")
        self.assertIn("ldc_artifact_path", profile)

    def test_existing_variants_do_not_enable_ldc(self):
        from bfa.backtest.models import built_in_variants
        variants = built_in_variants()
        for name, v in variants.items():
            if name == "quant_setup_ldc":
                continue
            self.assertFalse(
                v.setup_profile.get("use_ldc_confidence_modifier", False),
                f"{name} should not enable LDC",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_strategy_setup_ldc.LdcVariantTests -v`
Expected: FAIL — `quant_setup_ldc` not in variants.

- [ ] **Step 3: Add the variant**

In `src/bfa/backtest/models.py`, find the end of the `quant_setup_ml_trend` variant block (the `),` that closes its `with_overrides(... setup_profile={...})`, around L708) and add immediately after it:

```python
        "quant_setup_ldc": base.with_overrides(
            name="quant_setup_ldc",
            strategy_type="quant_setup",
            account_capital_usdt=100.0,
            max_leverage=30.0,
            max_position_notional_usdt=600.0,
            max_risk_per_trade_usdt=4.0,
            max_daily_loss_usdt=10.0,
            max_open_positions=5,
            lookback_bars=6,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=1,
            max_hold_bars=144,
            trailing_stop_enabled=True,
            trailing_activate_r=1.0,
            trailing_lock_r=0.25,
            trailing_giveback_r=0.65,
            setup_profile={
                "name": "ldc",
                # LDC confidence modifier (flag default off in the dataclass;
                # this variant turns it on). Artifact path points at the
                # offline-built reference dataset. Enable live by setting
                # BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_ldc ONLY after the
                # offline report shows lift > 1.0 (see train_ldc_classifier.py).
                "use_ldc_confidence_modifier": True,
                "ldc_artifact_path": "data/research/ldc/ldc_reference.npz",
                "ldc_blend_strength": 0.06,
                "ldc_blend_mode": "linear",
                "ldc_min_voters": 3,
                "ldc_confidence_ceiling": 0.95,
                # keep the geometry repair from Phase 71
                "min_edge": 6.0,
                "min_confidence": 0.0,
                "min_risk_reward": 1.5,
                "max_stop_distance_percent": 2.6,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": False,
                "require_rsi_not_extreme": False,
                "min_quote_volume_usdt": 5_000_000.0,
                "min_abs_momentum_percent": 0.08,
                "max_notional_fraction": 0.86,
                "stop_distance_multiplier": 0.82,
                "target_distance_multiplier": 1.8,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.12,
                "limit_entry_min_offset_percent": 0.02,
                "limit_entry_max_offset_percent": 0.42,
                "limit_entry_max_wait_seconds": 75,
                "min_post_cost_edge_ratio": 1.2,
                "fee_bps": 2.0,
                "slippage_bps": 2.0,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.0,
                "adaptive_stop_realized_volatility_multiplier": 1.35,
                "adaptive_target_volatility_multiplier": 1.7,
                "time_exit_only_when_not_profitable": True,
                "time_exit_use_config_max_hold_only": True,
                "regime_router_enforced": True,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_strategy_setup_ldc.LdcVariantTests -v`
Expected: PASS (2 variant tests)

- [ ] **Step 5: Run deploy-asset test (it checks variants) to confirm no breakage**

Run: `python -m unittest tests.test_deploy_assets -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bfa/backtest/models.py tests/test_strategy_setup_ldc.py
git commit -m "feat(ldc): add quant_setup_ldc variant mirroring quant_setup_ml_trend"
```

---

## Task 6: Offline training script — feature build + artifact emission

**Files:**
- Create: `scripts/research/train_ldc_classifier.py`
- Test: `tests/test_train_ldc_classifier_script.py`

- [ ] **Step 1: Write failing smoke test for feature build + artifact emission**

Create `tests/test_train_ldc_classifier_script.py`:

```python
import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np


def _write_synthetic_klines(tmpdir: Path, symbol: str = "SYN", bars: int = 80):
    p = tmpdir / f"{symbol}_5m.csv"
    rng = np.random.default_rng(0)
    base = 100.0
    closes = [base]
    for _ in range(bars):
        closes.append(closes[-1] * (1.0 + rng.normal(0, 0.004)))
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["open_time", "open", "high", "low", "close",
                    "volume", "close_time", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote"])
        t = 1_700_000_000_000
        for i, c in enumerate(closes):
            o = c * 0.999
            h = c * 1.001
            low = c * 0.999
            qv = 10_000_000.0
            tbq = qv * 0.5
            w.writerow([t + i * 300_000, o, h, low, c, 100.0,
                        t + i * 300_000 + 1, qv, 100, 50.0, tbq])
    return p


class TrainLdcScriptTests(unittest.TestCase):
    def test_build_reference_features_and_labels(self):
        from scripts.research.train_ldc_classifier import build_reference
        with tempfile.TemporaryDirectory() as tmp:
            _write_synthetic_klines(Path(tmp), bars=80)
            ref = build_reference(
                Path(tmp), horizon=12, dead_zone_atr_mult=0.3, min_lookback=30
            )
            self.assertEqual(ref["feature_names"],
                             ("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6"))
            self.assertGreater(len(ref["X"]), 0)
            self.assertEqual(ref["X"].shape[1], 5)
            self.assertEqual(len(ref["X"]), len(ref["y"]))
            # labels in {-1, 0, +1}
            self.assertTrue(set(np.unique(ref["y"])).issubset({-1, 0, 1}))

    def test_emit_artifact_roundtrip(self):
        from scripts.research.train_ldc_classifier import (
            build_reference, fit_scaler, make_artifact, save_ldc_artifact,
            load_ldc_artifact,
        )
        with tempfile.TemporaryDirectory() as tmp:
            _write_synthetic_klines(Path(tmp), bars=80)
            ref = build_reference(Path(tmp), horizon=12, dead_zone_atr_mult=0.3,
                                  min_lookback=30)
            mean, std = fit_scaler(ref["X"])
            art = make_artifact(ref, mean, std, k=4,
                                horizon=12, dead_zone_atr_mult=0.3)
            path = Path(tmp) / "ldc.npz"
            save_ldc_artifact(art, path)
            loaded = load_ldc_artifact(path)
            self.assertEqual(loaded.feature_names, ref["feature_names"])
            self.assertEqual(loaded.reference_x.shape, ref["X"].shape)
            self.assertEqual(loaded.meta["horizon_bars"], 12)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_train_ldc_classifier_script -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.research.train_ldc_classifier'`

- [ ] **Step 3: Implement feature build, scaler, artifact assembly**

Create `scripts/research/train_ldc_classifier.py`:

```python
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
import csv
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
    """Build the (X, y, split, symbol) reference dataset across all symbols."""
    ema, rsi, atr_percent, load_csv = _import_indicators()
    symbols = sorted({p.name.rsplit("_", 1)[0] for p in klines_dir.glob("*_5m.csv")})
    X_parts, y_parts, split_parts = [], [], []
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
    if not X_parts:
        return {"X": np.empty((0, len(FEATURE_NAMES))), "y": np.empty(0, dtype=int),
                "split": np.empty(0, dtype=int), "feature_names": FEATURE_NAMES}
    return {
        "X": np.array(X_parts, dtype=float),
        "y": np.array(y_parts, dtype=int),
        "split": np.array(split_parts, dtype=int),
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
    meta = {
        "trained_at": "offline",
        "horizon_bars": horizon,
        "dead_zone_atr_mult": dead_zone_atr_mult,
        "k": k,
        "n_reference": int(len(train_x)),
        "symbol_set": None,
    }
    return LdcArtifact(
        reference_x=train_x,
        reference_y=train_y,
        feature_names=tuple(ref["feature_names"]),
        scaler_mean=mean,
        scaler_std=std,
        meta=meta,
        blend_modes_supported=("linear", "asymmetric"),
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
        "recommended_blend": {"strength": 0.06, "mode": "linear", "lift": 0.0,
                              "reason": "lift_sweep_not_yet_implemented"},
    }


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_train_ldc_classifier_script -v`
Expected: PASS (2 smoke tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/research/train_ldc_classifier.py tests/test_train_ldc_classifier_script.py
git commit -m "feat(ldc): offline training script builds reference dataset + artifact"
```

---

## Task 7: Lift sweep + report + release gate

**Files:**
- Modify: `scripts/research/train_ldc_classifier.py` (`run_lift_sweep`)
- Test: `tests/test_train_ldc_classifier_script.py`

- [ ] **Step 1: Write failing test for the lift sweep logic**

Append to `tests/test_train_ldc_classifier_script.py`:

```python
class LiftSweepTests(unittest.TestCase):
    def test_lift_sweep_schema_and_recommendation(self):
        from scripts.research.train_ldc_classifier import (
            build_reference, fit_scaler, make_artifact, run_lift_sweep,
        )
        # Build a dataset where train neighbors are directionally informative:
        # mom_6 strongly predicts the forward sign, so aligned LDC should lift.
        with tempfile.TemporaryDirectory() as tmp:
            _write_synthetic_klines(Path(tmp), bars=120)
            ref = build_reference(Path(tmp), horizon=12, dead_zone_atr_mult=0.3,
                                  min_lookback=30)
            if len(ref["X"][ref["split"] == 1]) == 0:
                self.skipTest("synthetic data produced no validation rows")
            mean, std = fit_scaler(ref["X"][ref["split"] == 0])
            art = make_artifact(ref, mean, std, k=4, horizon=12,
                                dead_zone_atr_mult=0.3)
            class _Args:
                horizon = 12
                dead_zone_atr_mult = 0.3
                k = 4
                artifact = "x.npz"
                report = "x.json"
            report = run_lift_sweep(ref, mean, std, art, _Args())
            self.assertEqual(report["schema"], "bfa_ldc_research_v1")
            self.assertIn("blend_sweep", report)
            self.assertIn("recommended_blend", report)
            self.assertIn(report["recommended_blend"]["reason"],
                          {"max_lift_subject_to_min_n_passed",
                           "no_sweep_meets_min_passed"})

    def test_release_gate_no_lift_returns_zero_exit(self):
        # When validation is empty, recommended lift stays <= 1.0.
        from scripts.research.train_ldc_classifier import run_lift_sweep
        ref = {"X": np.empty((0, 5)), "y": np.empty(0, dtype=int),
               "split": np.empty(0, dtype=int), "feature_names":
               ("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6")}
        from bfa.strategy.ldc_classifier import LdcArtifact
        art = LdcArtifact(
            reference_x=np.empty((0, 5)), reference_y=np.empty(0, dtype=int),
            feature_names=("ema_spread", "rsi", "atr_percent", "taker_ratio", "mom_6"),
            scaler_mean=np.zeros(5), scaler_std=np.ones(5),
            meta={"k": 8}, blend_modes_supported=("linear",),
        )
        class _Args:
            horizon = 36; dead_zone_atr_mult = 0.3; k = 8
            artifact = "x"; report = "x"
        report = run_lift_sweep(ref, np.zeros(5), np.ones(5), art, _Args())
        self.assertLessEqual(report["recommended_blend"]["lift"], 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_train_ldc_classifier_script.LiftSweepTests -v`
Expected: FAIL — `recommended_blend.reason` is `"lift_sweep_not_yet_implemented"`.

- [ ] **Step 3: Implement the real lift sweep**

In `scripts/research/train_ldc_classifier.py`, replace the entire `run_lift_sweep` function with:

```python
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
            "recommended_blend": {"strength": 0.06, "mode": "linear", "lift": 0.0,
                                  "reason": "no_sweep_meets_min_passed"},
        }

    # Precompute each val point's agreement + proxy side once.
    agreements = np.zeros(len(val_x))
    proxy_sides = []
    for i in range(len(val_x)):
        row = val_x[i]
        # proxy side: mom_6 sign (simplified direction hint, like train_trend_filter)
        side = "long" if row[FEATURE_NAMES.index("mom_6")] >= 0 else "short"
        proxy_sides.append(side)
        q = (row - mean) / std_safe
        d = lorentzian_distance(q, (train_x - mean) / std_safe)
        k = min(args.k, len(train_x))
        idx = np.argpartition(d, k - 1)[:k]
        labels = train_y[idx]
        same = 1 if side == "long" else -1
        voters = int(np.count_nonzero(labels != 0))
        if voters == 0:
            agreements[i] = 0.0
            continue
        same_votes = int(np.count_nonzero(labels == same))
        agreements[i] = (same_votes - (voters - same_votes)) / voters

    for strength in blend_strengths:
        for mode in blend_modes:
            for base in base_confs:
                from bfa.strategy.ldc_classifier import _blend_delta
                adjusted = np.array([
                    min(max(base + _blend_delta(agreements[i],
                                                blend_strength=strength,
                                                blend_mode=mode), 0.0), 0.95)
                    for i in range(len(val_x))
                ])
                unadj_pass = np.full(len(val_x), base) >= min_conf_gate
                adj_pass = adjusted >= min_conf_gate
                # win = the proxy side matched realized direction
                # (proxy long correct when val_y == 1; proxy short when val_y == -1)
                correct = np.array([
                    (val_y[i] == 1 and proxy_sides[i] == "long")
                    or (val_y[i] == -1 and proxy_sides[i] == "short")
                    for i in range(len(val_x))
                ])
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
    return {
        "schema": "bfa_ldc_research_v1", "artifact_path": args.artifact,
        "feature_names": list(FEATURE_NAMES), "horizon_bars": args.horizon,
        "dead_zone_atr_mult": args.dead_zone_atr_mult, "k": args.k,
        "n_train_reference": int(len(train_x)), "n_val": int(len(val_x)),
        "val_base_win_rate": round(base_win_rate, 4),
        "blend_sweep": sweep, "recommended_blend": rec,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_train_ldc_classifier_script -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/research/train_ldc_classifier.py tests/test_train_ldc_classifier_script.py
git commit -m "feat(ldc): add lift sweep, report, and lift>1.0 release gate"
```

---

## Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected: PASS — all tests, including the new `test_strategy_ldc_classifier`, `test_strategy_setup_ldc`, `test_train_ldc_classifier_script`, and the existing suites (`test_strategy_setup`, `test_deploy_assets`, etc.).

- [ ] **Step 2: Run git diff --check**

Run: `git diff --check`
Expected: no whitespace errors output, exit 0.

- [ ] **Step 3: Commit any final cleanup if needed, else report done**

If Steps 1 and 2 are clean, no commit needed. Report the verification output to the operator.

---

## Out of scope (per spec)

- No online learning / incremental reference updates (offline monthly retrain).
- No per-symbol reference sets (mixed-universe set in v1).
- No micro-grid / range leg (trend only).
- No sizing / edge adjustment (confidence only).
- No new event type / DB table (diagnostics into existing `price_basis`).
- No LDC-specific kill-switch (fail-closed is the strictest protection).
- No `BFA_LDC_*` env keys (enablement is via `BFA_LIVE_QUANT_SETUP_VARIANT` selecting `quant_setup_ldc`).
- Asymmetric blend mode is implemented but only enabled live after the offline report shows it beats linear.
