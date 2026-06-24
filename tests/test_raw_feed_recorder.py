import gzip
import json
import tempfile
import unittest
from pathlib import Path

from bfa.market.raw_feed_recorder import (
    RawFeedRecorderConfig,
    RawSecondBarCache,
    append_raw_feed_line,
    normalize_symbols,
    raw_feed_line,
)


class RawFeedRecorderTests(unittest.TestCase):
    def test_config_builds_depth_and_trade_streams_for_hftbacktest_raw_feed(self):
        config = RawFeedRecorderConfig(symbols=("BTCUSDT", "ETHUSDT"), output_path=Path("runtime/raw.gz"), depth_speed_ms=100)

        self.assertEqual(
            config.streams,
            (
                "btcusdt@depth@100ms",
                "btcusdt@trade",
                "ethusdt@depth@100ms",
                "ethusdt@trade",
            ),
        )
        self.assertEqual(
            config.websocket_url,
            "wss://fstream.binance.com/stream?streams=btcusdt@depth@100ms/btcusdt@trade/ethusdt@depth@100ms/ethusdt@trade",
        )

    def test_normalize_symbols_accepts_csv_or_sequence(self):
        self.assertEqual(normalize_symbols("btcusdt, ETHUSDT "), ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(normalize_symbols([" solusdt "]), ("SOLUSDT",))

        with self.assertRaises(ValueError):
            normalize_symbols(" , ")

    def test_raw_feed_line_uses_local_timestamp_prefix_and_compact_json(self):
        line = raw_feed_line({"stream": "btcusdt@trade", "data": {"e": "trade"}}, local_timestamp_ns=123)

        self.assertEqual(line, '123 {"data":{"e":"trade"},"stream":"btcusdt@trade"}\n')

    def test_append_raw_feed_line_writes_gzip_converter_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.gz"
            append_raw_feed_line(path, {"stream": "btcusdt@trade", "data": {"e": "trade"}}, local_timestamp_ns=123)
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                line = handle.readline()

        timestamp, payload = line.split(" ", 1)
        self.assertEqual(timestamp, "123")
        self.assertEqual(json.loads(payload), {"data": {"e": "trade"}, "stream": "btcusdt@trade"})

    def test_second_bar_cache_ingests_combined_trade_and_writes_latest_window(self):
        cache = RawSecondBarCache(window_seconds=1)
        self.assertTrue(
            cache.ingest_combined_message(
                {
                    "stream": "btcusdt@trade",
                    "data": {"e": "trade", "s": "BTCUSDT", "T": 1700000000123, "p": "100", "q": "0.2", "m": False},
                }
            )
        )
        self.assertTrue(
            cache.ingest_combined_message(
                {
                    "stream": "btcusdt@trade",
                    "data": {"e": "trade", "s": "BTCUSDT", "T": 1700000000789, "p": "101", "q": "0.1", "m": True},
                }
            )
        )

        payload = cache.to_dict()
        bars = payload["symbols"]["BTCUSDT"]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["open_time"], 1700000000000)
        self.assertEqual(bars[0]["open"], 100.0)
        self.assertEqual(bars[0]["high"], 101.0)
        self.assertEqual(bars[0]["close"], 101.0)
        self.assertAlmostEqual(bars[0]["quote_volume"], 30.1)
        self.assertAlmostEqual(bars[0]["taker_buy_quote_volume"], 20.0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime" / "seconds.json"
            cache.write_json(path)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(written["schema"], "bfa_raw_feed_second_bars_v1")
        self.assertIn("BTCUSDT", written["symbols"])

    def test_second_bar_cache_can_resume_from_existing_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seconds.json"
            cache = RawSecondBarCache(window_seconds=1200)
            cache.ingest_trade(
                symbol="BTCUSDT",
                event_time_ms=1700000000000,
                price=100.0,
                quantity=0.2,
                taker_buy=True,
            )
            cache.write_json(path)

            resumed = RawSecondBarCache.load_json(path, window_seconds=1200)
            resumed.ingest_trade(
                symbol="BTCUSDT",
                event_time_ms=1700000001000,
                price=101.0,
                quantity=0.1,
                taker_buy=False,
            )

        bars = resumed.to_dict()["symbols"]["BTCUSDT"]
        self.assertEqual([item["open_time"] for item in bars], [1700000000000, 1700000001000])
        self.assertEqual(bars[0]["close"], 100.0)
        self.assertEqual(bars[1]["close"], 101.0)


if __name__ == "__main__":
    unittest.main()
