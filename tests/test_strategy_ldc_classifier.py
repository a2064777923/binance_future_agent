import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from bfa.strategy.ldc_classifier import (
    lorentzian_distance,
    LdcArtifact,
    _knn_agreement,
    _blend_delta,
    load_ldc_artifact,
    save_ldc_artifact,
    ldc_confidence_modifier,
)


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


if __name__ == "__main__":
    unittest.main()
