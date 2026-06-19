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

    def test_missing_features_add_quality_notes(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        features = extract_features(packet)

        doge = features["DOGEUSDT"]

        self.assertIn("missing_market_confirmation", doge.quality_notes)
        self.assertIn("missing_quote_volume", doge.quality_notes)


if __name__ == "__main__":
    unittest.main()

