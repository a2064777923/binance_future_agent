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
            self.assertEqual(len(ref["X"]), len(ref["symbols"]))
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
            # artifact stores only the TRAIN slice, not all of ref["X"]
            train_mask = ref["split"] == 0
            self.assertEqual(loaded.reference_x.shape, ref["X"][train_mask].shape)
            self.assertEqual(loaded.meta["horizon_bars"], 12)
            self.assertEqual(len(loaded.reference_symbols), len(loaded.reference_x))


class LiftSweepTests(unittest.TestCase):
    def test_lift_sweep_schema_and_recommendation(self):
        from scripts.research.train_ldc_classifier import (
            build_reference, fit_scaler, make_artifact, run_lift_sweep,
        )
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
            self.assertIn("cross_symbol_diagnostic", report)
            self.assertIn(report["recommended_blend"]["reason"],
                          {"max_lift_subject_to_min_n_passed",
                           "no_sweep_meets_min_passed"})

    def test_release_gate_no_lift_returns_zero_exit(self):
        from scripts.research.train_ldc_classifier import run_lift_sweep
        ref = {"X": np.empty((0, 5)), "y": np.empty(0, dtype=int),
               "split": np.empty(0, dtype=int), "symbols": [],
               "feature_names":
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


if __name__ == "__main__":
    unittest.main()
