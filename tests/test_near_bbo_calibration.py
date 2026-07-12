import builtins
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from bfa.backtest.near_bbo_calibration import (
    CONFIG_DOMAIN_FEATURES,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    NearBboCalibrationConfig,
    NearBboCalibrator,
    fit_near_bbo_calibration,
    load_near_bbo_labels,
    load_trained_near_bbo_calibrator,
)


class NearBboCalibrationTests(unittest.TestCase):
    def test_model_inference_import_does_not_require_numpy(self):
        module_path = Path(__file__).resolve().parents[1] / "src" / "bfa" / "backtest" / "near_bbo_calibration.py"
        spec = importlib.util.spec_from_file_location("near_bbo_calibration_without_numpy", module_path)
        isolated = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        original_import = builtins.__import__

        def import_without_numpy(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("numpy intentionally unavailable", name="numpy")
            return original_import(name, *args, **kwargs)

        sys.modules[spec.name] = isolated
        try:
            with mock.patch("builtins.__import__", side_effect=import_without_numpy):
                spec.loader.exec_module(isolated)
                calibrator = isolated.NearBboCalibrator(self.model_payload())
                prediction = calibrator.predict(
                    self.domain_features(),
                    side="long",
                    lane="range_reversion",
                    regime="RANGE",
                )
        finally:
            sys.modules.pop(spec.name, None)

        self.assertAlmostEqual(prediction.expected_net_bps, 1.0)

    def test_loader_combines_native_labels_with_legacy_reconstruction(self):
        native = self.label(1, filled=False, profitable=None)
        legacy_proposal = {
            "proposal_id": "legacy-2",
            "symbol": "ETHUSDT",
            "side": "short",
            "lane": "legacy_direction",
            "regime": "UNCLASSIFIED",
            "generated_at_ms": 120_000,
            "expires_at_ms": 125_000,
            "fill_probability": 0.4,
            "win_probability": 0.7,
            "conditional_net_ev_bps": 1.5,
            "features": {"aligned_microprice": 0.2},
        }
        legacy_outcome = {
            "symbol": "ETHUSDT",
            "signal_time_ms": 120_000,
            "fill_time_ms": 122_000,
            "exit_time_ms": 128_000,
            "exit_reason": "stop_loss",
            "notional_usdt": 120.0,
            "net_pnl_usdt": -0.12,
            "mfe_bps": 1.0,
            "mae_bps": -11.0,
        }
        events = [
            {"type": "label", "label": native},
            {
                "type": "evaluation",
                "event_time_ms": 120_000,
                "admitted": [legacy_proposal],
                "summary": {"notional_usdt": 120.0},
            },
            {"type": "outcome", "outcome": legacy_outcome},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.jsonl"
            path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

            labels = load_near_bbo_labels([path])

        self.assertEqual([label["proposal_id"] for label in labels], ["p-1", "legacy-2"])
        self.assertTrue(labels[1]["filled"])
        self.assertFalse(labels[1]["profitable"])
        self.assertAlmostEqual(labels[1]["net_pnl_usdt"], -0.12)

    def test_loader_reconstructs_expired_unfilled_legacy_admission(self):
        proposal = {
            "proposal_id": "legacy-expired",
            "symbol": "SOLUSDT",
            "side": "long",
            "generated_at_ms": 10_000,
            "expires_at_ms": 15_000,
            "features": {},
        }
        events = [
            {"type": "evaluation", "event_time_ms": 10_000, "admitted": [proposal]},
            {"type": "evaluation", "event_time_ms": 20_000, "admitted": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.jsonl"
            path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

            labels = load_near_bbo_labels([path])

        self.assertEqual(len(labels), 1)
        self.assertFalse(labels[0]["filled"])
        self.assertEqual(labels[0]["exit_reason"], "quote_expired")

    def test_trained_artifact_loader_rejects_untrained_or_malformed_models(self):
        report = {
            "schema": "bfa_near_bbo_calibration_report_v1",
            "status": "trained",
            "model": self.model_payload(),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            calibrator = load_trained_near_bbo_calibrator(path)
            prediction = calibrator.predict(
                self.domain_features(),
                side="long",
                lane="range_reversion",
                regime="RANGE",
            )

            report["status"] = "insufficient_data"
            report["model"] = None
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not trained"):
                load_trained_near_bbo_calibrator(path)

            report["status"] = "trained"
            report["model"] = self.model_payload()
            report["model"]["feature_names"] = ["unexpected_feature"]
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "feature schema"):
                load_trained_near_bbo_calibrator(path)

        self.assertAlmostEqual(prediction.fill_probability, 0.5)
        self.assertAlmostEqual(prediction.win_probability, 0.5)
        self.assertAlmostEqual(prediction.expected_net_bps, 1.0)

    def test_calibrator_rejects_execution_config_outside_training_domain(self):
        calibrator = NearBboCalibrator(self.model_payload())

        with self.assertRaisesRegex(ValueError, "quote_ttl_seconds"):
            calibrator.predict(
                {"quote_ttl_seconds": 5.0},
                side="long",
                lane="range_reversion",
                regime="RANGE",
            )

    def test_training_refuses_small_or_one_sided_forward_sample(self):
        labels = [self.label(index, filled=True, profitable=False) for index in range(30)]

        result = fit_near_bbo_calibration(
            labels,
            NearBboCalibrationConfig(
                min_labels=100,
                min_fills=40,
                min_profitable_fills=10,
                min_losing_fills=10,
            ),
        )

        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["model"])
        self.assertIn("labels_below_minimum", result["reasons"])
        self.assertIn("profitable_fills_below_minimum", result["reasons"])

    def test_training_excludes_legacy_or_feature_incomplete_labels(self):
        labels = [
            self.label(0, filled=False, profitable=None),
            self.label(1, filled=True, profitable=True, net_bps=8.0),
            self.label(2, filled=True, profitable=False, net_bps=-8.0),
            self.label(3, filled=False, profitable=None),
        ]
        labels[0]["lane"] = "legacy_direction"
        labels[0]["regime"] = "UNCLASSIFIED"
        del labels[1]["features"]["quote_ttl_seconds"]

        result = fit_near_bbo_calibration(
            labels,
            NearBboCalibrationConfig(
                min_labels=4,
                min_fills=2,
                min_profitable_fills=1,
                min_losing_fills=1,
            ),
        )

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["counts"]["observed_labels"], 4)
        self.assertEqual(result["counts"]["excluded_incompatible_labels"], 2)
        self.assertEqual(result["counts"]["labels"], 2)

    def test_training_split_must_retain_proportional_outcome_sample(self):
        labels = [self.label(index, filled=False, profitable=None) for index in range(100)]
        labels[0] = self.label(0, filled=True, profitable=True, net_bps=8.0)
        labels[1] = self.label(1, filled=True, profitable=False, net_bps=-8.0)
        for index in range(75, 100):
            profitable = index % 2 == 0
            labels[index] = self.label(
                index,
                filled=True,
                profitable=profitable,
                net_bps=8.0 if profitable else -8.0,
            )

        result = fit_near_bbo_calibration(
            labels,
            NearBboCalibrationConfig(
                min_labels=100,
                min_fills=20,
                min_profitable_fills=5,
                min_losing_fills=5,
            ),
        )

        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("training_fills_below_minimum", result["reasons"])

    def test_walk_forward_training_learns_fill_profit_and_net_surfaces(self):
        labels = []
        for index in range(600):
            fill_signal = ((index * 7) % 100) / 50.0 - 1.0
            profit_signal = ((index * 13) % 100) / 50.0 - 1.0
            filled = fill_signal + (0.25 if index % 5 == 0 else -0.05) > 0.0
            profitable = filled and profit_signal > 0.0
            labels.append(
                self.label(
                    index,
                    filled=filled,
                    profitable=profitable if filled else None,
                    aligned_flow_change=fill_signal,
                    favorable_reversal_bps=profit_signal * 4.0,
                    net_bps=(10.0 if profitable else -8.0) if filled else None,
                )
            )
        split_boundary = int(len(labels) * 0.75)
        labels[split_boundary - 1]["resolved_time_ms"] = labels[split_boundary]["signal_time_ms"] + 1

        result = fit_near_bbo_calibration(
            labels,
            NearBboCalibrationConfig(
                min_labels=200,
                min_fills=100,
                min_profitable_fills=20,
                min_losing_fills=20,
                iterations=600,
                learning_rate=0.08,
            ),
        )
        calibrator = NearBboCalibrator.from_dict(result["model"])
        high = calibrator.predict(
            self.features(aligned_flow_change=0.9, favorable_reversal_bps=3.6),
            side="long",
            lane="range_reversion",
            regime="RANGE",
        )
        low = calibrator.predict(
            self.features(aligned_flow_change=-0.9, favorable_reversal_bps=-3.6),
            side="long",
            lane="range_reversion",
            regime="RANGE",
        )

        self.assertEqual(result["status"], "trained")
        self.assertEqual(result["split"]["purged_train_count"], 1)
        self.assertLess(result["split"]["train_end_ms"], result["split"]["validation_start_ms"])
        self.assertGreater(high.fill_probability, low.fill_probability)
        self.assertGreater(high.win_probability, low.win_probability)
        self.assertGreater(high.expected_net_bps, low.expected_net_bps)

    @classmethod
    def label(
        cls,
        index: int,
        *,
        filled: bool,
        profitable: bool | None,
        aligned_flow_change: float = 0.0,
        favorable_reversal_bps: float = 0.0,
        net_bps: float | None = None,
    ) -> dict:
        notional = 120.0
        return {
            "proposal_id": f"p-{index}",
            "symbol": f"S{index % 20}USDT",
            "side": "long" if index % 2 == 0 else "short",
            "lane": "range_reversion" if index % 3 else "trend_pullback",
            "regime": "RANGE" if index % 3 else "TREND",
            "signal_time_ms": index * 60_000,
            "resolved_time_ms": index * 60_000 + 5_000,
            "expires_at_ms": index * 60_000 + 5_000,
            "notional_usdt": notional,
            "filled": filled,
            "fill_time_ms": index * 60_000 + 2_000 if filled else None,
            "exit_time_ms": index * 60_000 + 5_000 if filled else None,
            "exit_reason": "take_profit" if profitable else "stop_loss" if filled else "quote_expired",
            "profitable": profitable,
            "net_pnl_usdt": net_bps * notional / 10_000.0 if net_bps is not None else None,
            "mfe_bps": 12.0 if profitable else 1.0 if filled else None,
            "mae_bps": -2.0 if profitable else -9.0 if filled else None,
            "predicted_fill_probability": 0.5,
            "predicted_win_probability": 0.5,
            "predicted_conditional_net_ev_bps": 0.0,
            "features": cls.features(
                aligned_flow_change=aligned_flow_change,
                favorable_reversal_bps=favorable_reversal_bps,
            ),
        }

    @staticmethod
    def features(*, aligned_flow_change: float, favorable_reversal_bps: float) -> dict:
        values = {name: 0.0 for name in NUMERIC_FEATURES}
        values.update({
            "aligned_microprice": 0.4,
            "aligned_flow_change": aligned_flow_change,
            "aligned_fast_flow": 0.2,
            "favorable_reversal_bps": favorable_reversal_bps,
            "volatility_bps": 3.0,
            "momentum_bps": 0.5,
            "near_bbo_regime_confidence": 0.75,
            "near_bbo_range_position": 0.1,
            "signal_persistence_ratio": 1.1,
            "scout_adverse_bps": 0.0,
        })
        return values

    @staticmethod
    def model_payload() -> dict:
        size = len(MODEL_FEATURES)
        return {
            "schema": "bfa_near_bbo_calibration_v1",
            "feature_names": list(MODEL_FEATURES),
            "means": [0.0] * size,
            "scales": [1.0] * size,
            "fill_model": {"intercept": 0.0, "coefficients": [0.0] * size},
            "win_model": {"intercept": 0.0, "coefficients": [0.0] * size},
            "net_model": {"intercept": 1.0, "coefficients": [0.0] * size},
            "input_domain": {
                name: {"minimum": 0.0, "maximum": 0.0}
                for name in CONFIG_DOMAIN_FEATURES
            },
        }

    @staticmethod
    def domain_features() -> dict:
        return {name: 0.0 for name in CONFIG_DOMAIN_FEATURES}


if __name__ == "__main__":
    unittest.main()
