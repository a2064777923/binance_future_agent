import unittest

from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse


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


if __name__ == "__main__":
    unittest.main()
