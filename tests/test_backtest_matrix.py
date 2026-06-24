import unittest

from bfa.backtest.matrix import (
    BacktestMatrixConfig,
    BacktestMatrixSuiteConfig,
    HotUniverseConfig,
    hot_universe_presets,
    run_hot_backtest_matrix,
    run_hot_backtest_matrix_suite,
    select_hot_usdt_symbols,
)
from bfa.market.models import MarketDataResponse


FIVE_MINUTES_MS = 300_000


def ticker(symbol, *, price_change, quote_volume, count=1000):
    return {
        "symbol": symbol,
        "priceChangePercent": str(price_change),
        "quoteVolume": str(quote_volume),
        "count": count,
    }


def kline(open_time, *, open_price, high, low, close, quote_volume=2_000_000, taker_ratio=1.2):
    taker_buy_quote = quote_volume * (taker_ratio / (1 + taker_ratio))
    return [
        open_time,
        str(open_price),
        str(high),
        str(low),
        str(close),
        "1000",
        open_time + FIVE_MINUTES_MS - 1,
        str(quote_volume),
        10,
        "500",
        str(taker_buy_quote),
        "0",
    ]


def trend_rows(count=16):
    rows = []
    price = 100.0
    for index in range(count):
        close = price * 1.01
        rows.append(
            kline(
                1_700_000_000_000 + index * FIVE_MINUTES_MS,
                open_price=price,
                high=close * 1.025,
                low=price * 0.998,
                close=close,
            )
        )
        price = close
    return rows


class FakeClient:
    def __init__(self):
        self.calls = []

    def ticker_24hr(self, symbol=None):
        self.calls.append(("ticker_24hr", symbol))
        return MarketDataResponse(
            endpoint="/fapi/v1/ticker/24hr",
            params={},
            payload=[
                ticker("AAAUSDT", price_change=8.0, quote_volume=25_000_000),
                ticker("BBBUSDT", price_change=-6.0, quote_volume=30_000_000),
                ticker("USDCUSDT", price_change=4.0, quote_volume=100_000_000),
                ticker("CCCUSDT", price_change=1.0, quote_volume=50_000_000),
                ticker("AAABTC", price_change=20.0, quote_volume=999_000_000),
            ],
        )

    def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
        self.calls.append(("klines", symbol, interval, limit, start_time, end_time))
        return MarketDataResponse(
            endpoint="/fapi/v1/klines",
            params={},
            payload=trend_rows(limit),
        )


class BacktestMatrixTests(unittest.TestCase):
    def test_select_hot_usdt_symbols_filters_and_ranks(self):
        rows = [
            ticker("LOWUSDT", price_change=9.0, quote_volume=1_000_000),
            ticker("MOVEUSDT", price_change=-7.0, quote_volume=20_000_000),
            ticker("BIGUSDT", price_change=4.0, quote_volume=50_000_000),
            ticker("USDCUSDT", price_change=10.0, quote_volume=80_000_000),
            ticker("MOVEETH", price_change=20.0, quote_volume=90_000_000),
        ]

        selected = select_hot_usdt_symbols(rows, HotUniverseConfig(top_n=2))

        self.assertEqual([item["symbol"] for item in selected], ["BIGUSDT", "MOVEUSDT"])
        self.assertTrue(all(item["symbol"].endswith("USDT") for item in selected))

    def test_hot_universe_presets_resolve_named_configs(self):
        presets = hot_universe_presets(["broad", "momentum"])

        self.assertEqual([item.name for item in presets], ["broad", "momentum"])
        self.assertGreater(presets[0].config.top_n, presets[1].config.top_n)
        with self.assertRaises(ValueError):
            hot_universe_presets(["unknown"])

    def test_hot_backtest_matrix_auto_selects_symbols_and_reports_promotion(self):
        client = FakeClient()

        payload = run_hot_backtest_matrix(
            client,
            BacktestMatrixConfig(
                intervals=("5m", "15m"),
                limit=16,
                window_bars=8,
                step_bars=4,
                variants=("balanced",),
                hot_universe=HotUniverseConfig(top_n=2, min_quote_volume_usdt=10_000_000),
            ),
        )

        self.assertEqual(payload["schema"], "bfa_hot_backtest_matrix_v1")
        self.assertEqual(payload["symbols"], ["BBBUSDT", "AAAUSDT"])
        self.assertEqual(payload["hot_universe"]["source"], "binance_24h_ticker")
        self.assertEqual(len(payload["reports"]), 2)
        self.assertIn("balanced", payload["promotion"]["variants"])
        self.assertIn(
            payload["promotion"]["overall"],
            {
                "candidate_for_forward_paper",
                "mixed_candidate_collect_more_data",
                "keep_caps_unchanged_drawdown_risk",
                "keep_caps_unchanged",
            },
        )
        self.assertEqual(client.calls[0], ("ticker_24hr", None))

    def test_hot_backtest_matrix_manual_symbols_skips_ticker_selection(self):
        client = FakeClient()

        payload = run_hot_backtest_matrix(
            client,
            BacktestMatrixConfig(
                intervals=("5m",),
                limit=16,
                window_bars=8,
                step_bars=4,
                variants=("balanced",),
            ),
            symbols=["solusdt"],
        )

        self.assertEqual(payload["symbols"], ["SOLUSDT"])
        self.assertEqual(payload["hot_universe"]["source"], "manual_symbols")
        self.assertTrue(all(call[0] != "ticker_24hr" for call in client.calls))

    def test_hot_backtest_matrix_accepts_quant_setup_variants(self):
        client = FakeClient()

        payload = run_hot_backtest_matrix(
            client,
            BacktestMatrixConfig(
                intervals=("5m",),
                limit=16,
                window_bars=8,
                step_bars=4,
                variants=(
                    "quant_setup",
                    "quant_setup_hf_profit_guarded",
                    "quant_setup_high_frequency_flow_guarded",
                    "quant_setup_high_frequency_guarded",
                    "quant_setup_selective",
                    "quant_setup_selective_guarded",
                    "quant_setup_loss_recalibrated",
                ),
            ),
            symbols=["AAAUSDT"],
        )

        self.assertEqual(
            payload["matrix_config"]["variants"],
            [
                "quant_setup",
                "quant_setup_hf_profit_guarded",
                "quant_setup_high_frequency_flow_guarded",
                "quant_setup_high_frequency_guarded",
                "quant_setup_selective",
                "quant_setup_selective_guarded",
                "quant_setup_loss_recalibrated",
            ],
        )
        self.assertIn("quant_setup", payload["promotion"]["variants"])
        self.assertIn("quant_setup_hf_profit_guarded", payload["promotion"]["variants"])
        self.assertIn("quant_setup_high_frequency_flow_guarded", payload["promotion"]["variants"])
        self.assertIn("quant_setup_high_frequency_guarded", payload["promotion"]["variants"])
        self.assertIn("quant_setup_selective", payload["promotion"]["variants"])
        self.assertIn("quant_setup_selective_guarded", payload["promotion"]["variants"])
        self.assertIn("quant_setup_loss_recalibrated", payload["promotion"]["variants"])

    def test_hot_backtest_matrix_suite_default_includes_high_frequency_variant(self):
        self.assertIn("quant_setup_hf_profit_guarded", BacktestMatrixSuiteConfig().variants)
        self.assertIn("quant_setup_high_frequency_flow_guarded", BacktestMatrixSuiteConfig().variants)
        self.assertIn("quant_setup_high_frequency_guarded", BacktestMatrixSuiteConfig().variants)

    def test_hot_backtest_matrix_suite_runs_multiple_universe_presets(self):
        client = FakeClient()

        payload = run_hot_backtest_matrix_suite(
            client,
            BacktestMatrixSuiteConfig(
                intervals=("5m",),
                limit=16,
                window_bars=8,
                step_bars=4,
                variants=("quant_setup_selective", "quant_setup_loss_recalibrated"),
                universe_presets=("broad", "momentum"),
            ),
        )

        self.assertEqual(payload["schema"], "bfa_hot_backtest_matrix_suite_v1")
        self.assertEqual([item["preset"] for item in payload["matrices"]], ["broad", "momentum"])
        self.assertIn("quant_setup_selective", payload["promotion"]["variants"])
        self.assertIn("quant_setup_loss_recalibrated", payload["promotion"]["variants"])
        self.assertEqual(payload["promotion"]["variants"]["quant_setup_selective"]["matrix_count"], 2)
        self.assertEqual(
            [call for call in client.calls if call[0] == "ticker_24hr"],
            [("ticker_24hr", None), ("ticker_24hr", None)],
        )

    def test_hot_backtest_matrix_reports_no_symbols_selected(self):
        client = FakeClient()

        payload = run_hot_backtest_matrix(
            client,
            BacktestMatrixConfig(
                intervals=("5m",),
                hot_universe=HotUniverseConfig(min_quote_volume_usdt=999_000_000),
            ),
        )

        self.assertEqual(payload["symbols"], [])
        self.assertEqual(payload["reports"], [])
        self.assertEqual(payload["promotion"]["overall"], "no_symbols_selected")
        self.assertEqual(client.calls, [("ticker_24hr", None)])

    def test_invalid_matrix_config_rejects_unknown_variant(self):
        with self.assertRaises(ValueError):
            run_hot_backtest_matrix(
                FakeClient(),
                BacktestMatrixConfig(variants=("unknown",)),
                symbols=["BTCUSDT"],
            )


if __name__ == "__main__":
    unittest.main()
