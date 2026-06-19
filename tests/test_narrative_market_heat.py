import unittest

from bfa.market.models import NormalizedMarketSnapshot
from bfa.narrative.market_heat import MarketHeatNarrativeCollector


def snapshot(event_type, symbol, payload):
    return NormalizedMarketSnapshot(
        source="binance_usdm",
        event_type=event_type,
        symbol=symbol,
        event_time=1700000000000,
        received_at="2026-06-20T10:00:00Z",
        payload=payload,
    )


class MarketHeatNarrativeTests(unittest.TestCase):
    def collector(self, snapshots):
        return MarketHeatNarrativeCollector(
            snapshots,
            known_symbols=["BTCUSDT", "ETHUSDT"],
            collected_at="2026-06-20T10:00:00Z",
            min_quote_volume=5_000_000,
            min_price_change_percent=2.5,
            min_taker_buy_sell_ratio=1.05,
            min_open_interest_value=1_000_000,
            max_kline_range_percent=15,
            max_records=3,
        )

    def test_emits_record_for_confirmed_market_heat(self):
        records = self.collector(
            [
                snapshot("ticker_24h", "BTCUSDT", {"price_change_percent": "5.2", "quote_volume": "12000000"}),
                snapshot("kline", "BTCUSDT", {"high": "101", "low": "99", "close": "100"}),
                snapshot("taker_buy_sell_volume", "BTCUSDT", {"buy_sell_ratio": "1.2"}),
                snapshot("open_interest_hist", "BTCUSDT", {"sum_open_interest_value": "5000000"}),
                snapshot("funding_rate", "BTCUSDT", {"funding_rate": "0.0001"}),
            ]
        ).collect()

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source, "market_heat")
        self.assertEqual(record.symbol_mentions, ["BTCUSDT"])
        self.assertEqual(record.author, "binance_usdm_metrics")
        self.assertIn("market_derived", record.quality_flags)
        self.assertGreater(record.engagement["heat_score"], 0)
        self.assertIn("taker_buy_bias", record.raw["reason_codes"])

    def test_skips_weak_or_uncontrolled_market_moves(self):
        records = self.collector(
            [
                snapshot("ticker_24h", "BTCUSDT", {"price_change_percent": "1.1", "quote_volume": "12000000"}),
                snapshot("kline", "BTCUSDT", {"high": "101", "low": "99", "close": "100"}),
                snapshot("taker_buy_sell_volume", "BTCUSDT", {"buy_sell_ratio": "1.2"}),
                snapshot("ticker_24h", "ETHUSDT", {"price_change_percent": "5.1", "quote_volume": "12000000"}),
                snapshot("kline", "ETHUSDT", {"high": "130", "low": "90", "close": "100"}),
                snapshot("taker_buy_sell_volume", "ETHUSDT", {"buy_sell_ratio": "1.2"}),
            ]
        ).collect()

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
