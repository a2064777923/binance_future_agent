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

    def test_rejects_symbols_that_cannot_fit_notional_cap(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
        packet["records"].append(
            {
                "id": 9,
                "event_type": "market_snapshot",
                "occurred_at": "2026-06-19T09:08:30Z",
                "source": "binance_usdm",
                "symbol": "BTCUSDT",
                "ref_id": "exchange_symbol:BTCUSDT",
                "payload": {
                    "event_type": "exchange_symbol",
                    "symbol": "BTCUSDT",
                    "payload": {
                        "filters": {
                            "MARKET_LOT_SIZE": {"minQty": "0.001", "stepSize": "0.001"},
                            "MIN_NOTIONAL": {"notional": "50"},
                        }
                    },
                },
            }
        )
        config = StrategyConfig(
            allowed_symbols=["BTCUSDT"],
            generated_at="2026-06-19T09:30:00Z",
            min_quote_volume=1000000,
            max_position_notional_usdt=20,
        )

        result = generate_candidates(packet, config)
        rejected = {item.symbol: item for item in result.rejected}

        self.assertEqual(result.candidates, [])
        self.assertIn("min_executable_notional_exceeds_cap", rejected["BTCUSDT"].reason_codes)
        self.assertGreater(rejected["BTCUSDT"].features["min_executable_notional"], 20)

    def test_generation_is_deterministic(self):
        packet = json.loads(FIXTURE.read_text(encoding="utf-8"))

        first = generate_candidates(packet, self.config()).to_dict()
        second = generate_candidates(packet, self.config()).to_dict()

        self.assertEqual(first, second)

    def test_spike_reversal_can_be_disabled_for_candidate_features(self):
        packet = {
            "records": [
                {
                    "id": 1,
                    "event_type": "narrative",
                    "occurred_at": "2026-06-19T09:00:00Z",
                    "source": "manual",
                    "symbol": "SOLUSDT",
                    "payload": {"symbol_mentions": ["SOLUSDT"], "engagement": {"likes": 1}},
                },
                {
                    "id": 2,
                    "event_type": "market_snapshot",
                    "occurred_at": "2026-06-19T09:01:00Z",
                    "symbol": "SOLUSDT",
                    "ref_id": "ticker_24h:SOLUSDT",
                    "payload": {
                        "event_type": "ticker_24h",
                        "symbol": "SOLUSDT",
                        "payload": {"price_change_percent": "4", "quote_volume": "5000000"},
                    },
                },
                {
                    "id": 3,
                    "event_type": "market_snapshot",
                    "occurred_at": "2026-06-19T09:02:00Z",
                    "symbol": "SOLUSDT",
                    "ref_id": "kline:SOLUSDT:1",
                    "payload": {
                        "event_type": "kline",
                        "symbol": "SOLUSDT",
                        "payload": {"open": "100", "high": "104", "low": "99.8", "close": "100.2"},
                    },
                },
            ]
        }
        config = StrategyConfig(
            allowed_symbols=["SOLUSDT"],
            generated_at="2026-06-19T09:30:00Z",
            min_quote_volume=1000000,
            spike_reversal_enabled=False,
        )

        result = generate_candidates(packet, config)

        self.assertEqual(result.candidates[0].features["spike_reversal_signal"], None)


if __name__ == "__main__":
    unittest.main()
