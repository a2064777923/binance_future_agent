import json
import tempfile
import unittest
from pathlib import Path

from bfa.market.models import NormalizedMarketSnapshot
from bfa.market.normalize import (
    normalize_exchange_info,
    normalize_funding_rate,
    normalize_kline,
    normalize_open_interest,
    normalize_open_interest_hist,
    normalize_taker_buy_sell_volume,
    normalize_ticker_24h,
    normalize_top_long_short_position,
)
from bfa.market.snapshot_writer import write_jsonl_snapshots


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binance_market"


def load_payloads():
    return json.loads((FIXTURE_DIR / "normalization_payloads.json").read_text(encoding="utf-8"))


class RestNormalizationTests(unittest.TestCase):
    def test_exchange_info_symbols_normalize_with_filter_strings(self):
        payloads = load_payloads()

        snapshots = normalize_exchange_info(payloads["exchange_info"], received_at="now")

        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertIsInstance(snapshot, NormalizedMarketSnapshot)
        self.assertEqual(snapshot.source, "binance_usdm")
        self.assertEqual(snapshot.event_type, "exchange_symbol")
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.event_time, 1700000000000)
        self.assertEqual(snapshot.received_at, "now")
        self.assertEqual(snapshot.payload["status"], "TRADING")
        self.assertEqual(snapshot.payload["filters"]["PRICE_FILTER"]["tickSize"], "0.10")

    def test_rest_metric_payloads_normalize_to_documented_event_types(self):
        payloads = load_payloads()
        received_at = 1700000009999

        snapshots = [
            normalize_ticker_24h(payloads["ticker_24hr"], received_at=received_at),
            normalize_kline("BTCUSDT", payloads["kline"], interval="5m", received_at=received_at),
            normalize_funding_rate(payloads["funding_rate"], received_at=received_at),
            normalize_open_interest(payloads["open_interest"], received_at=received_at),
            normalize_open_interest_hist(payloads["open_interest_hist"], received_at=received_at),
            normalize_top_long_short_position(
                payloads["top_long_short_position_ratio"],
                received_at=received_at,
            ),
            normalize_taker_buy_sell_volume(payloads["taker_buy_sell_volume"], received_at=received_at),
        ]

        self.assertEqual(
            [snapshot.event_type for snapshot in snapshots],
            [
                "ticker_24h",
                "kline",
                "funding_rate",
                "open_interest",
                "open_interest_hist",
                "top_long_short_position",
                "taker_buy_sell_volume",
            ],
        )
        for snapshot in snapshots:
            self.assertEqual(snapshot.source, "binance_usdm")
            self.assertEqual(snapshot.symbol, "BTCUSDT")
            self.assertEqual(snapshot.received_at, received_at)

    def test_rest_snapshots_preserve_endpoint_specific_metadata(self):
        payloads = load_payloads()

        ticker = normalize_ticker_24h(payloads["ticker_24hr"], received_at="now")
        kline = normalize_kline("btcusdt", payloads["kline"], interval="5m", received_at="now")
        funding = normalize_funding_rate(payloads["funding_rate"], received_at="now")
        open_interest_hist = normalize_open_interest_hist(payloads["open_interest_hist"], received_at="now")
        taker_flow = normalize_taker_buy_sell_volume(payloads["taker_buy_sell_volume"], received_at="now")

        self.assertEqual(ticker.event_time, 1700003600000)
        self.assertEqual(ticker.payload["last_price"], "70100.00")
        self.assertEqual(kline.event_time, 1700000000000)
        self.assertEqual(kline.payload["interval"], "5m")
        self.assertEqual(kline.payload["trade_count"], 1000)
        self.assertEqual(funding.event_time, 1700000000000)
        self.assertEqual(funding.payload["funding_rate"], "0.00010000")
        self.assertEqual(open_interest_hist.event_time, "1700000000000")
        self.assertEqual(open_interest_hist.payload["sum_open_interest"], "20403.63700000")
        self.assertEqual(taker_flow.payload["buy_volume"], "387.3300")

    def test_taker_buy_sell_volume_allows_symbol_from_request_context(self):
        payloads = load_payloads()
        payload = dict(payloads["taker_buy_sell_volume"])
        payload.pop("symbol", None)

        snapshot = normalize_taker_buy_sell_volume(payload, symbol="btcusdt", received_at="now")

        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.event_type, "taker_buy_sell_volume")


class SnapshotWriterTests(unittest.TestCase):
    def make_snapshot(self, symbol="BTCUSDT"):
        return NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="ticker_24h",
            symbol=symbol,
            event_time=1700000000000,
            received_at="now",
            payload={"last_price": "70100.00"},
        )

    def test_write_jsonl_snapshots_creates_parent_and_writes_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "runtime" / "snapshots" / "market.jsonl"

            count = write_jsonl_snapshots(output_path, [self.make_snapshot()])

            self.assertEqual(count, 1)
            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["source"], "binance_usdm")
            self.assertEqual(payload["symbol"], "BTCUSDT")
            self.assertEqual(payload["payload"]["last_price"], "70100.00")

    def test_write_jsonl_snapshots_appends_serializable_dicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "data" / "market.jsonl"

            write_jsonl_snapshots(output_path, [self.make_snapshot("BTCUSDT")])
            count = write_jsonl_snapshots(output_path, [self.make_snapshot("ETHUSDT")])

            self.assertEqual(count, 1)
            records = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["symbol"] for record in records], ["BTCUSDT", "ETHUSDT"])

    def test_write_jsonl_snapshots_empty_list_returns_zero_without_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "runtime" / "empty.jsonl"

            count = write_jsonl_snapshots(output_path, [])

            self.assertEqual(count, 0)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
