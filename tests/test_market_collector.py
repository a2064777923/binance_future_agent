import unittest

from bfa.market.collector import MarketDataCollector
from bfa.market.models import MarketDataResponse


class FakeMarketClient:
    def __init__(self):
        self.calls = []

    def exchange_info(self):
        self.calls.append(("exchange_info",))
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload={
                "serverTime": 1700000000000,
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "marginAsset": "USDT",
                        "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.10"}],
                    }
                ],
            },
        )

    def ticker_24hr(self, symbol):
        self.calls.append(("ticker_24hr", symbol))
        return MarketDataResponse(
            endpoint="/fapi/v1/ticker/24hr",
            params={"symbol": symbol},
            payload={"symbol": symbol, "lastPrice": "70100.00", "closeTime": 1700003600000},
        )

    def klines(self, symbol, *, interval, limit):
        self.calls.append(("klines", symbol, interval, limit))
        return MarketDataResponse(
            endpoint="/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": str(limit)},
            payload=[
                [
                    1700000000000,
                    "70000.00",
                    "70200.00",
                    "69900.00",
                    "70100.00",
                    "123.456",
                    1700000299999,
                    "8650000.00",
                    1000,
                    "70.000",
                    "4900000.00",
                    "0",
                ]
            ],
        )

    def funding_rate(self, symbol, *, limit):
        self.calls.append(("funding_rate", symbol, limit))
        return MarketDataResponse(
            endpoint="/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": str(limit)},
            payload=[
                {
                    "symbol": symbol,
                    "fundingRate": "0.00010000",
                    "fundingTime": 1700000000000,
                    "markPrice": "70100.00",
                }
            ],
        )

    def open_interest(self, symbol):
        self.calls.append(("open_interest", symbol))
        return MarketDataResponse(
            endpoint="/fapi/v1/openInterest",
            params={"symbol": symbol},
            payload={"symbol": symbol, "openInterest": "10659.509", "time": 1700000000000},
        )

    def open_interest_hist(self, symbol, *, period, limit):
        self.calls.append(("open_interest_hist", symbol, period, limit))
        return MarketDataResponse(
            endpoint="/futures/data/openInterestHist",
            params={"symbol": symbol, "period": period, "limit": str(limit)},
            payload=[
                {
                    "symbol": symbol,
                    "sumOpenInterest": "20403.63700000",
                    "sumOpenInterestValue": "150570784.07809979",
                    "timestamp": "1700000000000",
                }
            ],
        )

    def top_long_short_position_ratio(self, symbol, *, period, limit):
        self.calls.append(("top_long_short_position_ratio", symbol, period, limit))
        return MarketDataResponse(
            endpoint="/futures/data/topLongShortPositionRatio",
            params={"symbol": symbol, "period": period, "limit": str(limit)},
            payload=[
                {
                    "symbol": symbol,
                    "longShortRatio": "1.4342",
                    "longAccount": "0.5891",
                    "shortAccount": "0.4108",
                    "timestamp": "1700000000000",
                }
            ],
        )

    def taker_buy_sell_volume(self, symbol, *, period, limit):
        self.calls.append(("taker_buy_sell_volume", symbol, period, limit))
        return MarketDataResponse(
            endpoint="/futures/data/takerlongshortRatio",
            params={"symbol": symbol, "period": period, "limit": str(limit)},
            payload=[
                {
                    "symbol": symbol,
                    "buySellRatio": "1.5586",
                    "buyVol": "387.3300",
                    "sellVol": "248.5030",
                    "timestamp": "1700000000000",
                }
            ],
        )


class MarketDataCollectorTests(unittest.TestCase):
    def test_collector_uses_fake_client_and_configured_symbols(self):
        client = FakeMarketClient()
        collector = MarketDataCollector(client=client, symbols=["btcusdt"], received_at="now")

        snapshots = collector.collect_rest_snapshots()

        self.assertEqual(client.calls[0], ("exchange_info",))
        self.assertIn(("ticker_24hr", "BTCUSDT"), client.calls)
        self.assertIn(("klines", "BTCUSDT", "5m", 30), client.calls)
        self.assertEqual({snapshot.source for snapshot in snapshots}, {"binance_usdm"})
        self.assertEqual({snapshot.symbol for snapshot in snapshots}, {"BTCUSDT"})

    def test_collector_returns_all_rest_metric_snapshot_types(self):
        collector = MarketDataCollector(client=FakeMarketClient(), symbols=["BTCUSDT"], received_at="now")

        snapshots = collector.collect_rest_snapshots()

        self.assertEqual(
            [snapshot.event_type for snapshot in snapshots],
            [
                "exchange_symbol",
                "ticker_24h",
                "kline",
                "funding_rate",
                "open_interest",
                "open_interest_hist",
                "top_long_short_position",
                "taker_buy_sell_volume",
            ],
        )

    def test_collector_rejects_empty_or_excessive_symbol_sets_before_requests(self):
        client = FakeMarketClient()

        with self.assertRaises(ValueError):
            MarketDataCollector(client=client, symbols=[]).collect_rest_snapshots()
        self.assertEqual(client.calls, [])

        with self.assertRaises(ValueError):
            MarketDataCollector(
                client=client,
                symbols=["BTCUSDT", "ETHUSDT"],
                max_symbols=1,
            ).collect_rest_snapshots()
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
