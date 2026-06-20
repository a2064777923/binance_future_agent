import unittest

from bfa.ai.schema import RiskLimits
from bfa.strategy.setup import build_trade_setup


class StrategySetupTests(unittest.TestCase):
    def risk_limits(self):
        return RiskLimits(
            account_capital_usdt=30,
            max_leverage=10,
            max_position_notional_usdt=25,
            max_risk_per_trade_usdt=0.6,
            max_daily_loss_usdt=2,
            max_open_positions=2,
        )

    def candidate(self, **feature_overrides):
        features = {
            "mention_count": 2,
            "source_count": 2,
            "engagement_score": 120,
            "price_change_percent": 5.5,
            "quote_volume": 25_000_000,
            "open_interest_value": 15_000_000,
            "taker_buy_sell_ratio": 1.35,
            "taker_buy_sell_ratio_change": 0.08,
            "funding_rate": -0.0001,
            "kline_range_mean_percent": 1.1,
            "kline_range_max_percent": 2.0,
            "kline_momentum_percent": 1.8,
            "kline_micro_momentum_percent": 0.4,
            "kline_close_position_percent": 78,
            "kline_quote_volume_change_percent": 35,
            "support_price": 97.8,
            "resistance_price": 103.2,
            "vwap": 99.4,
            "atr_percent": 1.05,
            "ema_fast": 100.8,
            "ema_slow": 99.6,
            "ema_spread_percent": 1.2,
            "rsi": 68.0,
            "indicator_sample_size": 12,
            "reference_price": 100.0,
            "min_executable_notional": 5.0,
        }
        features.update(feature_overrides)
        return {
            "symbol": "BTCUSDT",
            "score": 80,
            "reason_codes": ["narrative_heat", "price_momentum"],
            "features": features,
        }

    def test_builds_deterministic_long_setup_with_factor_breakdown(self):
        setup = build_trade_setup(self.candidate(), risk_limits=self.risk_limits())

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "long")
        self.assertIsNotNone(setup.entry_price)
        self.assertIsNotNone(setup.stop_price)
        self.assertIsNotNone(setup.target_price)
        self.assertLess(setup.stop_price, setup.entry_price)
        self.assertGreater(setup.target_price, setup.entry_price)
        self.assertLessEqual(setup.notional_usdt, 25)
        self.assertGreaterEqual(setup.notional_usdt, 5)
        self.assertGreaterEqual(setup.risk_reward_ratio, 1.2)
        self.assertEqual(setup.price_basis["model"], "expected_market_entry_structure_stop_target_v1")
        self.assertEqual(setup.price_basis["stop_basis"]["anchor"], "support_price")
        self.assertIn("target_basis", setup.price_basis)
        self.assertIn("quant_long_setup", setup.reasons)
        self.assertGreaterEqual(len(setup.factor_scores), 11)
        self.assertIn("momentum", {factor.name for factor in setup.factor_scores})
        self.assertIn("taker_flow", {factor.name for factor in setup.factor_scores})
        self.assertIn("trend_structure", {factor.name for factor in setup.factor_scores})
        self.assertIn("rsi_regime", {factor.name for factor in setup.factor_scores})

    def test_builds_short_setup_when_directional_factors_flip(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=-4.0,
                taker_buy_sell_ratio=0.72,
                taker_buy_sell_ratio_change=-0.1,
                funding_rate=0.0002,
                kline_momentum_percent=-1.4,
                kline_micro_momentum_percent=-0.3,
                kline_close_position_percent=22,
                support_price=96.0,
                resistance_price=102.2,
                vwap=100.7,
                ema_fast=99.1,
                ema_slow=100.4,
                ema_spread_percent=-1.2948,
                rsi=31.0,
            ),
            risk_limits=self.risk_limits(),
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "short")
        self.assertGreater(setup.stop_price, setup.entry_price)
        self.assertLess(setup.target_price, setup.entry_price)

    def test_passes_when_factor_edge_is_too_small(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=0.1,
                taker_buy_sell_ratio=1.0,
                taker_buy_sell_ratio_change=0.0,
                funding_rate=0.0,
                kline_momentum_percent=0.05,
                kline_micro_momentum_percent=0.0,
                kline_close_position_percent=50,
                kline_quote_volume_change_percent=0,
                support_price=99.5,
                resistance_price=100.5,
                vwap=100.0,
                atr_percent=1.0,
                ema_fast=100.0,
                ema_slow=100.0,
                ema_spread_percent=0.0,
                rsi=50.0,
            ),
            risk_limits=self.risk_limits(),
        )

        self.assertEqual(setup.decision, "pass")
        self.assertEqual(setup.side, "flat")
        self.assertIn("factor_edge_too_small", setup.reasons)

    def test_profile_can_require_trend_alignment_and_indicator_coverage(self):
        setup = build_trade_setup(
            self.candidate(
                indicator_sample_size=3,
                ema_spread_percent=-0.2,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "selective",
                "min_edge": 20,
                "min_indicator_sample_size": 8,
                "require_trend_alignment": True,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertEqual(setup.side, "flat")
        self.assertIn("indicator_sample_below_profile_min", setup.reasons)
        self.assertIn("trend_not_aligned", setup.reasons)
        self.assertEqual(setup.price_basis["profile"], "selective")

    def test_profile_can_disable_side_without_changing_default(self):
        short_candidate = self.candidate(
            price_change_percent=-4.0,
            taker_buy_sell_ratio=0.72,
            taker_buy_sell_ratio_change=-0.1,
            funding_rate=0.0002,
            kline_momentum_percent=-1.4,
            kline_micro_momentum_percent=-0.3,
            kline_close_position_percent=22,
            support_price=96.0,
            resistance_price=102.2,
            vwap=100.7,
            ema_fast=99.1,
            ema_slow=100.4,
            ema_spread_percent=-1.2948,
            rsi=31.0,
        )

        default_setup = build_trade_setup(short_candidate, risk_limits=self.risk_limits())
        guarded_setup = build_trade_setup(
            short_candidate,
            risk_limits=self.risk_limits(),
            profile={"name": "guarded", "disabled_sides": ["short"]},
        )

        self.assertEqual(default_setup.decision, "trade")
        self.assertEqual(default_setup.side, "short")
        self.assertEqual(guarded_setup.decision, "pass")
        self.assertEqual(guarded_setup.side, "flat")
        self.assertIn("side_disabled_by_profile", guarded_setup.reasons)

    def test_profile_can_exclude_symbol(self):
        setup = build_trade_setup(
            self.candidate(),
            risk_limits=self.risk_limits(),
            profile={"name": "guarded", "excluded_symbols": ["BTCUSDT"]},
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("symbol_excluded_by_profile", setup.reasons)


if __name__ == "__main__":
    unittest.main()
