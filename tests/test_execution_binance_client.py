import unittest
from urllib.parse import parse_qs, urlparse

from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError


class FakeSignedTransport:
    def __init__(self, response=(200, {"ok": True}, None)):
        self.response = response
        self.calls = []

    def request_json(self, url, *, method, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "method": method,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        status, payload, headers_out = self.response
        return status, payload, {} if headers_out is None else headers_out


class BinanceSignedClientTests(unittest.TestCase):
    def client(self, transport):
        return BinanceFuturesSignedClient(
            base_url="https://fapi.binance.com",
            api_key="synthetic-binance-key-abcdef",
            api_secret="synthetic-binance-secret-abcdef",
            transport=transport,
            timestamp_ms=lambda: 1700000000000,
            recv_window=6000,
            timeout=8.0,
        )

    def test_new_order_signs_request_with_api_key_header(self):
        transport = FakeSignedTransport(response=(200, {"orderId": 123}, {}))
        client = self.client(transport)

        response = client.new_order(
            symbol="btcusdt",
            side="BUY",
            order_type="MARKET",
            quantity=0.2,
            new_client_order_id="bfa-test-1",
        )

        call = transport.calls[0]
        parsed = urlparse(call["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(response["orderId"], 123)
        self.assertEqual(call["method"], "POST")
        self.assertEqual(parsed.path, "/fapi/v1/order")
        self.assertEqual(call["headers"]["X-MBX-APIKEY"], "synthetic-binance-key-abcdef")
        self.assertEqual(query["symbol"], ["BTCUSDT"])
        self.assertEqual(query["side"], ["BUY"])
        self.assertEqual(query["type"], ["MARKET"])
        self.assertEqual(query["quantity"], ["0.2"])
        self.assertEqual(query["timestamp"], ["1700000000000"])
        self.assertEqual(query["recvWindow"], ["6000"])
        self.assertIn("signature", query)

    def test_margin_and_leverage_use_expected_endpoints(self):
        transport = FakeSignedTransport()
        client = self.client(transport)

        client.change_margin_type("BTCUSDT", margin_type="isolated")
        client.change_initial_leverage("BTCUSDT", leverage=3)

        self.assertEqual(urlparse(transport.calls[0]["url"]).path, "/fapi/v1/marginType")
        self.assertIn("marginType=ISOLATED", transport.calls[0]["url"])
        self.assertEqual(urlparse(transport.calls[1]["url"]).path, "/fapi/v1/leverage")
        self.assertIn("leverage=3", transport.calls[1]["url"])

    def test_new_algo_order_uses_conditional_algo_endpoint(self):
        transport = FakeSignedTransport(response=(200, {"algoId": 456}, {}))
        client = self.client(transport)

        response = client.new_algo_order(
            symbol="btcusdt",
            side="SELL",
            order_type="STOP_MARKET",
            stop_price=96.0,
            client_algo_id="bfa-test-sl",
        )

        call = transport.calls[0]
        parsed = urlparse(call["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(response["algoId"], 456)
        self.assertEqual(call["method"], "POST")
        self.assertEqual(parsed.path, "/fapi/v1/algoOrder")
        self.assertEqual(query["symbol"], ["BTCUSDT"])
        self.assertEqual(query["side"], ["SELL"])
        self.assertEqual(query["algoType"], ["CONDITIONAL"])
        self.assertEqual(query["type"], ["STOP_MARKET"])
        self.assertEqual(query["stopPrice"], ["96"])
        self.assertEqual(query["closePosition"], ["true"])
        self.assertEqual(query["clientAlgoId"], ["bfa-test-sl"])
        self.assertIn("signature", query)

    def test_cancel_order_uses_delete_order_endpoint(self):
        transport = FakeSignedTransport(response=(200, {"status": "CANCELED"}, {}))
        client = self.client(transport)

        response = client.cancel_order(symbol="BTCUSDT", orig_client_order_id="bfa-test-1")

        call = transport.calls[0]
        parsed = urlparse(call["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(response["status"], "CANCELED")
        self.assertEqual(call["method"], "DELETE")
        self.assertEqual(parsed.path, "/fapi/v1/order")
        self.assertEqual(query["origClientOrderId"], ["bfa-test-1"])
        self.assertIn("signature", query)

    def test_cancel_order_requires_order_identifier(self):
        client = self.client(FakeSignedTransport())

        with self.assertRaises(ValueError):
            client.cancel_order(symbol="BTCUSDT")

    def test_account_open_orders_and_position_risk_are_fakeable(self):
        transport = FakeSignedTransport(response=(200, [], {}))
        client = self.client(transport)

        client.account()
        client.open_orders("BTCUSDT")
        client.position_risk("BTCUSDT")

        paths = [urlparse(call["url"]).path for call in transport.calls]
        self.assertEqual(paths, ["/fapi/v3/account", "/fapi/v1/openOrders", "/fapi/v2/positionRisk"])

    def test_error_payload_raises_structured_error_without_signature(self):
        transport = FakeSignedTransport(response=(400, {"code": -2019, "msg": "Margin is insufficient."}, {}))
        client = self.client(transport)

        with self.assertRaises(BinanceSignedError) as raised:
            client.new_order(symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.2)

        error = raised.exception
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.binance_code, -2019)
        self.assertNotIn("signature", error.params)


if __name__ == "__main__":
    unittest.main()
