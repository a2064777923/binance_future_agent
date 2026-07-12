import unittest

from bfa.strategy.near_bbo_regime import (
    BREAKOUT,
    RANGE,
    TREND,
    WARMUP,
    NearBboRegimeConfig,
    NearBboRegimeTracker,
)


class NearBboRegimeTrackerTests(unittest.TestCase):
    def setUp(self):
        self.config = NearBboRegimeConfig(
            history_minutes=16,
            min_bars=12,
            fast_ema_span=5,
            slow_ema_span=12,
        )

    def test_requires_completed_multiminute_context(self):
        tracker = NearBboRegimeTracker(self.config)
        self.ingest_prices(tracker, [100.0] * 6)

        snapshot = tracker.snapshot(now_ms=6 * 60_000)

        self.assertEqual(snapshot.label, WARMUP)
        self.assertEqual(snapshot.bar_count, 6)

    def test_warmup_cannot_end_before_slow_ema_has_enough_bars(self):
        with self.assertRaisesRegex(ValueError, "min_bars"):
            NearBboRegimeConfig(
                history_minutes=16,
                min_bars=10,
                fast_ema_span=5,
                slow_ema_span=15,
            )

    def test_alternating_path_classifies_range_and_exposes_edge_location(self):
        tracker = NearBboRegimeTracker(self.config)
        prices = [100.0, 100.30, 99.80, 100.28, 99.82, 100.26, 99.84, 100.24, 99.86, 100.22, 99.88, 100.20]
        self.ingest_prices(tracker, prices)

        snapshot = tracker.snapshot(now_ms=12 * 60_000)

        self.assertEqual(snapshot.label, RANGE)
        self.assertIsNone(snapshot.direction)
        self.assertGreaterEqual(snapshot.edge_alternation_count, 2)
        self.assertLess(snapshot.path_efficiency, 0.35)
        self.assertGreaterEqual(snapshot.range_position, 0.0)
        self.assertLessEqual(snapshot.range_position, 1.0)

    def test_orderly_multiminute_path_classifies_directional_trend(self):
        tracker = NearBboRegimeTracker(self.config)
        self.ingest_prices(tracker, [100.0 + index * 0.15 for index in range(12)])

        snapshot = tracker.snapshot(now_ms=12 * 60_000)

        self.assertEqual(snapshot.label, TREND)
        self.assertEqual(snapshot.direction, "long")
        self.assertGreater(snapshot.path_efficiency, 0.5)
        self.assertGreater(snapshot.ema_spread_percent, 0.0)

    def test_accelerating_final_move_is_breakout_not_pullback_or_range(self):
        tracker = NearBboRegimeTracker(self.config)
        prices = [100.0, 100.04, 99.98, 100.03, 99.99, 100.02, 100.0, 100.03, 99.99, 100.02, 100.01, 101.20]
        self.ingest_prices(tracker, prices)

        snapshot = tracker.snapshot(now_ms=12 * 60_000)

        self.assertEqual(snapshot.label, BREAKOUT)
        self.assertEqual(snapshot.direction, "long")
        self.assertGreater(snapshot.breakout_strength, 1.0)

    def test_minute_storage_is_bounded(self):
        tracker = NearBboRegimeTracker(self.config)
        self.ingest_prices(tracker, [100.0 + index * 0.01 for index in range(60)])

        self.assertLessEqual(tracker.bar_count, self.config.history_minutes)

    @staticmethod
    def ingest_prices(tracker: NearBboRegimeTracker, prices: list[float]) -> None:
        for index, price in enumerate(prices):
            tracker.ingest_trade(
                event_time_ms=index * 60_000 + 59_000,
                price=price,
                quantity=1.0,
                taker_buy=index % 2 == 0,
            )


if __name__ == "__main__":
    unittest.main()
