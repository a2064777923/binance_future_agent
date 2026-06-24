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

    def test_market_only_candidate_can_pass_when_narrative_is_not_required(self):
        packet = {
            "records": [
                market_record(
                    1,
                    "HOTUSDT",
                    "ticker_24h",
                    {"price_change_percent": "6.5", "quote_volume": "75000000"},
                ),
                market_record(
                    2,
                    "HOTUSDT",
                    "kline",
                    {"open": "100", "high": "107", "low": "99", "close": "106", "quote_volume": "12000000"},
                ),
                market_record(
                    3,
                    "HOTUSDT",
                    "taker_buy_sell_volume",
                    {"buy_sell_ratio": "1.22"},
                ),
            ]
        }
        config = StrategyConfig(
            allowed_symbols=["HOTUSDT"],
            generated_at="2026-06-21T01:00:00Z",
            min_quote_volume=5_000_000,
            require_narrative_evidence=False,
            score_mode="market_momentum",
        )

        result = generate_candidates(packet, config)

        self.assertEqual([candidate.symbol for candidate in result.candidates], ["HOTUSDT"])
        self.assertEqual(result.candidates[0].narrative_score, 0)
        self.assertIn("short_interval_momentum", result.candidates[0].reason_codes)
        self.assertNotIn("no_narrative_evidence", [reason for item in result.rejected for reason in item.reason_codes])

    def test_market_momentum_scores_short_bias_from_sell_flow(self):
        packet = {
            "records": [
                market_record(
                    1,
                    "LONGUSDT",
                    "ticker_24h",
                    {"price_change_percent": "2.0", "quote_volume": "50000000"},
                ),
                market_record(
                    2,
                    "LONGUSDT",
                    "kline",
                    {"open": "100", "high": "102", "low": "99", "close": "101", "quote_volume": "9000000"},
                ),
                market_record(3, "LONGUSDT", "taker_buy_sell_volume", {"buy_sell_ratio": "1.05"}),
                market_record(
                    4,
                    "SHORTUSDT",
                    "ticker_24h",
                    {"price_change_percent": "-7.0", "quote_volume": "65000000"},
                ),
                market_record(
                    5,
                    "SHORTUSDT",
                    "kline",
                    {"open": "100", "high": "101", "low": "92", "close": "94", "quote_volume": "15000000"},
                ),
                market_record(6, "SHORTUSDT", "taker_buy_sell_volume", {"buy_sell_ratio": "0.78"}),
            ]
        }
        config = StrategyConfig(
            allowed_symbols=["LONGUSDT", "SHORTUSDT"],
            generated_at="2026-06-21T01:00:00Z",
            min_quote_volume=5_000_000,
            require_narrative_evidence=False,
            score_mode="market_momentum",
        )

        result = generate_candidates(packet, config)

        self.assertEqual(result.candidates[0].symbol, "SHORTUSDT")
        self.assertIn("directional_bias_short", result.candidates[0].reason_codes)
        self.assertIn("taker_sell_bias", result.candidates[0].reason_codes)


def market_record(id_, symbol, event_type, payload):
    return {
        "id": id_,
        "event_type": "market_snapshot",
        "occurred_at": "2026-06-21T01:00:00Z",
        "source": "binance_usdm",
        "symbol": symbol,
        "ref_id": f"{event_type}:{symbol}:{id_}",
        "payload": {
            "event_type": event_type,
            "symbol": symbol,
            "payload": payload,
        },
    }


if __name__ == "__main__":
    unittest.main()
