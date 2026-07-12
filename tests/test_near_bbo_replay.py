import csv
from datetime import date
from pathlib import Path
import tempfile
import unittest
import zipfile

from bfa.backtest.near_bbo_replay import (
    NearBboReplayTick,
    ReplayWindow,
    SyntheticBboVariant,
    aggregate_variant_reports,
    available_symbols,
    default_variants,
    iter_merged_ticks,
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
