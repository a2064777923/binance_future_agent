import unittest
import zipfile
import io
import csv

from bfa.market.vision_archives import (
    funding_rate_url,
    klines_monthly_url,
    parse_funding_rate_zip,
    parse_klines_zip,
)
from bfa.backtest.models import BacktestBar


def _funding_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["calc_time", "funding_interval_hours", "last_funding_rate"])
        for r in rows:
            w.writerow(r)
        z.writestr("BTCUSDT-fundingRate-2026-02.csv", out.getvalue())
    return buf.getvalue()


def _klines_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time",
                    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"])
        for r in rows:
            w.writerow(r)
        z.writestr("BTCUSDT-5m-2026-02.csv", out.getvalue())
    return buf.getvalue()


class TestVisionArchives(unittest.TestCase):
    def test_funding_rate_url_format(self):
        self.assertEqual(
            funding_rate_url("BTCUSDT", "2026-02"),
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-02.zip",
        )

    def test_klines_monthly_url_format(self):
        self.assertEqual(
            klines_monthly_url("BTCUSDT", "5m", "2026-02"),
            "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-02.zip",
        )

    def test_parse_funding_rate_zip(self):
        data = _funding_zip([["1769904000001", "8", "0.0001"], ["1769932800004", "8", "-0.0002"]])
        rates = parse_funding_rate_zip(data)
        self.assertEqual(rates, [(1769904000001, 0.0001), (1769932800004, -0.0002)])

    def test_parse_klines_zip_to_backtest_bars(self):
        rows = [["1769904000000", "100.0", "101.0", "99.5", "100.8", "50", "1769904299999",
                 "5000", "10", "30", "3000", "0"]]
        bars = parse_klines_zip("BTCUSDT", _klines_zip(rows))
        self.assertEqual(len(bars), 1)
        b = bars[0]
        self.assertIsInstance(b, BacktestBar)
        self.assertEqual(b.symbol, "BTCUSDT")
        self.assertEqual(b.open_time, 1769904000000)
        self.assertAlmostEqual(b.open, 100.0)
        self.assertAlmostEqual(b.taker_buy_quote_volume, 3000.0)


if __name__ == "__main__":
    unittest.main()
