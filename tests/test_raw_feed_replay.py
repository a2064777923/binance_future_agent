import csv
from datetime import UTC, datetime
import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from bfa.backtest.raw_feed_replay import extract_raw_trade_archives


class RawFeedReplayTests(unittest.TestCase):
    def test_extracts_selected_trade_once_and_keeps_receive_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            out = root / "cache"
            raw.mkdir()
            event_ms = int(datetime(2026, 7, 10, 20, 0, tzinfo=UTC).timestamp() * 1000)
            first = raw / "binance-usdm-raw-20260710T195900Z.gz"
            second = raw / "binance-usdm-raw-20260710T200001Z.gz"
            trade = {
                "stream": "btcusdt@trade",
                "data": {
                    "e": "trade",
                    "s": "BTCUSDT",
                    "t": 42,
                    "T": event_ms,
                    "p": "100.25",
                    "q": "0.5",
                    "m": False,
                },
            }
            depth = {"stream": "btcusdt@depth@100ms", "data": {"e": "depthUpdate", "s": "BTCUSDT"}}
            eth = {"stream": "ethusdt@trade", "data": {"e": "trade", "s": "ETHUSDT", "t": 1, "T": event_ms, "p": "2", "q": "1", "m": True}}
            with gzip.open(first, "wt", encoding="utf-8") as handle:
                handle.write(f"{(event_ms + 25) * 1_000_000} {json.dumps(depth, separators=(',', ':'))}\n")
                handle.write(f"{(event_ms + 25) * 1_000_000} {json.dumps(trade, separators=(',', ':'))}\n")
                handle.write(f"{(event_ms + 30) * 1_000_000} {json.dumps(eth, separators=(',', ':'))}\n")
            with gzip.open(second, "wt", encoding="utf-8") as handle:
                handle.write(f"{(event_ms + 40) * 1_000_000} {json.dumps(trade, separators=(',', ':'))}\n")

            report = extract_raw_trade_archives(
                raw,
                out,
                symbols=["BTCUSDT"],
                start_ms=event_ms - 1_000,
                end_ms=event_ms + 1_000,
            )

            coverage = report["coverage"]["BTCUSDT"]
            self.assertEqual(coverage["trade_count"], 1)
            self.assertEqual(coverage["duplicate_count"], 1)
            self.assertEqual(coverage["latency_ms_p50"], 25.0)
            archive = out / "BTCUSDT" / "BTCUSDT-aggTrades-2026-07-10.zip"
            with zipfile.ZipFile(archive) as zf:
                with zf.open(zf.namelist()[0]) as raw_csv:
                    rows = list(csv.reader(io.TextIOWrapper(raw_csv, encoding="utf-8")))
            self.assertEqual(rows, [["42", "100.25", "0.5", "42", "42", str(event_ms), "false"]])


if __name__ == "__main__":
    unittest.main()
