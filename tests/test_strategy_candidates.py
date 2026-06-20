import json
import unittest
from pathlib import Path

from bfa.strategy.candidates import StrategyConfig, generate_candidates


FIXTURE = Path(__file__).parent / "fixtures" / "strategy" / "replay_packet.json"


class StrategyCandidateTests(unittest.TestCase):
    def config(self):
        return StrategyConfig(
            allowed_symbols=["BTCUSDT", "ETHUSDT"],
            generated_at="2026-06-19T09:30:00Z",
            min_quote_volume=1000000,
            top_n=3,
        )

    def test_strong_narrative_and_market_confirmation_ranks_first(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = generate_candidates(packet, self.config())

        self.assertEqual([candidate.symbol for candidate in result.candidates], ["BTCUSDT"])
        candidate = result.candidates[0]
        self.assertGreater(candidate.score, 0)
        self.assertIn("narrative_heat", candidate.reason_codes)
        self.assertIn("source_diversity", candidate.reason_codes)
        self.assertIn("price_momentum", candidate.reason_codes)
        self.assertEqual(candidate.source_event_ids, [1, 2])
        self.assertEqual(candidate.market_event_ids, [3, 4, 5])
        self.assertEqual(candidate.features["reference_price"], 104.0)

    def test_rejections_include_explicit_reasons(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = generate_candidates(packet, self.config())
        rejected = {item.symbol: item for item in result.rejected}

        self.assertIn("insufficient_liquidity", rejected["ETHUSDT"].reason_codes)
        self.assertIn("symbol_not_allowed", rejected["DOGEUSDT"].reason_codes)
        self.assertIn("missing_market_confirmation", rejected["DOGEUSDT"].reason_codes)

    def test_generation_is_deterministic(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))

        first = generate_candidates(packet, self.config()).to_dict()
        second = generate_candidates(packet, self.config()).to_dict()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
