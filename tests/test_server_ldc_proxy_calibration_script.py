import unittest


class ProxyCalibrationTests(unittest.TestCase):
    def test_proxy_side_from_features(self):
        from scripts.server_ldc_proxy_calibration import proxy_side_from_features
        # proxy side mirrors train_ldc_classifier: mom_6 (kline_momentum_percent) sign
        self.assertEqual(proxy_side_from_features({"kline_momentum_percent": 1.2}), "long")
        self.assertEqual(proxy_side_from_features({"kline_momentum_percent": -0.8}), "short")
        self.assertEqual(proxy_side_from_features({"kline_momentum_percent": 0.0}), "long")

    def test_agreement_report_from_setups(self):
        from scripts.server_ldc_proxy_calibration import agreement_report_from_setups
        setups = [
            {"side": "long", "candidate": {"features": {"kline_momentum_percent": 1.0}}},
            {"side": "long", "candidate": {"features": {"kline_momentum_percent": -1.0}}},  # disagree
            {"side": "short", "candidate": {"features": {"kline_momentum_percent": -2.0}}},
            {"side": "short", "candidate": {"features": {"kline_momentum_percent": 1.5}}},  # disagree
        ]
        report = agreement_report_from_setups(setups)
        self.assertEqual(report["n_setups"], 4)
        self.assertEqual(report["n_agree"], 2)
        self.assertAlmostEqual(report["agreement_fraction"], 0.5, places=4)
        self.assertIn("interpretation", report)


if __name__ == "__main__":
    unittest.main()
