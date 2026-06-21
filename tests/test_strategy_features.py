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


if __name__ == "__main__":
    unittest.main()
