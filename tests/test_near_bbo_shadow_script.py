import importlib.util
import json
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_near_bbo_shadow.py"
SPEC = importlib.util.spec_from_file_location("run_near_bbo_shadow", SCRIPT_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class FakeUniverse:
    def __init__(self):
        self.books = []
        self.trades = []

    def ingest_book_ticker(self, **values):
        self.books.append(values)
        return True

    def ingest_trade(self, **values):
        self.trades.append(values)
        return True


class FakeLedger:
    def __init__(self):
        self.trades = []

    def on_trade(self, **values):
        self.trades.append(values)
        return ()


class NearBboShadowScriptTests(unittest.TestCase):
    def test_build_streams_uses_public_book_ticker_and_trade_only(self):
        streams = runner.build_streams(["BTCUSDT", "ETHUSDT"])

        self.assertEqual(
            streams,
            (
                "btcusdt@bookTicker",
                "btcusdt@trade",
                "ethusdt@bookTicker",
                "ethusdt@trade",
            ),
        )
        self.assertFalse(any("depth" in stream.lower() for stream in streams))

    def test_ingest_message_dispatches_book_ticker_without_order_side_effect(self):
        universe = FakeUniverse()
        ledger = FakeLedger()
        payload = {
            "stream": "btcusdt@bookTicker",
            "data": {
                "e": "bookTicker",
                "E": 10_000,
                "s": "BTCUSDT",
                "b": "100.0",
                "B": "2.0",
                "a": "100.1",
                "A": "3.0",
            },
        }

        result = runner.ingest_public_message(json.dumps(payload), universe=universe, ledger=ledger)

        self.assertEqual(result["event_type"], "bookTicker")
        self.assertEqual(len(universe.books), 1)
        self.assertEqual(ledger.trades, [])

    def test_ingest_message_uses_binance_buyer_maker_flag_for_taker_side(self):
        universe = FakeUniverse()
        ledger = FakeLedger()
        payload = {
            "stream": "btcusdt@trade",
            "data": {
                "e": "trade",
                "T": 10_100,
                "s": "BTCUSDT",
                "p": "100.0",
                "q": "4.0",
                "m": True,
            },
        }

        result = runner.ingest_public_message(payload, universe=universe, ledger=ledger)

        self.assertEqual(result["event_type"], "trade")
        self.assertFalse(universe.trades[0]["taker_buy"])
        self.assertFalse(ledger.trades[0]["taker_buy"])

    def test_symbol_parser_deduplicates_and_caps_broad_watch_universe(self):
        symbols = runner.parse_symbols("btcusdt,ethusdt,BTCUSDT", max_symbols=80)

        self.assertEqual(symbols, ("BTCUSDT", "ETHUSDT"))
        with self.assertRaises(ValueError):
            runner.parse_symbols(",".join(f"S{i}USDT" for i in range(81)), max_symbols=80)

    def test_evaluation_clock_advances_during_silent_stream(self):
        self.assertEqual(
            runner.evaluation_time_ms(latest_event_ms=10_000, wall_time_ms=12_500),
            12_500,
        )

    def test_evaluation_clock_tolerates_local_clock_behind_exchange(self):
        self.assertEqual(
            runner.evaluation_time_ms(latest_event_ms=10_100, wall_time_ms=10_000),
            10_100,
        )


if __name__ == "__main__":
    unittest.main()
