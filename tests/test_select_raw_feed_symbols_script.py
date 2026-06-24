import unittest
from unittest.mock import patch

from scripts.select_raw_feed_symbols import select_symbols


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload


class FakeClient:
    def __init__(self, *, base_url):
        self.base_url = base_url

    def ticker_24hr(self):
        return FakeResponse(
            [
                {"symbol": "BTCUSDT", "quoteVolume": "100000000", "priceChangePercent": "2", "count": 1},
                {"symbol": "SYNUSDT", "quoteVolume": "90000000", "priceChangePercent": "5", "count": 1},
                {"symbol": "USDCUSDT", "quoteVolume": "999999999", "priceChangePercent": "10", "count": 1},
                {"symbol": "AAPLUSDT", "quoteVolume": "999999999", "priceChangePercent": "10", "count": 1},
            ]
        )

    def exchange_info(self):
        return FakeResponse(
            {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "contractType": "PERPETUAL",
                        "underlyingType": "COIN",
                        "underlyingSubType": ["PoW"],
                    },
                    {
                        "symbol": "SYNUSDT",
                        "contractType": "PERPETUAL",
                        "underlyingType": "COIN",
                        "underlyingSubType": ["Layer-1"],
                    },
                    {
                        "symbol": "AAPLUSDT",
                        "contractType": "PERPETUAL",
                        "underlyingType": "INDEX",
                        "underlyingSubType": ["Stock"],
                    },
                ]
            }
        )


class SelectRawFeedSymbolsScriptTests(unittest.TestCase):
    @patch("scripts.select_raw_feed_symbols.BinanceFuturesRestClient", FakeClient)
    def test_selects_hot_crypto_usdt_symbols_and_excludes_stables(self):
        symbols = select_symbols(
            base_url="https://example.test",
            top_n=2,
            min_quote_volume_usdt=10_000_000,
            min_abs_price_change_percent=0.5,
            fallback_symbols="ETHUSDT",
            crypto_only=True,
        )

        self.assertEqual(symbols, ("BTCUSDT", "SYNUSDT"))

    @patch("scripts.select_raw_feed_symbols.BinanceFuturesRestClient", FakeClient)
    def test_falls_back_when_hot_filters_return_empty(self):
        symbols = select_symbols(
            base_url="https://example.test",
            top_n=2,
            min_quote_volume_usdt=10_000_000_000,
            min_abs_price_change_percent=0.5,
            fallback_symbols="ETHUSDT,SOLUSDT",
            crypto_only=True,
        )

        self.assertEqual(symbols, ("ETHUSDT", "SOLUSDT"))


if __name__ == "__main__":
    unittest.main()
