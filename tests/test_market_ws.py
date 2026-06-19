import json
import unittest
from pathlib import Path

from bfa.market.binance_ws import (
    book_ticker_stream,
    combined_stream_url,
    next_reconnect_delay,
    kline_stream,
    mark_price_stream,
    parse_market_stream_message,
    raw_stream_url,
    ticker_stream,
    validate_public_stream,
)
from bfa.market.models import NormalizedMarketSnapshot


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binance_market"


def load_events():
    return json.loads((FIXTURE_DIR / "websocket_events.json").read_text(encoding="utf-8"))


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


class WebSocketParserTests(unittest.TestCase):
    def test_combined_wrapper_parses_to_binance_snapshot(self):
        events = load_events()

        snapshot = parse_market_stream_message(events["combined_ticker"], received_at=1700000009999)

        self.assertIsInstance(snapshot, NormalizedMarketSnapshot)
        self.assertEqual(snapshot.source, "binance_usdm")
        self.assertEqual(snapshot.event_type, "ws_ticker")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.event_time, 1700000000000)
        self.assertEqual(snapshot.received_at, 1700000009999)
        self.assertEqual(snapshot.payload["stream"], "btcusdt@ticker")
        self.assertEqual(snapshot.payload["last_price"], "70100.00")

    def test_raw_public_events_parse_to_expected_event_types(self):
        events = load_events()

        cases = [
            ("raw_ticker", "ws_ticker"),
            ("raw_kline", "ws_kline"),
            ("raw_mark_price", "ws_mark_price"),
            ("raw_book_ticker", "ws_book_ticker"),
        ]

        for fixture_name, event_type in cases:
            with self.subTest(fixture_name=fixture_name):
                snapshot = parse_market_stream_message(json.dumps(events[fixture_name]), received_at="now")
                self.assertEqual(snapshot.event_type, event_type)
                self.assertEqual(snapshot.symbol, "BTCUSDT")
                self.assertEqual(snapshot.source, "binance_usdm")

        kline = parse_market_stream_message(events["raw_kline"], received_at="now")
        self.assertEqual(kline.event_time, 1700000001000)
        self.assertEqual(kline.payload["interval"], "5m")
        self.assertFalse(kline.payload["closed"])

    def test_unknown_public_payload_preserves_context(self):
        events = load_events()

        snapshot = parse_market_stream_message(
            json.dumps(events["unknown_public"]).encode("utf-8"),
            received_at="now",
        )

        self.assertEqual(snapshot.event_type, "ws_unknown")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.event_time, 1700000004000)
        self.assertEqual(snapshot.payload["event_name"], "depthUpdate")

    def test_parser_rejects_private_payloads_and_backoff_is_capped(self):
        with self.assertRaises(ValueError):
            parse_market_stream_message({"listenKey": "secret", "e": "ACCOUNT_UPDATE"}, received_at="now")

        self.assertEqual(next_reconnect_delay(0), 1.0)
        self.assertEqual(next_reconnect_delay(3, initial_delay=1.0, max_delay=5.0), 5.0)


if __name__ == "__main__":
    unittest.main()
