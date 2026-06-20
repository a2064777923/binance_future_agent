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
        self.assertIn("quant_long_setup", setup.reasons)
        self.assertGreaterEqual(len(setup.factor_scores), 8)
        self.assertIn("momentum", {factor.name for factor in setup.factor_scores})
        self.assertIn("taker_flow", {factor.name for factor in setup.factor_scores})

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
            ),
            risk_limits=self.risk_limits(),
        )

        self.assertEqual(setup.decision, "pass")
        self.assertEqual(setup.side, "flat")
        self.assertIn("factor_edge_too_small", setup.reasons)


if __name__ == "__main__":
    unittest.main()
