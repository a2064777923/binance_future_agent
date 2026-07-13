import csv
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import bfa.backtest.near_bbo_replay as replay_module
from bfa.backtest.near_bbo_replay import (
    NearBboReplayTick,
    NearBboReplayConfig,
    ReplayWindow,
    SyntheticBboVariant,
    aggregate_variant_reports,
    available_symbols,
    default_variants,
    fill_audit_variants,
    iter_merged_ticks,
    load_eligibility_schedule,
    select_symbols_for_window,
    synthetic_bbo,
    utc_ms,
)
from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse
from bfa.strategy.near_bbo_regime import NearBboRegimeTracker


def write_archive(root: Path, symbol: str, day: str, rows: list[list[str]]) -> None:
    directory = root / symbol
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{symbol}-aggTrades-{day}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open(f"{symbol}-aggTrades-{day}.csv", "w") as raw:
            # TextIOWrapper must be kept alive until all rows are flushed.
            import io

            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            writer = csv.writer(text)
            writer.writerow(
                [
                    "agg_trade_id",
                    "price",
                    "quantity",
                    "first_trade_id",
                    "last_trade_id",
                    "transact_time",
                    "is_buyer_maker",
                ]
            )
            writer.writerows(rows)
            text.flush()
            text.detach()


class NearBboReplayTests(unittest.TestCase):
    def test_fill_audit_defaults_use_twenty_second_contract_and_explicit_envelope(self):
        config = NearBboReplayConfig()
        variants = {variant.name: variant for variant in fill_audit_variants()}

        self.assertEqual(config.quote_ttl_ms, 20_000)
        self.assertGreaterEqual(config.post_window_ms, config.quote_ttl_ms + config.max_hold_ms)
        self.assertEqual(variants["touch_upper_bound"].queue_fill_mode, "touch")
        self.assertEqual(
            variants["queue_1pct"].queue_fill_mode,
            "price_through_or_volume_ahead",
        )
        self.assertEqual(
            variants["queue_10pct"].queue_fill_mode,
            "price_through_or_volume_ahead",
        )
        self.assertEqual(
            variants["displayed_queue"].queue_fill_mode,
            "price_through_or_volume_ahead",
        )
        self.assertEqual(variants["queue_1pct"].queue_ahead_fraction, 0.01)
        self.assertEqual(variants["queue_10pct"].queue_ahead_fraction, 0.10)
        self.assertEqual(variants["displayed_queue"].queue_ahead_fraction, 1.0)
        self.assertTrue(
            all(variant.quote_anchor_mode == "aggressor_side" for variant in variants.values())
        )

    def test_fill_envelope_changes_only_shadow_fill_assumption(self):
        config = NearBboReplayConfig()
        runtimes = {
            variant.name: replay_module._build_runtime(variant, config)
            for variant in fill_audit_variants()
        }

        self.assertEqual(
            {runtime.universe.config.queue_ahead_fraction for runtime in runtimes.values()},
            {1.0},
        )
        self.assertEqual(
            {
                name: runtime.ledger.config.queue_ahead_fraction
                for name, runtime in runtimes.items()
            },
            {
                "touch_upper_bound": 1.0,
                "queue_1pct": 0.01,
                "queue_10pct": 0.10,
                "displayed_queue": 1.0,
            },
        )

    def test_synthetic_bbo_has_declared_spread_and_flow_imbalance(self):
        spec = SyntheticBboVariant(
            name="test",
            spread_bps=4.0,
            combined_top_notional_usdt=10_000.0,
            imbalance_scale=0.5,
        )
        bid, bid_qty, ask, ask_qty = synthetic_bbo(100.0, flow_signed=1.0, spec=spec)
        self.assertAlmostEqual((ask - bid) / 100.0 * 10_000.0, 4.0)
        self.assertGreater(bid_qty, ask_qty)
        self.assertAlmostEqual((bid_qty + ask_qty) * 100.0, 10_000.0)

    def test_causal_price_grid_waits_for_two_changes_and_infers_gcd_tick(self):
        grid = replay_module._CausalPriceGrid()

        grid.ingest(100.00)
        grid.ingest(100.02)
        self.assertIsNone(grid.tick_size)
        grid.ingest(100.03)

        self.assertEqual(grid.tick_size, 0.01)

    def test_synthetic_bbo_quantizes_passive_sides_to_inferred_tick(self):
        spec = SyntheticBboVariant(
            name="quantized",
            spread_bps=2.5,
            combined_top_notional_usdt=10_000.0,
            imbalance_scale=0.0,
            quote_anchor_mode="aggressor_side",
        )

        buy_bid, _buy_bid_qty, buy_ask, _buy_ask_qty = synthetic_bbo(
            100.0,
            flow_signed=0.0,
            spec=spec,
            last_taker_buy=True,
            tick_size=0.1,
        )
        sell_bid, _sell_bid_qty, sell_ask, _sell_ask_qty = synthetic_bbo(
            100.0,
            flow_signed=0.0,
            spec=spec,
            last_taker_buy=False,
            tick_size=0.1,
        )

        self.assertEqual((buy_bid, buy_ask), (99.9, 100.0))
        self.assertEqual((sell_bid, sell_ask), (100.0, 100.1))

    def test_aggressor_side_anchor_places_buy_trade_at_ask_and_sell_trade_at_bid(self):
        spec = SyntheticBboVariant(
            name="anchored",
            spread_bps=2.5,
            combined_top_notional_usdt=10_000.0,
            imbalance_scale=0.0,
            quote_anchor_mode="aggressor_side",
        )

        buy_bid, _buy_bid_qty, buy_ask, _buy_ask_qty = synthetic_bbo(
            100.0,
            flow_signed=0.0,
            spec=spec,
            last_taker_buy=True,
        )
        sell_bid, _sell_bid_qty, sell_ask, _sell_ask_qty = synthetic_bbo(
            100.0,
            flow_signed=0.0,
            spec=spec,
            last_taker_buy=False,
        )

        self.assertEqual(buy_ask, 100.0)
        self.assertLess(buy_bid, buy_ask)
        self.assertEqual(sell_bid, 100.0)
        self.assertGreater(sell_ask, sell_bid)

    def test_aggressor_anchor_requires_last_trade_side(self):
        spec = SyntheticBboVariant(name="anchored", quote_anchor_mode="aggressor_side")
        with self.assertRaisesRegex(ValueError, "last_taker_buy"):
            synthetic_bbo(100.0, flow_signed=0.0, spec=spec)

    def test_fill_variant_rejects_queue_fraction_above_displayed_depth(self):
        with self.assertRaisesRegex(ValueError, "queue_ahead_fraction"):
            SyntheticBboVariant(name="invalid", queue_ahead_fraction=1.01)

    def test_merged_stream_is_chronological_and_decodes_aggressor_side(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_archive(
                root,
                "AAAUSDT",
                "2026-07-05",
                [
                    ["1", "10", "2", "1", "1", "1783209600002", "false"],
                    ["2", "10.1", "1", "2", "2", "1783209600004", "true"],
                ],
            )
            write_archive(
                root,
                "BBBUSDT",
                "2026-07-05",
                [["3", "20", "1", "3", "3", "1783209600003", "false"]],
            )
            ticks = list(
                iter_merged_ticks(
                    root,
                    ["AAAUSDT", "BBBUSDT"],
                    start_ms=1783209600000,
                    end_ms=1783209600010,
                )
            )
            self.assertEqual([tick.symbol for tick in ticks], ["AAAUSDT", "BBBUSDT", "AAAUSDT"])
            self.assertEqual([tick.taker_buy for tick in ticks], [True, True, False])

    def test_symbol_selection_is_intersection_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [["1", "1", "1", "1", "1", "1783209600000", "false"]]
            for symbol in ("AAAUSDT", "BBBUSDT", "CCUSDT"):
                write_archive(root, symbol, "2026-07-05", rows)
            write_archive(root, "AAAUSDT", "2026-07-06", rows)
            write_archive(root, "BBBUSDT", "2026-07-06", rows)
            self.assertEqual(
                available_symbols(root, [date(2026, 7, 5), date(2026, 7, 6)]),
                ("AAAUSDT", "BBBUSDT"),
            )
            window = ReplayWindow("fixed", utc_ms("2026-07-05T00:00:00Z"), utc_ms("2026-07-05T00:05:00Z"))
            first = select_symbols_for_window(root, window, limit=2, warmup_ms=0, post_window_ms=0)
            second = select_symbols_for_window(root, window, limit=2, warmup_ms=0, post_window_ms=0)
            self.assertEqual(first, second)

    def test_schedule_loader_uses_exclusive_hour_boundaries(self):
        payload = {
            "eligibility_schedule": {
                "schema": "bfa_micro_grid_eligibility_schedule_v2",
                "windows": [
                    {
                        "signal_start": "2026-07-05T12:00:00+00:00",
                        "signal_end": "2026-07-05T12:59:59.999000+00:00",
                        "symbols": ["AAAUSDT", "BBBUSDT"],
                    },
                    {
                        "signal_start": "2026-07-05T13:00:00+00:00",
                        "signal_end": "2026-07-05T13:59:59.999000+00:00",
                        "symbols": ["CCUSDT"],
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            schedule = load_eligibility_schedule([path])

        self.assertEqual(
            schedule.symbols_at(utc_ms("2026-07-05T12:59:59.999Z")),
            frozenset({"AAAUSDT", "BBBUSDT"}),
        )
        self.assertEqual(
            schedule.symbols_at(utc_ms("2026-07-05T13:00:00Z")),
            frozenset({"CCUSDT"}),
        )
        self.assertEqual(
            schedule.symbols_for_range(
                utc_ms("2026-07-05T12:30:00Z"),
                utc_ms("2026-07-05T13:30:00Z"),
            ),
            frozenset({"AAAUSDT", "BBBUSDT", "CCUSDT"}),
        )

    def test_summary_ingestion_preserves_second_and_event_counts(self):
        config = NearBboConfig(min_trade_events=1, min_top_notional_usdt=1.0)
        raw = NearBboUniverse(config)
        summarized = NearBboUniverse(config)
        events = [
            (1_000, 100.0, 2.0, True),
            (1_200, 100.1, 1.0, False),
            (1_900, 99.9, 3.0, True),
            (2_100, 100.2, 1.0, False),
        ]
        for event_time, price, quantity, taker_buy in events:
            raw.ingest_trade(
                symbol="TESTUSDT",
                event_time_ms=event_time,
                price=price,
                quantity=quantity,
                taker_buy=taker_buy,
            )
        self.assertTrue(
            summarized.ingest_trade_summary(
                symbol="TESTUSDT",
                event_time_ms=1_900,
                first_price=100.0,
                last_price=99.9,
                high_price=100.1,
                low_price=99.9,
                taker_buy_quantity=5.0,
                taker_sell_quantity=1.0,
                quote_volume=599.8,
                taker_buy_quote=499.7,
                trade_count=3,
            )
        )
        self.assertTrue(
            summarized.ingest_trade_summary(
                symbol="TESTUSDT",
                event_time_ms=2_100,
                first_price=100.2,
                last_price=100.2,
                high_price=100.2,
                low_price=100.2,
                taker_buy_quantity=0.0,
                taker_sell_quantity=1.0,
                quote_volume=100.2,
                taker_buy_quote=0.0,
                trade_count=1,
            )
        )
        self.assertEqual(raw.symbol_diagnostics("TESTUSDT"), summarized.symbol_diagnostics("TESTUSDT"))

    def test_regime_summary_matches_raw_minute_features(self):
        raw = NearBboRegimeTracker()
        summarized = NearBboRegimeTracker()
        for minute in range(16):
            base = 100.0 + minute * 0.05
            event_time = minute * 60_000 + 1_000
            raw.ingest_trade(
                event_time_ms=event_time,
                price=base,
                quantity=2.0,
                taker_buy=True,
            )
            raw.ingest_trade(
                event_time_ms=event_time + 500,
                price=base + 0.02,
                quantity=1.0,
                taker_buy=False,
            )
            summarized.ingest_trade_summary(
                event_time_ms=event_time + 500,
                first_price=base,
                last_price=base + 0.02,
                high_price=base + 0.02,
                low_price=base,
                quote_volume=base * 2.0 + (base + 0.02),
                taker_buy_quote=base * 2.0,
                trade_count=2,
            )
        raw_snapshot = raw.snapshot(now_ms=16 * 60_000)
        summarized_snapshot = summarized.snapshot(now_ms=16 * 60_000)
        self.assertEqual(raw_snapshot.label, summarized_snapshot.label)
        self.assertEqual(raw_snapshot.bar_count, summarized_snapshot.bar_count)
        self.assertAlmostEqual(raw_snapshot.range_position, summarized_snapshot.range_position)
        self.assertAlmostEqual(raw_snapshot.momentum_percent, summarized_snapshot.momentum_percent)
        self.assertEqual(raw_snapshot.feature_payload, summarized_snapshot.feature_payload)

    def test_aggregate_keeps_positive_window_rate_and_capacity_metrics(self):
        outcome = {
            "proposal_id": "p1",
            "symbol": "AAAUSDT",
            "lane": "range_reversion",
            "regime": "RANGE",
            "exit_time_ms": 3,
            "net_pnl_usdt": 1.0,
            "mfe_bps": 2.0,
            "mae_bps": -1.0,
            "exit_reason": "take_profit",
        }
        report = {
            "synthetic_bbo": {"name": "baseline"},
            "symbols": ["AAAUSDT"],
            "window": {"name": "one", "duration_hours": 1.0},
            "outcomes": [outcome],
            "metrics": {
                "net_pnl_usdt": 1.0,
                "admitted_count": 1,
                "capacity_rejected_count": 2,
                "expired_count": 0,
                "filled_count": 1,
                "closed_count": 1,
                "wins": 1,
                "losses": 0,
                "raw_tick_count": 10,
                "evaluation_count": 10,
            },
        }
        aggregate = aggregate_variant_reports([{"variants": {"baseline": report}}])
        metrics = aggregate["baseline"]["metrics"]
        self.assertEqual(metrics["positive_window_count"], 1)
        self.assertEqual(metrics["capacity_rejected_count"], 2)
        self.assertEqual(metrics["filled_count"], 1)
        self.assertEqual(metrics["positive_window_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
