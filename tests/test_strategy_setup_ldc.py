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
            # before/after recorded for testnet LDC-on-vs-off comparison
            self.assertIn("ldc_confidence_before", diag)
            self.assertIn("ldc_confidence_after", diag)
            self.assertGreater(diag["ldc_confidence_after"],
                               diag["ldc_confidence_before"])

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
