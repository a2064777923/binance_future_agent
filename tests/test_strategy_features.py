import json
import unittest
from pathlib import Path

from bfa.strategy.features import extract_features


FIXTURE = Path(__file__).parent / "fixtures" / "strategy" / "replay_packet.json"


class StrategyFeatureTests(unittest.TestCase):
    def test_extracts_narrative_and_market_features(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        features = extract_features(packet)

        btc = features["BTCUSDT"]

        self.assertEqual(btc.mention_count, 2)
        self.assertEqual(btc.sources, {"binance_square", "rss:news.example"})
        self.assertEqual(btc.authors, {"poster-a", "newsdesk"})
        self.assertGreater(btc.engagement_score, 0)
        self.assertEqual(btc.narrative_event_ids, [1, 2])
        self.assertEqual(btc.market_event_ids, [3, 4, 5])
        self.assertEqual(btc.price_change_percent, 6.5)
        self.assertEqual(btc.quote_volume, 5000000.0)
        self.assertEqual(btc.taker_buy_sell_ratio, 1.2)
        self.assertIsNotNone(btc.kline_range_percent)
        self.assertIsNotNone(btc.support_price)
        self.assertIsNotNone(btc.resistance_price)
        self.assertIsNotNone(btc.atr_percent)
        self.assertGreaterEqual(btc.indicator_sample_size, 1)

    def test_missing_features_add_quality_notes(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        features = extract_features(packet)

        doge = features["DOGEUSDT"]

        self.assertIn("missing_market_confirmation", doge.quality_notes)
        self.assertIn("missing_quote_volume", doge.quality_notes)

    def test_extracts_open_interest_change_percent(self):
        features = extract_features(
            {
                "records": [
                    {
                        "id": 1,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:00:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "open_interest:SOLUSDT",
                        "payload": {
                            "event_type": "open_interest",
                            "symbol": "SOLUSDT",
                            "payload": {"open_interest": "1000"},
                        },
                    },
                    {
                        "id": 2,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:01:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "open_interest:SOLUSDT",
                        "payload": {
                            "event_type": "open_interest",
                            "symbol": "SOLUSDT",
                            "payload": {"open_interest": "1125"},
                        },
                    },
                ]
            }
        )

        sol = features["SOLUSDT"]
        self.assertEqual(sol.open_interest, 1125.0)
        self.assertAlmostEqual(sol.open_interest_change_percent, 12.5)

    def test_detects_upper_wick_spike_reversal_reference(self):
        features = extract_features(
            {
                "records": [
                    {
                        "id": 1,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:00:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "kline:SOLUSDT:1",
                        "payload": {
                            "event_type": "kline",
                            "symbol": "SOLUSDT",
                            "payload": {"open": "100", "high": "101", "low": "99.5", "close": "100", "quote_volume": "1000"},
                        },
                    },
                    {
                        "id": 2,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:05:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "kline:SOLUSDT:2",
                        "payload": {
                            "event_type": "kline",
                            "symbol": "SOLUSDT",
                            "payload": {"open": "100", "high": "103.5", "low": "99.8", "close": "100.2", "quote_volume": "3000"},
                        },
                    },
                ]
            }
        )

        sol = features["SOLUSDT"]
        self.assertEqual(sol.spike_reversal_signal, "short")
        self.assertGreater(sol.spike_wick_percent, 3.0)
        self.assertGreater(sol.spike_wick_to_body_ratio, 10)
        self.assertEqual(sol.spike_reversal_entry_price, 100.2)
        self.assertGreater(sol.spike_reversal_stop_price, 103.5)
        self.assertLess(sol.spike_reversal_target_price, 100.2)

    def test_detects_lower_wick_spike_reversal_reference(self):
        features = extract_features(
            {
                "records": [
                    {
                        "id": 1,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:00:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "kline:SOLUSDT:1",
                        "payload": {
                            "event_type": "kline",
                            "symbol": "SOLUSDT",
                            "payload": {"open": "100", "high": "100.5", "low": "99", "close": "100", "quote_volume": "1000"},
                        },
                    },
                    {
                        "id": 2,
                        "event_type": "market_snapshot",
                        "occurred_at": "2026-06-19T09:05:00Z",
                        "symbol": "SOLUSDT",
                        "ref_id": "kline:SOLUSDT:2",
                        "payload": {
                            "event_type": "kline",
                            "symbol": "SOLUSDT",
                            "payload": {"open": "100", "high": "100.2", "low": "96.5", "close": "99.8", "quote_volume": "3000"},
                        },
                    },
                ]
            }
        )

        sol = features["SOLUSDT"]
        self.assertEqual(sol.spike_reversal_signal, "long")
        self.assertGreater(sol.spike_wick_percent, 3.0)
        self.assertGreater(sol.spike_wick_to_body_ratio, 10)
        self.assertEqual(sol.spike_reversal_entry_price, 99.8)
        self.assertLess(sol.spike_reversal_stop_price, 96.5)
        self.assertGreater(sol.spike_reversal_target_price, 99.8)


if __name__ == "__main__":
    unittest.main()
