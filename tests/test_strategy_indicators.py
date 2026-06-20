import unittest

from bfa.strategy.indicators import KlinePoint, compute_indicator_snapshot


class StrategyIndicatorTests(unittest.TestCase):
    def test_computes_market_structure_indicators_from_kline_points(self):
        price = 100.0
        points = []
        for index in range(8):
            close = price * 1.006
            points.append(
                KlinePoint(
                    open=price,
                    high=close * 1.004,
                    low=price * 0.996,
                    close=close,
                    quote_volume=1_000_000 + index * 100_000,
                )
            )
            price = close

        snapshot = compute_indicator_snapshot(points)

        self.assertEqual(snapshot.sample_size, 8)
        self.assertIsNotNone(snapshot.atr_percent)
        self.assertIsNotNone(snapshot.vwap)
        self.assertIsNotNone(snapshot.rsi)
        self.assertIsNotNone(snapshot.ema_spread_percent)
        self.assertGreater(snapshot.resistance_price, snapshot.support_price)
        self.assertGreater(snapshot.momentum_percent, 0)


if __name__ == "__main__":
    unittest.main()
