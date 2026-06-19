import json
import unittest
from pathlib import Path

from bfa.market.models import NormalizedMarketSnapshot, parse_exchange_symbols


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binance_market"


class MarketModelTests(unittest.TestCase):
    def load_exchange_info(self):
        return json.loads((FIXTURE_DIR / "exchange_info.json").read_text(encoding="utf-8"))

    def test_exchange_info_fixture_parses_symbols_and_filters(self):
        symbols = parse_exchange_symbols(self.load_exchange_info())

        self.assertEqual([symbol.symbol for symbol in symbols], ["BTCUSDT", "ETHUSDT"])
        btc = symbols[0]
        self.assertEqual(btc.status, "TRADING")
        self.assertEqual(btc.contract_type, "PERPETUAL")
        self.assertEqual(btc.base_asset, "BTC")
        self.assertEqual(btc.quote_asset, "USDT")
        self.assertEqual(btc.margin_asset, "USDT")
        self.assertIn("PRICE_FILTER", btc.filters)
        self.assertIn("LOT_SIZE", btc.filters)

    def test_exchange_filters_preserve_exact_string_values(self):
        btc = parse_exchange_symbols(self.load_exchange_info())[0]

        self.assertEqual(btc.filters["PRICE_FILTER"].values["tickSize"], "0.10")
        self.assertEqual(btc.filters["LOT_SIZE"].values["stepSize"], "0.001")
        self.assertIsInstance(btc.filters["PRICE_FILTER"].values["tickSize"], str)
        self.assertEqual(btc.min_notional, "5")

    def test_normalized_market_snapshot_serializes_required_metadata(self):
        snapshot = NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="exchange_symbol",
            symbol="BTCUSDT",
            event_time=1700000000000,
            received_at="2026-06-19T10:00:00Z",
            payload={"status": "TRADING"},
        )

        self.assertEqual(
            snapshot.to_dict(),
            {
                "source": "binance_usdm",
                "event_type": "exchange_symbol",
                "symbol": "BTCUSDT",
                "event_time": 1700000000000,
                "received_at": "2026-06-19T10:00:00Z",
                "payload": {"status": "TRADING"},
            },
        )


if __name__ == "__main__":
    unittest.main()
