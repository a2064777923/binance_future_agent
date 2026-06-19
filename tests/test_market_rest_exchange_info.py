import json
import unittest
from pathlib import Path

from bfa.market.binance_rest import BinanceFuturesRestClient, BinanceMarketDataError
from bfa.market.models import MarketDataResponse, parse_exchange_symbols


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binance_market"


class FakeTransport:
    def __init__(self, payload=None, status_code=200, headers=None):
        self.payload = {} if payload is None else payload
        self.status_code = status_code
        self.headers = {} if headers is None else headers
        self.calls = []

    def get_json(self, url, *, timeout):
        self.calls.append({"url": url, "timeout": timeout})
        return self.status_code, self.payload, self.headers


class BinanceRestExchangeInfoTests(unittest.TestCase):
    def load_exchange_info(self):
        return json.loads((FIXTURE_DIR / "exchange_info.json").read_text(encoding="utf-8"))

    def test_exchange_info_uses_fake_transport_and_returns_response(self):
        transport = FakeTransport(
            payload=self.load_exchange_info(),
            headers={"X-MBX-USED-WEIGHT-1M": "1"},
        )
        client = BinanceFuturesRestClient(
            base_url="https://fapi.binance.com",
            transport=transport,
            timeout=7.5,
        )

        response = client.exchange_info()

        self.assertIsInstance(response, MarketDataResponse)
        self.assertEqual(response.endpoint, "/fapi/v1/exchangeInfo")
        self.assertEqual(response.params, {})
        self.assertEqual(response.request_weight, "1")
        self.assertEqual(
            transport.calls,
            [{"url": "https://fapi.binance.com/fapi/v1/exchangeInfo", "timeout": 7.5}],
        )
        self.assertEqual(parse_exchange_symbols(response.payload)[0].symbol, "BTCUSDT")

    def test_public_client_does_not_add_private_auth_material(self):
        transport = FakeTransport(payload=self.load_exchange_info())
        client = BinanceFuturesRestClient(
            base_url="https://fapi.binance.com/",
            transport=transport,
        )

        client.exchange_info()
        requested_url = transport.calls[0]["url"]

        self.assertNotIn("signature=", requested_url)
        self.assertNotIn("listenKey", requested_url)
        self.assertNotIn("account", requested_url.lower())
        self.assertNotIn("order", requested_url.lower())

    def test_non_2xx_binance_error_payload_raises_structured_error(self):
        transport = FakeTransport(
            payload={"code": -1121, "msg": "Invalid symbol."},
            status_code=400,
            headers={"X-MBX-USED-WEIGHT-1M": "3"},
        )
        client = BinanceFuturesRestClient(
            base_url="https://fapi.binance.com",
            transport=transport,
        )

        with self.assertRaises(BinanceMarketDataError) as raised:
            client.exchange_info()

        error = raised.exception
        self.assertEqual(error.endpoint, "/fapi/v1/exchangeInfo")
        self.assertEqual(error.params, {})
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.binance_code, -1121)
        self.assertEqual(error.binance_message, "Invalid symbol.")
        self.assertEqual(error.request_weight, "3")


if __name__ == "__main__":
    unittest.main()
