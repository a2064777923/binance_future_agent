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
