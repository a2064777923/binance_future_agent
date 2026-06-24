import csv
import gzip
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from bfa.backtest.hft_adapter import (
    AggTradeLike,
    HftSyntheticBboConfig,
    archive_url,
    event_time_bounds,
    round_to_lot,
    summarize_public_book_depth_archive,
    timestamp_intervals_seconds,
    convert_agg_trades_to_hft_events,
    convert_binance_raw_feed_to_hft,
    convert_historical_l2_csv_to_hft,
    hftbacktest_available,
    synthetic_bbo,
)


class HftAdapterTests(unittest.TestCase):
    def test_synthetic_bbo_keeps_ask_above_bid(self):
        bid, ask = synthetic_bbo(100.0, tick_size=0.1, half_spread=0.1)

        self.assertEqual(bid, 99.9)
        self.assertEqual(ask, 100.1)

    def test_round_to_lot_never_returns_below_one_lot(self):
        self.assertEqual(round_to_lot(0.01, 1.0), 1.0)
        self.assertEqual(round_to_lot(2.4, 1.0), 2.0)
        self.assertAlmostEqual(round_to_lot(2.6, 0.1), 2.6)

    def test_archive_url_preserves_case_sensitive_market_name(self):
        url = archive_url("bookDepth", "nearusdt", date(2026, 5, 23))

        self.assertIn("/bookDepth/NEARUSDT/", url)
        self.assertTrue(url.endswith("NEARUSDT-bookDepth-2026-05-23.zip"))

    def test_timestamp_intervals_seconds_parses_public_bookdepth_timestamps(self):
        intervals = timestamp_intervals_seconds(
            [
                "2026-05-23 00:02:31",
                "2026-05-23 00:03:00",
                "2026-05-23 00:03:32",
            ]
        )

        self.assertEqual(intervals, [29.0, 32.0])

    def test_summarize_public_book_depth_marks_not_l2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "TESTUSDT-bookDepth-2026-05-23.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "TESTUSDT-bookDepth-2026-05-23.csv",
                    "\n".join(
                        [
                            "timestamp,percentage,depth,notional",
                            "2026-05-23 00:02:31,-0.20,10,100",
                            "2026-05-23 00:02:31,0.20,11,110",
                            "2026-05-23 00:03:00,-0.20,12,120",
                            "2026-05-23 00:03:00,0.20,13,130",
                        ]
                    ),
                )

            summary = summarize_public_book_depth_archive("TESTUSDT", date(2026, 5, 23), path)

        self.assertFalse(summary.is_l2_order_book)
        self.assertEqual(summary.rows, 4)
        self.assertEqual(summary.timestamps, 2)
        self.assertEqual(summary.percentages, (-0.2, 0.2))
        self.assertEqual(summary.median_interval_seconds, 29.0)
        self.assertIn("not tick-by-tick L2", summary.warning)

    @unittest.skipUnless(hftbacktest_available(), "hftbacktest optional dependency is not installed")
    def test_convert_agg_trades_to_hft_events_marks_depth_and_trade_flags(self):
        from hftbacktest import EXCH_EVENT, LOCAL_EVENT
        from hftbacktest.types import BUY_EVENT, DEPTH_SNAPSHOT_EVENT, SELL_EVENT, TRADE_EVENT

        events = convert_agg_trades_to_hft_events(
            [
                AggTradeLike(time_ms=1_700_000_000_000, price=100.0, quantity=0.5, buyer_maker=False),
                AggTradeLike(time_ms=1_700_000_000_001, price=100.2, quantity=0.3, buyer_maker=True),
            ],
            config=HftSyntheticBboConfig(tick_size=0.1, synthetic_spread_ticks=1),
        )

        self.assertEqual(len(events), 8)
        self.assertTrue(events[0]["ev"] & DEPTH_SNAPSHOT_EVENT)
        self.assertTrue(events[0]["ev"] & BUY_EVENT)
        self.assertTrue(events[0]["ev"] & EXCH_EVENT)
        self.assertTrue(events[0]["ev"] & LOCAL_EVENT)
        self.assertTrue(events[4]["ev"] & TRADE_EVENT)
        self.assertTrue(events[4]["ev"] & BUY_EVENT)
        self.assertTrue(events[7]["ev"] & TRADE_EVENT)
        self.assertTrue(events[7]["ev"] & SELL_EVENT)
        self.assertEqual(events[4]["px"], 100.0)
        self.assertEqual(events[7]["qty"], 0.3)

    @unittest.skipUnless(hftbacktest_available(), "hftbacktest optional dependency is not installed")
    def test_convert_historical_l2_csv_to_hft_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            depth = tmp_path / "depth.csv"
            trades = tmp_path / "trades.csv"
            with depth.open("w", newline="", encoding="utf-8") as raw:
                writer = csv.writer(raw)
                writer.writerow(["symbol", "timestamp", "trans_id", "first_update_id", "last_update_id", "side", "update_type", "price", "qty"])
                writer.writerow(["TESTUSDT", 1_700_000_000_000, 1, 1, 1, "b", "set", "99.9", "10"])
                writer.writerow(["TESTUSDT", 1_700_000_000_000, 2, 1, 1, "a", "set", "100.1", "10"])
            with trades.open("w", newline="", encoding="utf-8") as raw:
                writer = csv.writer(raw)
                writer.writerow(["id", "price", "qty", "quote_qty", "time", "is_buyer_maker"])
                writer.writerow([1, "100.0", "0.5", "50", 1_700_000_000_001, "false"])

            events, conversion = convert_historical_l2_csv_to_hft(depth, trades, buffer_size=16)

        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(conversion.event_count, len(events))
        self.assertIsNotNone(conversion.first_timestamp)
        self.assertIsNotNone(conversion.last_timestamp)

    @unittest.skipUnless(hftbacktest_available(), "hftbacktest optional dependency is not installed")
    def test_convert_binance_raw_feed_to_hft_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "raw.gz"
            lines = [
                (
                    1_700_000_000_000_000_000,
                    {
                        "stream": "testusdt@depth@0ms",
                        "data": {
                            "e": "depthUpdate",
                            "E": 1_700_000_000_000,
                            "T": 1_700_000_000_000,
                            "s": "TESTUSDT",
                            "U": 1,
                            "u": 1,
                            "pu": 0,
                            "b": [["99.9", "10"]],
                            "a": [["100.1", "10"]],
                        },
                    },
                ),
                (
                    1_700_000_000_001_000_000,
                    {
                        "stream": "testusdt@trade",
                        "data": {
                            "e": "trade",
                            "E": 1_700_000_000_001,
                            "T": 1_700_000_000_001,
                            "s": "TESTUSDT",
                            "t": 1,
                            "p": "100.0",
                            "q": "0.5",
                            "X": "MARKET",
                            "m": False,
                        },
                    },
                ),
            ]
            with gzip.open(raw_path, "wt", encoding="utf-8") as raw:
                for local_ts, payload in lines:
                    raw.write(f"{local_ts} {json.dumps(payload, separators=(',', ':'))}\n")

            events, conversion = convert_binance_raw_feed_to_hft(raw_path, buffer_size=16)

        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(conversion.event_count, len(events))
        first, last = event_time_bounds(events)
        self.assertEqual(conversion.first_timestamp_ns, first)
        self.assertEqual(conversion.last_timestamp_ns, last)


if __name__ == "__main__":
    unittest.main()
