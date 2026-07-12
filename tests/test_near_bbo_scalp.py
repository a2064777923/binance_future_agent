import unittest
from types import SimpleNamespace

from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse
from bfa.strategy.near_bbo_regime import NearBboRegimeConfig


class NearBboScalpTests(unittest.TestCase):
    def setUp(self):
        self.config = NearBboConfig(
            observation_window_ms=5_000,
            fast_window_ms=1_000,
            quote_ttl_ms=5_000,
            max_pending_orders=3,
            min_trade_events=5,
            min_top_notional_usdt=100.0,
            min_fill_probability=0.10,
            min_win_probability=0.58,
            min_conditional_net_ev_bps=0.10,
            max_abs_momentum_bps=12.0,
        )

    def favorable_long_universe(
        self,
        *,
        symbol="TESTUSDT",
        now_ms=10_000,
        universe=None,
        config=None,
    ):
        universe = universe or NearBboUniverse(config or self.config)
        universe.ingest_book_ticker(
            symbol=symbol,
            event_time_ms=now_ms,
            bid_price=100.0,
            bid_quantity=10.0,
            ask_price=100.02,
            ask_quantity=2.0,
        )
        trades = [
            (6_000, 99.995, 2.0, False),
            (7_000, 99.997, 2.0, False),
            (8_000, 99.999, 2.0, True),
            (9_100, 100.000, 2.0, False),
            (9_500, 100.001, 3.0, True),
            (9_900, 100.002, 2.0, False),
        ]
        for event_ms, price, quantity, taker_buy in trades:
            universe.ingest_trade(
                symbol=symbol,
                event_time_ms=event_ms,
                price=price,
                quantity=quantity,
                taker_buy=taker_buy,
            )
        return universe

    def test_favorable_recovery_quotes_best_bid_with_positive_fill_weighted_ev(self):
        universe = self.favorable_long_universe()

        proposals, diagnostics = universe.rank_opportunities(now_ms=10_000)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.symbol, "TESTUSDT")
        self.assertEqual(proposal.side, "long")
        self.assertEqual(proposal.entry_price, 100.0)
        self.assertGreater(proposal.fill_probability, 0.10)
        self.assertGreater(proposal.win_probability, 0.58)
        self.assertGreater(proposal.conditional_net_ev_bps, 0.10)
        self.assertGreater(proposal.fill_weighted_ev_bps, 0.0)
        self.assertGreater(proposal.target_price, proposal.entry_price)
        self.assertLess(proposal.stop_price, proposal.entry_price)
        self.assertEqual(diagnostics["selected_count"], 1)

    def test_cost_gate_rejects_apparent_edge_that_is_not_net_profitable(self):
        expensive = NearBboConfig(
            **{
                **self.config.__dict__,
                "maker_entry_fee_bps": 8.0,
                "maker_exit_fee_bps": 8.0,
                "taker_exit_fee_bps": 12.0,
                "exit_slippage_bps": 4.0,
                "min_conditional_net_ev_bps": 2.0,
            }
        )
        universe = self.favorable_long_universe(config=expensive)

        proposals, diagnostics = universe.rank_opportunities(now_ms=10_000)

        self.assertEqual(proposals, [])
        self.assertGreater(diagnostics["rejection_counts"].get("net_ev_below_min", 0), 0)

    def test_stale_book_fails_closed(self):
        universe = self.favorable_long_universe(now_ms=10_000)

        proposals, diagnostics = universe.rank_opportunities(now_ms=12_500)

        self.assertEqual(proposals, [])
        self.assertEqual(diagnostics["rejection_counts"]["stale_book"], 1)

    def test_ranking_watches_many_symbols_but_returns_only_pending_capacity(self):
        universe = NearBboUniverse(self.config)
        for index in range(8):
            symbol = f"S{index}USDT"
            self.favorable_long_universe(symbol=symbol, universe=universe)

        proposals, diagnostics = universe.rank_opportunities(now_ms=10_000)

        self.assertEqual(len(proposals), 3)
        self.assertEqual(diagnostics["watch_symbol_count"], 8)
        self.assertEqual(diagnostics["selected_count"], 3)
        self.assertEqual(diagnostics["pending_capacity"], 3)

    def test_trade_hot_path_aggregates_same_second_in_one_bounded_bucket(self):
        universe = NearBboUniverse(self.config)
        for index in range(1_000):
            universe.ingest_trade(
                symbol="TESTUSDT",
                event_time_ms=9_000 + index % 1_000,
                price=100.0 + index / 1_000_000,
                quantity=0.1,
                taker_buy=index % 2 == 0,
            )

        diagnostics = universe.symbol_diagnostics("TESTUSDT")

        self.assertEqual(diagnostics["trade_bucket_count"], 1)
        self.assertEqual(diagnostics["trade_event_count"], 1_000)

    def test_article_v2_fails_closed_until_multiminute_regime_is_ready(self):
        config = NearBboConfig(
            **{
                **self.config.__dict__,
                "setup_mode": "article_v2",
                "regime_config": NearBboRegimeConfig(
                    history_minutes=16,
                    min_bars=12,
                    fast_ema_span=5,
                    slow_ema_span=12,
                ),
            }
        )
        universe = self.favorable_long_universe(config=config)

        proposals, diagnostics = universe.rank_opportunities(now_ms=10_000)

        self.assertEqual(proposals, [])
        self.assertEqual(diagnostics["rejection_counts"]["regime_warmup"], 1)

    def test_article_v2_requires_persistent_range_reversal_before_proposal(self):
        universe, now_ms = self.article_range_universe()

        first, first_diagnostics = universe.rank_opportunities(now_ms=now_ms)
        self.add_favorable_long_flow(universe, now_ms=now_ms + 3_000, bid_price=99.83)
        second, second_diagnostics = universe.rank_opportunities(now_ms=now_ms + 3_000)

        self.assertEqual(first, [])
        self.assertEqual(first_diagnostics["rejection_counts"]["scout_started"], 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].lane, "range_reversion")
        self.assertEqual(second[0].regime, "RANGE")
        self.assertEqual(second[0].features["score_source"], "article_v2_exploration_uncalibrated")
        self.assertGreaterEqual(second[0].features["scout_age_ms"], 2_000)
        self.assertEqual(second_diagnostics["selected_count"], 1)

    def test_article_v2_blocks_accelerating_breakout_even_when_book_signal_is_strong(self):
        config = self.article_config()
        universe = NearBboUniverse(config)
        prices = [100.0, 100.04, 99.98, 100.03, 99.99, 100.02, 100.0, 100.03, 99.99, 100.02, 100.01, 101.20]
        for index, price in enumerate(prices):
            universe.ingest_trade(
                symbol="TESTUSDT",
                event_time_ms=index * 60_000 + 50_000,
                price=price,
                quantity=1.0,
                taker_buy=index % 2 == 0,
            )
        now_ms = 12 * 60_000
        self.add_favorable_long_flow(universe, now_ms=now_ms, bid_price=101.20)

        proposals, diagnostics = universe.rank_opportunities(now_ms=now_ms)

        self.assertEqual(proposals, [])
        self.assertEqual(diagnostics["rejection_counts"]["regime_breakout"], 1)

    def test_article_v2_exploration_does_not_reuse_uncalibrated_probability_gates(self):
        config = NearBboConfig(
            **{
                **self.article_config().__dict__,
                "min_fill_probability": 0.999,
                "min_win_probability": 0.999,
                "min_conditional_net_ev_bps": 100.0,
            }
        )
        universe, now_ms = self.article_range_universe(config=config)

        first, first_diagnostics = universe.rank_opportunities(now_ms=now_ms)
        self.add_favorable_long_flow(universe, now_ms=now_ms + 3_000, bid_price=99.83)
        proposals, diagnostics = universe.rank_opportunities(now_ms=now_ms + 3_000)

        self.assertEqual(first, [])
        self.assertEqual(first_diagnostics["rejection_counts"]["scout_started"], 1)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            proposals[0].features["score_source"],
            "article_v2_exploration_uncalibrated",
        )
        self.assertEqual(diagnostics["selected_count"], 1)

    def test_calibrated_scores_override_heuristics_after_scout_confirmation(self):
        calibrator = FixedCalibrator(fill=0.82, win=0.93, net_bps=2.75)
        config = NearBboConfig(
            **{
                **self.article_config().__dict__,
                "min_fill_probability": 0.80,
                "min_win_probability": 0.90,
                "min_conditional_net_ev_bps": 2.0,
            }
        )
        universe, now_ms = self.article_range_universe(config=config, calibrator=calibrator)

        first, first_diagnostics = universe.rank_opportunities(now_ms=now_ms)
        self.add_favorable_long_flow(universe, now_ms=now_ms + 3_000, bid_price=99.83)
        proposals, diagnostics = universe.rank_opportunities(now_ms=now_ms + 3_000)

        self.assertEqual(first, [])
        self.assertEqual(first_diagnostics["rejection_counts"]["scout_started"], 1)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertAlmostEqual(proposal.fill_probability, 0.82)
        self.assertAlmostEqual(proposal.win_probability, 0.93)
        self.assertAlmostEqual(proposal.conditional_net_ev_bps, 2.75)
        self.assertAlmostEqual(proposal.fill_weighted_ev_bps, 0.82 * 2.75)
        self.assertEqual(proposal.features["score_source"], "walk_forward_calibrated")
        self.assertIn("heuristic_fill_probability", proposal.features)
        self.assertGreater(calibrator.calls[-1]["features"]["queue_pressure_ratio"], 0.0)
        self.assertEqual(calibrator.calls[-1]["features"]["quote_ttl_seconds"], 5.0)
        self.assertGreater(calibrator.calls[-1]["features"]["queue_ahead_notional_usdt"], 0.0)
        self.assertEqual(calibrator.calls[-1]["lane"], "range_reversion")
        self.assertEqual(diagnostics["selected_count"], 1)

    def test_calibrated_negative_net_expectancy_fails_closed(self):
        calibrator = FixedCalibrator(fill=0.90, win=0.90, net_bps=-0.25)
        universe, now_ms = self.article_range_universe(calibrator=calibrator)

        first, _ = universe.rank_opportunities(now_ms=now_ms)
        self.add_favorable_long_flow(universe, now_ms=now_ms + 3_000, bid_price=99.83)
        proposals, diagnostics = universe.rank_opportunities(now_ms=now_ms + 3_000)

        self.assertEqual(first, [])
        self.assertEqual(proposals, [])
        self.assertEqual(diagnostics["rejection_counts"]["calibrated_net_ev_below_min"], 1)

    def article_range_universe(self, *, config=None, calibrator=None):
        universe = NearBboUniverse(config or self.article_config(), calibrator=calibrator)
        prices = [100.0, 100.30, 99.80, 100.28, 99.82, 100.26, 99.84, 100.24, 99.86, 100.22, 100.20, 99.82]
        for index, price in enumerate(prices):
            universe.ingest_trade(
                symbol="TESTUSDT",
                event_time_ms=index * 60_000 + 50_000,
                price=price,
                quantity=1.0,
                taker_buy=index % 2 == 0,
            )
        now_ms = 12 * 60_000
        self.add_favorable_long_flow(universe, now_ms=now_ms, bid_price=99.82)
        return universe, now_ms

    def article_config(self):
        return NearBboConfig(
            **{
                **self.config.__dict__,
                "setup_mode": "article_v2",
                "regime_config": NearBboRegimeConfig(
                    history_minutes=16,
                    min_bars=12,
                    fast_ema_span=5,
                    slow_ema_span=12,
                ),
                "scout_confirmation_ms": 2_000,
                "scout_ttl_ms": 8_000,
                "max_signal_volatility_bps": 8.0,
                "min_reversal_bps": 0.4,
            }
        )

    @staticmethod
    def add_favorable_long_flow(universe, *, now_ms: int, bid_price: float):
        universe.ingest_book_ticker(
            symbol="TESTUSDT",
            event_time_ms=now_ms,
            bid_price=bid_price,
            bid_quantity=10.0,
            ask_price=bid_price + 0.02,
            ask_quantity=2.0,
        )
        for offset_ms, delta, quantity, taker_buy in [
            (-4_000, -0.006, 2.0, False),
            (-3_000, -0.004, 2.0, False),
            (-2_000, -0.002, 2.0, True),
            (-900, 0.000, 2.0, False),
            (-500, 0.006, 3.0, True),
            (-100, 0.010, 2.0, True),
        ]:
            universe.ingest_trade(
                symbol="TESTUSDT",
                event_time_ms=now_ms + offset_ms,
                price=bid_price + delta,
                quantity=quantity,
                taker_buy=taker_buy,
            )


class FixedCalibrator:
    def __init__(self, *, fill: float, win: float, net_bps: float):
        self.fill = fill
        self.win = win
        self.net_bps = net_bps
        self.calls = []

    def predict(self, features, *, side, lane, regime):
        self.calls.append({"features": features, "side": side, "lane": lane, "regime": regime})
        return SimpleNamespace(
            fill_probability=self.fill,
            win_probability=self.win,
            expected_net_bps=self.net_bps,
        )


if __name__ == "__main__":
    unittest.main()
