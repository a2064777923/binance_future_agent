import unittest

from bfa.market.binance_ws import (
    book_ticker_stream,
    combined_stream_url,
    kline_stream,
    mark_price_stream,
    raw_stream_url,
    ticker_stream,
    validate_public_stream,
)


class WebSocketStreamBuilderTests(unittest.TestCase):
    def test_public_market_stream_names_use_lowercase_symbols(self):
        self.assertEqual(ticker_stream("BTCUSDT"), "btcusdt@ticker")
        self.assertEqual(kline_stream("BTCUSDT", "5m"), "btcusdt@kline_5m")
        self.assertEqual(mark_price_stream("BTCUSDT"), "btcusdt@markPrice")
        self.assertEqual(book_ticker_stream("BTCUSDT"), "btcusdt@bookTicker")

    def test_combined_and_raw_stream_urls_use_public_stream_paths(self):
        streams = [
            ticker_stream("BTCUSDT"),
            kline_stream("ETHUSDT", "5m"),
        ]

        self.assertEqual(
            combined_stream_url("wss://fstream.binance.com", streams),
            "wss://fstream.binance.com/stream?streams=btcusdt@ticker/ethusdt@kline_5m",
        )
        self.assertEqual(
            raw_stream_url("wss://fstream.binance.com", ticker_stream("BTCUSDT")),
            "wss://fstream.binance.com/ws/btcusdt@ticker",
        )
        self.assertEqual(
            combined_stream_url("wss://fstream.binance.com/market", streams),
            "wss://fstream.binance.com/market/stream?streams=btcusdt@ticker/ethusdt@kline_5m",
        )

    def test_private_or_trading_related_streams_are_rejected(self):
        blocked_streams = [
            "listenKey",
            "btcusdt@account",
            "btcusdt@userData",
            "btcusdt@order",
            "/private/btcusdt@ticker",
        ]

        for stream in blocked_streams:
            with self.subTest(stream=stream):
                with self.assertRaises(ValueError):
                    validate_public_stream(stream)

        with self.assertRaises(ValueError):
            ticker_stream("")
        with self.assertRaises(ValueError):
            kline_stream("BTCUSDT", "")


if __name__ == "__main__":
    unittest.main()
