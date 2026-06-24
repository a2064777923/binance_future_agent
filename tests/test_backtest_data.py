import json
import tempfile
import unittest
from pathlib import Path

from bfa.backtest.data import fetch_historical_klines, load_klines_dataset, parse_time_ms, write_klines_dataset
from bfa.market.models import MarketDataResponse


def kline(open_time, open_price="100", high="101", low="99", close="100.5"):
    return [
        open_time,
        open_price,
        high,
        low,
        close,
        "10",
        open_time + 299_999,
        "2000000",
        10,
        "5",
        "1200000",
        "0",
    ]


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
        self.calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        payload = self.pages.pop(0) if self.pages else []
        return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=payload)


class BacktestDataTests(unittest.TestCase):
    def test_parse_time_ms_accepts_iso_and_epoch_text(self):
        self.assertEqual(parse_time_ms("1700000000000"), 1700000000000)
        self.assertEqual(parse_time_ms("2023-11-14T22:13:20Z"), 1700000000000)

    def test_write_and_load_multi_symbol_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "klines.json"
            write_klines_dataset(
                path,
                interval="5m",
                symbols={"BTCUSDT": [kline(1_700_000_000_000)], "ETHUSDT": [kline(1_700_000_300_000)]},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded = load_klines_dataset(path)

        self.assertEqual(payload["schema"], "bfa_klines_v1")
        self.assertEqual(sorted(loaded), ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(loaded["BTCUSDT"][0].symbol, "BTCUSDT")
        self.assertGreater(loaded["BTCUSDT"][0].taker_buy_sell_ratio, 1)

    def test_fetch_historical_klines_pages_with_start_and_end(self):
        client = FakeClient(
            [
                [kline(1_700_000_000_000), kline(1_700_000_300_000)],
                [kline(1_700_000_600_000)],
            ]
        )

        rows = fetch_historical_klines(
            client,
            symbols=["btcusdt"],
            interval="5m",
            start="1700000000000",
            end="1700000900000",
            limit=3,
            page_limit=2,
        )

        self.assertEqual(len(rows["BTCUSDT"]), 3)
        self.assertEqual(client.calls[0]["start_time"], 1700000000000)
        self.assertEqual(client.calls[1]["start_time"], 1700000600000)
        self.assertEqual(client.calls[1]["limit"], 1)

    def test_unsupported_interval_rejects(self):
        with self.assertRaises(ValueError):
            fetch_historical_klines(FakeClient([]), symbols=["BTCUSDT"], interval="7m")

    def test_one_second_interval_is_supported_by_local_interval_map(self):
        client = FakeClient([[kline(1_700_000_000_000)]])

        rows = fetch_historical_klines(client, symbols=["BTCUSDT"], interval="1s", limit=1)

        self.assertEqual(len(rows["BTCUSDT"]), 1)
        self.assertEqual(client.calls[0]["interval"], "1s")


if __name__ == "__main__":
    unittest.main()
