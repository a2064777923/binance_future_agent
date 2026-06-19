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

    def test_klines_uses_symbol_interval_and_limit_params(self):
        client, transport = self.build_client(load_metrics()["klines"])

        client.klines("BTCUSDT", interval="5m", limit=30)

        self.assertEqual(
            transport.calls[0]["url"],
            "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=30",
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


if __name__ == "__main__":
    unittest.main()
