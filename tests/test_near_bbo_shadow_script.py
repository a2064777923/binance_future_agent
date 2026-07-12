import builtins
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
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
    def test_runner_import_does_not_require_numpy_without_calibration(self):
        original_import = builtins.__import__

        def import_without_numpy(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("numpy intentionally unavailable", name="numpy")
            return original_import(name, *args, **kwargs)

        isolated_spec = importlib.util.spec_from_file_location(
            "run_near_bbo_shadow_without_numpy",
            SCRIPT_PATH,
        )
        isolated_runner = importlib.util.module_from_spec(isolated_spec)
        assert isolated_spec.loader is not None
        sys.modules[isolated_spec.name] = isolated_runner
        cached_calibration = sys.modules.pop("bfa.backtest.near_bbo_calibration", None)
        try:
            with mock.patch("builtins.__import__", side_effect=import_without_numpy):
                isolated_spec.loader.exec_module(isolated_runner)
        finally:
            sys.modules.pop(isolated_spec.name, None)
            if cached_calibration is not None:
                sys.modules["bfa.backtest.near_bbo_calibration"] = cached_calibration

        self.assertIsNone(
            isolated_runner.load_optional_calibrator(None, setup_mode="article_v2")
        )

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

    def test_merge_counts_accumulates_diagnostics_without_rescanning_events(self):
        totals = {"regime_warmup": 24}

        runner.merge_counts(totals, {"regime_warmup": 23, "scout_started": 1})
        runner.merge_counts(totals, {"scout_waiting_confirmation": 2})

        self.assertEqual(
            totals,
            {
                "regime_warmup": 47,
                "scout_started": 1,
                "scout_waiting_confirmation": 2,
            },
        )

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

    def test_optional_calibration_rejects_insufficient_report_and_legacy_mode(self):
        report = {
            "schema": "bfa_near_bbo_calibration_report_v1",
            "status": "insufficient_data",
            "model": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not trained"):
                runner.load_optional_calibrator(str(path), setup_mode="article_v2")
            with self.assertRaisesRegex(ValueError, "article_v2"):
                runner.load_optional_calibrator(str(path), setup_mode="legacy")

        self.assertIsNone(runner.load_optional_calibrator(None, setup_mode="article_v2"))


if __name__ == "__main__":
    unittest.main()
