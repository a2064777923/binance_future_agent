import importlib.util
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from bfa.backtest.models import BacktestBar, BacktestConfig


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_second_agg_compound_backtest.py"
SPEC = importlib.util.spec_from_file_location("second_agg_compound_backtest", SCRIPT_PATH)
second_bt = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(second_bt)


class SecondAggCompoundBacktestScriptTests(unittest.TestCase):
    def config(self):
        return BacktestConfig(
            account_capital_usdt=30,
            max_position_notional_usdt=10,
            max_risk_per_trade_usdt=0.2,
            max_daily_loss_usdt=5,
            max_open_positions=1,
            max_hold_bars=1,
            taker_fee_rate=0.0,
            slippage_bps=0.0,
            trailing_stop_enabled=False,
        )

    def setup(self, *, exit_policy):
        return SimpleNamespace(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            notional_usdt=10.0,
            hold_time_minutes=1,
            price_basis={
                "entry_basis": {"order_type": "market"},
                "exit_policy": exit_policy,
                "vwap": 101.0,
            },
        )

    def bar(self, index, *, open_price=100.0, high=100.1, low=99.9, close=100.0, buy_quote=50.0):
        open_time = index * 1_000
        return BacktestBar(
            symbol="BTCUSDT",
            open_time=open_time,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1.0,
            close_time=open_time + 999,
            quote_volume=100.0,
            taker_buy_quote_volume=buy_quote,
        )

    def test_no_time_exit_holds_until_data_end_when_no_stop_or_target_hits(self):
        seconds = [
            self.bar(0, close=100.0),
            self.bar(1, close=100.2),
            self.bar(2, close=99.8),
        ]

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(exit_policy={"time_exit_enabled": False}),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "data_end")
        self.assertEqual(trade.exit_time, seconds[-1].close_time_iso)

    def test_early_invalid_exit_closes_when_price_flow_and_vwap_do_not_follow(self):
        seconds = [
            self.bar(0, high=100.0, low=99.85, close=99.9, buy_quote=20.0),
            self.bar(1, high=99.95, low=99.7, close=99.8, buy_quote=20.0),
            self.bar(2, high=99.9, low=99.6, close=99.65, buy_quote=20.0),
            self.bar(3, high=99.85, low=99.55, close=99.7, buy_quote=20.0),
        ]

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(
                exit_policy={
                    "time_exit_enabled": True,
                    "early_exit_enabled": True,
                    "early_exit_min_seconds": 3,
                    "early_exit_min_favorable_r": 0.25,
                    "early_exit_max_adverse_r": 0.1,
                    "early_exit_min_adverse_votes": 2,
                    "early_exit_flow_edge": 0.02,
                }
            ),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "early_invalid_exit")
        self.assertEqual(trade.exit_time, seconds[2].close_time_iso)

    def test_conditional_time_exit_keeps_profitable_trade_running(self):
        seconds = [self.bar(index, high=100.3, low=99.9, close=100.2) for index in range(65)]
        seconds.append(self.bar(65, high=104.2, low=100.1, close=104.0))

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(
                exit_policy={
                    "time_exit_enabled": True,
                    "time_exit_only_when_not_profitable": True,
                }
            ),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertEqual(trade.exit_time, seconds[65].close_time_iso)

    def test_conditional_time_exit_closes_non_profitable_trade_at_deadline(self):
        seconds = [self.bar(index, high=100.1, low=99.8, close=99.95) for index in range(65)]

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(
                exit_policy={
                    "time_exit_enabled": True,
                    "time_exit_only_when_not_profitable": True,
                }
            ),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "time_exit")
        self.assertEqual(trade.exit_time, seconds[59].close_time_iso)

    def test_stop_loss_reason_codes_mark_wrong_direction_when_price_continues(self):
        seconds = [
            self.bar(0, high=100.1, low=99.9, close=100.0),
            self.bar(1, high=99.9, low=97.9, close=98.0),
            self.bar(2, high=98.0, low=96.7, close=97.0),
            self.bar(3, high=97.1, low=96.4, close=96.6),
        ]

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(exit_policy={"time_exit_enabled": True}),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertIn("post_stop_path:wrong_direction", trade.reason_codes)

    def test_stop_loss_reason_codes_mark_bad_entry_or_stop_when_price_recovers(self):
        seconds = [
            self.bar(0, high=100.1, low=99.9, close=100.0),
            self.bar(1, high=99.9, low=97.9, close=98.2),
            self.bar(2, high=101.0, low=98.2, close=100.7),
            self.bar(3, high=104.2, low=100.6, close=104.0),
        ]

        trade, status = second_bt.simulate_signal_on_seconds(
            symbol="BTCUSDT",
            signal_entry_time_ms=0,
            setup=self.setup(exit_policy={"time_exit_enabled": True}),
            seconds=seconds,
            config=self.config(),
            reason_codes=["test"],
        )

        self.assertEqual(status, "filled")
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertIn("post_stop_path:bad_entry_or_stop", trade.reason_codes)

    def test_read_aggtrade_zip_skips_malformed_numeric_rows(self):
        path = Path("runtime") / "test-bad-aggtrade.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "TESTUSDT-aggTrades-2026-01-01.csv",
                "\n".join(
                    [
                        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker",
                        "1,100.0,0.5,1,1,1700000000000,false",
                        "2,101.0,tr9344237134,2,2,1700000001000,true",
                        "3,102.0,0.25,3,3,bad_time,false",
                    ]
                ),
            )

        rows = second_bt.read_aggtrade_zip(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 100.0)
        self.assertEqual(rows[0]["quantity"], 0.5)


if __name__ == "__main__":
    unittest.main()
