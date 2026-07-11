import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from bfa.backtest.models import BacktestBar


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = load_script("micro_grid_market_scan", "run_micro_grid_market_scan.py")
research = load_script("micro_grid_research_schedule", "run_micro_grid_research.py")


BASE_MS = int(datetime(2026, 7, 5, tzinfo=UTC).timestamp() * 1000)


def minute_bars(symbol, *, ranging, count=360):
    bars = []
    previous = 100.0
    for index in range(count):
        if ranging:
            close = 100.0 + (0.75 if index % 2 else -0.75)
            wick = 0.35
            taker_fraction = 0.56 if index % 2 else 0.44
        else:
            close = 100.0 + index * 0.025
            wick = 0.03
            taker_fraction = 0.58
        open_price = previous
        quote_volume = 20_000.0
        open_time = BASE_MS + index * 60_000
        bars.append(
            BacktestBar(
                symbol=symbol,
                open_time=open_time,
                open=open_price,
                high=max(open_price, close) + wick,
                low=min(open_price, close) - wick,
                close=close,
                volume=1_000.0,
                close_time=open_time + 59_999,
                quote_volume=quote_volume,
                taker_buy_quote_volume=quote_volume * taker_fraction,
            )
        )
        previous = close
    return bars


def second_bars(count=200):
    return [
        BacktestBar(
            symbol="AAAUSDT",
            open_time=BASE_MS + index * 1_000,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1.0,
            close_time=BASE_MS + index * 1_000 + 999,
            quote_volume=100.0,
            taker_buy_quote_volume=50.0,
        )
        for index in range(count)
    ]


class MicroGridMarketScanTests(unittest.TestCase):
    def test_universe_uses_exchange_metadata_and_excludes_tradfi(self):
        payload = {
            "symbols": [
                {
                    "symbol": "AAAUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "underlyingType": "COIN",
                    "underlyingSubType": [],
                    "onboardDate": BASE_MS,
                },
                {
                    "symbol": "STOCKUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "underlyingType": "EQUITY",
                    "underlyingSubType": ["TRADFI"],
                },
                {
                    "symbol": "BBBUSD",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USD",
                    "marginAsset": "USD",
                    "underlyingType": "COIN",
                },
            ]
        }

        universe, diagnostics = scan.resolve_universe(payload)

        self.assertEqual([item.symbol for item in universe], ["AAAUSDT"])
        self.assertEqual(diagnostics["eligible_symbol_count"], 1)
        self.assertIn("underlying_not_coin", diagnostics["exclusion_counts"])

    def test_archive_url_percent_encodes_non_ascii_symbols(self):
        url = scan.kline_archive_url("龍蝦USDT", "5m", "龍蝦USDT-5m-2026-07-05.zip")

        self.assertNotIn("龍蝦", url)
        self.assertIn("%E9%BE%8D%E8%9D%A6USDT", url)

    def test_symbol_job_does_not_fetch_archives_before_six_hour_history_exists(self):
        config = scan.MarketScanConfig()
        windows = scan.build_scan_windows([date(2026, 7, 5)], config)
        meta = scan.SymbolMeta(symbol="FUTUREUSDT", onboard_time_ms=windows[-1].signal_end_ms + 1)

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(scan, "fetch_daily_kline_zip") as fetch:
            result = scan.scan_symbol_windows(
                meta,
                windows,
                interval="5m",
                config=config,
                cache_dir=Path(temp_dir),
            )

        fetch.assert_not_called()
        self.assertEqual(result["features"], {})
        self.assertEqual(result["io"]["missing_archives"], 0)

    def test_prior_only_features_prefer_oscillating_wicks_over_clean_trend(self):
        config = scan.MarketScanConfig(min_lookback_quote_volume_usdt=1.0)
        window = scan.ScanWindow(
            signal_start_ms=BASE_MS + 360 * 60_000,
            signal_end_ms=BASE_MS + 420 * 60_000 - 1,
            feature_start_ms=BASE_MS,
            feature_end_ms=BASE_MS + 360 * 60_000 - 1,
        )
        ranging = minute_bars("RANGEUSDT", ranging=True)
        trend = minute_bars("TRENDUSDT", ranging=False)

        range_features = scan.opportunity_features(
            "RANGEUSDT",
            ranging,
            [bar.open_time for bar in ranging],
            window,
            interval_minutes=1,
            config=config,
        )
        trend_features = scan.opportunity_features(
            "TRENDUSDT",
            trend,
            [bar.open_time for bar in trend],
            window,
            interval_minutes=1,
            config=config,
        )

        self.assertIsNotNone(range_features)
        self.assertIsNotNone(trend_features)
        self.assertGreater(range_features["raw_components"]["oscillation"], trend_features["raw_components"]["oscillation"])
        self.assertGreater(range_features["raw_components"]["wick_quality"], trend_features["raw_components"]["wick_quality"])
        self.assertGreater(range_features["raw_components"]["mean_reversion"], trend_features["raw_components"]["mean_reversion"])
        self.assertLess(research.parse_iso_ms(range_features["feature_end"]), research.parse_iso_ms(range_features["signal_start"]))

    def test_cross_sectional_rank_uses_fixed_component_weights(self):
        low = {"symbol": "LOWUSDT", "raw_components": {key: 0.0 for key in scan.COMPONENT_WEIGHTS}}
        high = {"symbol": "HIGHUSDT", "raw_components": {key: 1.0 for key in scan.COMPONENT_WEIGHTS}}

        ranked = scan.rank_feature_windows({BASE_MS: [low, high]}, top_n=1)

        self.assertEqual(ranked[BASE_MS]["selected"][0]["symbol"], "HIGHUSDT")
        self.assertAlmostEqual(ranked[BASE_MS]["selected"][0]["opportunity_score"], 1.0)

    def test_schedule_loader_filters_dates_and_keeps_absent_symbols_ineligible(self):
        payload = {
            "eligibility_schedule": {
                "schema": "bfa_micro_grid_eligibility_schedule_v1",
                "windows": [
                    {
                        "signal_start": "2026-07-05T00:00:00+00:00",
                        "signal_end": "2026-07-05T00:59:59.999000+00:00",
                        "symbols": ["AAAUSDT"],
                    },
                    {
                        "signal_start": "2026-07-08T00:00:00+00:00",
                        "signal_end": "2026-07-08T00:59:59.999000+00:00",
                        "symbols": ["AAAUSDT", "OUTSIDEUSDT"],
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schedule.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            intervals, diagnostics = research.load_eligibility_schedule(
                path,
                loaded_start_ms=BASE_MS,
                loaded_end_ms=BASE_MS + 86_400_000 - 1,
                requested_symbols={"AAAUSDT", "BBBUSDT"},
            )

        self.assertEqual(len(intervals["AAAUSDT"]), 1)
        self.assertEqual(intervals["BBBUSDT"], [])
        self.assertEqual(diagnostics["outside_loaded_window_rows"], 1)
        self.assertEqual(diagnostics["eligible_requested_symbol_count"], 1)

    def test_interval_iterator_preserves_global_stride_and_skips_gaps(self):
        bars = second_bars()

        indexes = list(
            research.iter_signal_indexes(
                bars,
                80,
                180,
                stride=3,
                signal_intervals_ms=[
                    (BASE_MS + 91_000, BASE_MS + 100_000),
                    (BASE_MS + 150_000, BASE_MS + 156_000),
                ],
            )
        )

        self.assertEqual(indexes, [92, 95, 98, 152, 155])
        self.assertTrue(all((index - 80) % 3 == 0 for index in indexes))

    def test_midnight_schedule_loads_only_required_prior_day_warmup(self):
        profile = research.MicroGridProfile(
            structure_lookback_seconds=600,
            wick_training_seconds=900,
            spike_depth_lookback_seconds=300,
        )

        midnight = research.history_start_date_for_intervals(
            date(2026, 7, 5),
            [(BASE_MS, BASE_MS + 3_599_999)],
            profile,
        )
        later = research.history_start_date_for_intervals(
            date(2026, 7, 5),
            [(BASE_MS + 3_600_000, BASE_MS + 7_199_999)],
            profile,
        )

        self.assertEqual(midnight, date(2026, 7, 4))
        self.assertEqual(later, date(2026, 7, 5))

    def test_scan_windows_cover_only_requested_dates(self):
        config = scan.MarketScanConfig(selection_interval_minutes=60, signal_window_minutes=60)

        windows = scan.build_scan_windows([date(2026, 7, 5), date(2026, 7, 8)], config)

        self.assertEqual(len(windows), 48)
        self.assertEqual({scan.ms_to_date(item.signal_start_ms) for item in windows}, {date(2026, 7, 5), date(2026, 7, 8)})
        self.assertTrue(all(item.feature_end_ms < item.signal_start_ms for item in windows))


if __name__ == "__main__":
    unittest.main()
