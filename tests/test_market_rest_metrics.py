import json
import unittest
from pathlib import Path

from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.models import MarketDataResponse


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binance_market"


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url, *, timeout):
        self.calls.append({"url": url, "timeout": timeout})
        return 200, self.payload, {"X-MBX-USED-WEIGHT-1M": "1"}


def load_metrics():
    return json.loads((FIXTURE_DIR / "rest_metrics.json").read_text(encoding="utf-8"))


class RestCurrentMetricTests(unittest.TestCase):
    def build_client(self, payload):
        transport = FakeTransport(payload)
        client = BinanceFuturesRestClient(
            base_url="https://fapi.binance.com",
            transport=transport,
            timeout=5,
        )
        return client, transport

    def test_ticker_24hr_requires_explicit_uppercase_symbol(self):
        client, transport = self.build_client(load_metrics()["ticker_24hr"])

        response = client.ticker_24hr("btcusdt")

        self.assertIsInstance(response, MarketDataResponse)
        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT",
        )

    def test_ticker_24hr_can_fetch_all_symbols_without_symbol_param(self):
        client, transport = self.build_client([load_metrics()["ticker_24hr"]])

        response = client.ticker_24hr()

        self.assertEqual(response.endpoint, "/fapi/v1/ticker/24hr")
        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
        )

    def test_klines_uses_symbol_interval_and_limit_params(self):
        client, transport = self.build_client(load_metrics()["klines"])

        client.klines("BTCUSDT", interval="5m", limit=30)

        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=30",
        )

    def test_klines_accepts_start_and_end_time_params(self):
        client, transport = self.build_client(load_metrics()["klines"])

        client.klines(
            "BTCUSDT",
            interval="5m",
            limit=30,
            start_time=1700000000000,
            end_time=1700000900000,
        )

        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=30&startTime=1700000000000&endTime=1700000900000",
        )

    def test_funding_rate_and_open_interest_use_public_symbol_endpoints(self):
        client, funding_transport = self.build_client(load_metrics()["funding_rate"])
        funding = client.funding_rate("BTCUSDT", limit=20)

        client, interest_transport = self.build_client(load_metrics()["open_interest"])
        open_interest = client.open_interest("BTCUSDT")

        self.assertEqual(funding.endpoint, "/fapi/v1/fundingRate")
        self.assertEqual(open_interest.endpoint, "/fapi/v1/openInterest")
        self.assertEqual(
            funding_transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=20",
        )
        self.assertEqual(
            interest_transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
        )

    def test_blank_symbol_and_non_positive_limit_are_rejected(self):
        client, _transport = self.build_client({})

        with self.assertRaises(ValueError):
            client.ticker_24hr("")
        with self.assertRaises(ValueError):
            client.klines("BTCUSDT", interval="5m", limit=0)
        with self.assertRaises(ValueError):
            client.klines("BTCUSDT", interval="5m", start_time=-1)


class RestHistoricalMetricTests(unittest.TestCase):
    def build_client(self, payload):
        transport = FakeTransport(payload)
        client = BinanceFuturesRestClient(
            base_url="https://fapi.binance.com",
            transport=transport,
            timeout=5,
        )
        return client, transport

    def test_open_interest_hist_uses_symbol_period_and_limit_params(self):
        client, transport = self.build_client(load_metrics()["open_interest_hist"])

        response = client.open_interest_hist("btcusdt", period="5m", limit=30)

        self.assertIsInstance(response, MarketDataResponse)
        self.assertEqual(response.endpoint, "/futures/data/openInterestHist")
        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=30",
        )

    def test_top_long_short_position_ratio_uses_public_positioning_endpoint(self):
        client, transport = self.build_client(load_metrics()["top_long_short_position_ratio"])

        response = client.top_long_short_position_ratio("BTCUSDT", period="5m", limit=30)

        self.assertEqual(response.endpoint, "/futures/data/topLongShortPositionRatio")
        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=5m&limit=30",
        )

    def test_taker_buy_sell_volume_uses_public_taker_flow_endpoint(self):
        client, transport = self.build_client(load_metrics()["taker_buy_sell_volume"])

        response = client.taker_buy_sell_volume("BTCUSDT", period="5m", limit=30)

        self.assertEqual(response.endpoint, "/futures/data/takerlongshortRatio")
        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=5m&limit=30",
        )

    def test_historical_metrics_reject_blank_period_and_out_of_range_limit(self):
        client, _transport = self.build_client({})

        with self.assertRaises(ValueError):
            client.open_interest_hist("BTCUSDT", period="", limit=30)
        with self.assertRaises(ValueError):
            client.top_long_short_position_ratio("BTCUSDT", period="5m", limit=0)
        with self.assertRaises(ValueError):
            client.taker_buy_sell_volume("BTCUSDT", period="5m", limit=501)


if __name__ == "__main__":
    unittest.main()
