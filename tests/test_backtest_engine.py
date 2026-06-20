import unittest

from bfa.backtest.engine import run_hot_momentum_backtest, run_staged_sweep
from bfa.backtest.models import BacktestBar, BacktestConfig


FIVE_MINUTES_MS = 300_000


def bar(index, *, open_price, high, low, close, quote_volume=2_000_000, taker_ratio=1.2):
    open_time = 1_700_000_000_000 + index * FIVE_MINUTES_MS
    taker_buy_quote = quote_volume * (taker_ratio / (1 + taker_ratio))
    return BacktestBar(
        symbol="BTCUSDT",
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
        close_time=open_time + FIVE_MINUTES_MS - 1,
        quote_volume=quote_volume,
        taker_buy_quote_volume=taker_buy_quote,
    )


def symbol_bar(symbol, index, *, open_price, high, low, close, quote_volume=2_000_000, taker_ratio=1.2):
    item = bar(
        index,
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        quote_volume=quote_volume,
        taker_ratio=taker_ratio,
    )
    return BacktestBar(
        symbol=symbol,
        open_time=item.open_time,
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=item.volume,
        close_time=item.close_time,
        quote_volume=item.quote_volume,
        taker_buy_quote_volume=item.taker_buy_quote_volume,
    )


class BacktestEngineTests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "name": "unit",
            "lookback_bars": 3,
            "min_momentum_percent": 1.0,
            "min_quote_volume_usdt": 1_000_000,
            "min_taker_buy_sell_ratio": 1.05,
            "max_signal_bar_range_percent": 10.0,
            "stop_loss_percent": 1.0,
            "take_profit_percent": 2.0,
            "max_hold_bars": 4,
            "cooldown_bars": 1,
            "max_open_positions": 1,
            "taker_fee_rate": 0.0004,
            "slippage_bps": 5.0,
        }
        values.update(overrides)
        return BacktestConfig(**values)

    def test_completed_bar_signal_enters_next_open_and_takes_profit(self):
        bars = [
            bar(0, open_price=100, high=100.5, low=99.8, close=100.2),
            bar(1, open_price=100.2, high=101.0, low=100.0, close=100.8),
            bar(2, open_price=100.8, high=102.0, low=100.6, close=101.5),
            bar(3, open_price=101.5, high=103.8, low=101.0, close=103.2),
            bar(4, open_price=103.2, high=103.4, low=102.5, close=103.0),
        ]

        result = run_hot_momentum_backtest({"BTCUSDT": bars}, self.config())

        self.assertEqual(result.trade_count, 1)
        trade = result.trades[0]
        self.assertEqual(trade.entry_time, bars[3].open_time_iso)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertGreater(trade.net_pnl_usdt, 0)
        self.assertIn("lookback_momentum", trade.reason_codes)
        self.assertGreater(result.fees_usdt, 0)
        self.assertGreater(result.slippage_usdt, 0)

    def test_same_bar_stop_and_target_collision_takes_stop_first(self):
        bars = [
            bar(0, open_price=100, high=100.5, low=99.8, close=100.2),
            bar(1, open_price=100.2, high=101.0, low=100.0, close=100.8),
            bar(2, open_price=100.8, high=102.0, low=100.6, close=101.5),
            bar(3, open_price=101.5, high=104.0, low=99.0, close=103.2),
        ]

        result = run_hot_momentum_backtest({"BTCUSDT": bars}, self.config())

        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0].exit_reason, "stop_loss")
        self.assertLess(result.trades[0].net_pnl_usdt, 0)

    def test_weak_liquidity_and_taker_flow_rejects_signal(self):
        bars = [
            bar(0, open_price=100, high=100.5, low=99.8, close=100.2, quote_volume=50_000, taker_ratio=0.9),
            bar(1, open_price=100.2, high=101.0, low=100.0, close=100.8, quote_volume=50_000, taker_ratio=0.9),
            bar(2, open_price=100.8, high=102.0, low=100.6, close=101.5, quote_volume=50_000, taker_ratio=0.9),
            bar(3, open_price=101.5, high=103.8, low=101.0, close=103.2, quote_volume=50_000, taker_ratio=0.9),
        ]

        result = run_hot_momentum_backtest({"BTCUSDT": bars}, self.config())

        self.assertEqual(result.trade_count, 0)
        self.assertGreater(result.rejected_signals, 0)

    def test_staged_sweep_reports_variant_aggregates(self):
        bars = []
        price = 100.0
        for index in range(16):
            close = price * 1.01
            bars.append(
                bar(
                    index,
                    open_price=price,
                    high=close * 1.025,
                    low=price * 0.998,
                    close=close,
                    quote_volume=2_000_000,
                    taker_ratio=1.2,
                )
            )
            price = close

        payload = run_staged_sweep(
            {"BTCUSDT": bars},
            window_bars=8,
            step_bars=4,
            variants=["balanced", "aggressive"],
        )

        self.assertEqual(payload["schema"], "bfa_staged_backtest_sweep_v1")
        self.assertEqual(payload["window_count"], 3)
        self.assertIn("balanced", payload["aggregate"])
        self.assertIn(payload["interpretation"]["balanced"], {"insufficient_trades", "candidate_for_forward_paper"})
        self.assertIn("max_daily_loss_usdt", payload["aggregate"]["balanced"])

    def test_daily_loss_gate_counts_only_realized_exits(self):
        def series(symbol):
            return [
                symbol_bar(symbol, 0, open_price=100, high=100.5, low=99.8, close=100.2),
                symbol_bar(symbol, 1, open_price=100.2, high=101.0, low=100.0, close=100.8),
                symbol_bar(symbol, 2, open_price=100.8, high=102.0, low=100.6, close=101.5),
                symbol_bar(symbol, 3, open_price=101.5, high=101.7, low=100.0, close=100.5),
                symbol_bar(symbol, 4, open_price=100.5, high=102.0, low=99.0, close=101.4),
                symbol_bar(symbol, 5, open_price=101.4, high=104.2, low=101.0, close=104.0),
                symbol_bar(symbol, 6, open_price=104.0, high=106.0, low=103.0, close=105.0),
            ]

        result = run_hot_momentum_backtest(
            {"AAAUSDT": series("AAAUSDT"), "BBBUSDT": series("BBBUSDT")},
            self.config(max_open_positions=2, max_daily_loss_usdt=0.01, cooldown_bars=0),
        )

        self.assertEqual(result.trade_count, 2)
        self.assertGreater(result.skipped_daily_loss_signals, 0)
        self.assertTrue(all(trade.exit_reason == "stop_loss" for trade in result.trades))


if __name__ == "__main__":
    unittest.main()
