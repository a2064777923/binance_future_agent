import unittest

import numpy as np

from bfa.strategy.ldc_classifier import (
    lorentzian_distance,
    LdcArtifact,
    _knn_agreement,
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


if __name__ == "__main__":
    unittest.main()
