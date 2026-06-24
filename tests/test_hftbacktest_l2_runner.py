import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_hftbacktest_l2_micro_grid.py"
SPEC = importlib.util.spec_from_file_location("hftbacktest_l2_micro_grid", SCRIPT_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class HftBacktestL2RunnerTests(unittest.TestCase):
    def test_grid_config_from_args_converts_ms_to_ns(self):
        args = SimpleNamespace(
            tick_size=0.001,
            lot_size=1.0,
            notional_usdt=20.0,
            quote_offset_ticks=2,
            max_position_qty=5.0,
            grid_refresh_ms=750,
            step_ms=25,
            max_steps=100,
            maker_fee_bps=2.0,
            taker_fee_bps=4.0,
            order_latency_ms=3.5,
        )

        config = runner.grid_config_from_args(args)

        self.assertEqual(config.grid_refresh_ns, 750_000_000)
        self.assertEqual(config.step_ns, 25_000_000)
        self.assertEqual(config.order_latency_ns, 3_500_000)
        self.assertEqual(config.max_position_qty, 5.0)

    def test_public_probe_schema_marks_bookdepth_as_not_l2(self):
        original_fetch = runner.fetch_binance_public_archive
        original_summary = runner.summarize_public_book_depth_archive

        class FakeSummary:
            def to_dict(self):
                return {
                    "data_quality": "aggregated_depth_percent_bands",
                    "is_l2_order_book": False,
                    "warning": "not tick-by-tick L2",
                }

        def fake_fetch(market, symbol, day, cache_dir):
            return SimpleNamespace(
                market=market,
                symbol=symbol,
                day=day,
                path=Path("runtime") / f"{symbol}-{market}-{day}.zip",
                url=f"https://example.test/{market}",
                size_bytes=123,
            )

        try:
            runner.fetch_binance_public_archive = fake_fetch
            runner.summarize_public_book_depth_archive = lambda symbol, day, path: FakeSummary()

            payload = runner.run_public_probe(
                SimpleNamespace(
                    symbol="nearusdt",
                    date=date(2026, 5, 23).isoformat(),
                    cache_dir="runtime/test-cache",
                )
            )
        finally:
            runner.fetch_binance_public_archive = original_fetch
            runner.summarize_public_book_depth_archive = original_summary

        self.assertEqual(payload["schema"], "bfa_hft_public_archive_probe_v1")
        self.assertFalse(payload["data_quality"]["hftbacktest_l2_ready"])
        self.assertIn("aggregated", payload["data_quality"]["blocker"])


if __name__ == "__main__":
    unittest.main()
