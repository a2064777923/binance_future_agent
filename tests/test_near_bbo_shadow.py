import unittest

from bfa.backtest.near_bbo_shadow import NearBboShadowConfig, NearBboShadowLedger
from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse


def proposal(now_ms=10_000):
    config = NearBboConfig(
        min_trade_events=5,
        min_top_notional_usdt=100.0,
        min_fill_probability=0.10,
        min_win_probability=0.58,
        min_conditional_net_ev_bps=0.10,
    )
    universe = NearBboUniverse(config)
    universe.ingest_book_ticker(
        symbol="TESTUSDT",
        event_time_ms=now_ms,
        bid_price=100.0,
        bid_quantity=10.0,
        ask_price=100.02,
        ask_quantity=2.0,
    )
    for values in [
        (6_000, 99.995, 2.0, False),
        (7_000, 99.997, 2.0, False),
        (8_000, 99.999, 2.0, True),
        (9_100, 100.000, 2.0, False),
        (9_500, 100.001, 3.0, True),
        (9_900, 100.002, 2.0, False),
    ]:
        universe.ingest_trade(
            symbol="TESTUSDT",
            event_time_ms=values[0],
            price=values[1],
            quantity=values[2],
            taker_buy=values[3],
        )
    proposals, _diagnostics = universe.rank_opportunities(now_ms=now_ms)
    return proposals[0], config


class NearBboShadowLedgerTests(unittest.TestCase):
    def test_touch_fill_mode_fills_on_first_matching_trade_without_consuming_displayed_queue(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                queue_fill_mode="touch",
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])

        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=0.01,
            taker_buy=False,
        )

        self.assertEqual(ledger.summary(now_ms=10_100)["filled_count"], 1)
        self.assertEqual(ledger.summary(now_ms=10_100)["open_position_count"], 1)

    def test_expired_volume_queue_reports_touch_and_consumption_diagnostics(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=3),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=2.0,
            taker_buy=False,
        )
        ledger.advance(item.expires_at_ms)

        summary = ledger.summary(now_ms=item.expires_at_ms)
        label = ledger.labels[0]
        self.assertEqual(summary["queue_blocked_expired_count"], 1)
        self.assertEqual(summary["untouched_expired_count"], 0)
        self.assertEqual(label.features["shadow_matching_trade_count"], 1)
        self.assertEqual(label.features["shadow_matching_quantity"], 2.0)
        self.assertGreater(label.features["shadow_queue_consumed_fraction"], 0.0)
        self.assertLess(label.features["shadow_queue_consumed_fraction"], 1.0)

    def test_invalid_queue_fill_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "queue_fill_mode"):
            NearBboShadowConfig(queue_fill_mode="unknown")

    def test_trade_through_mode_requires_queue_at_limit_but_fills_beyond_it(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                queue_fill_mode="price_through_or_volume_ahead",
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])

        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=0.01,
            taker_buy=False,
        )
        self.assertEqual(ledger.summary(now_ms=10_100)["filled_count"], 0)
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_200,
            price=item.entry_price - 0.01,
            quantity=0.01,
            taker_buy=False,
        )

        summary = ledger.summary(now_ms=10_200)
        self.assertEqual(summary["filled_count"], 1)
        self.assertEqual(summary["trade_through_fill_count"], 1)

    def test_queue_fraction_scales_fill_only_and_preserves_displayed_queue_audit(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                queue_ahead_fraction=0.10,
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])

        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=0.5,
            taker_buy=False,
        )
        self.assertEqual(ledger.summary(now_ms=10_100)["filled_count"], 0)
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_200,
            price=item.entry_price,
            quantity=0.6,
            taker_buy=False,
        )
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=11_000,
            price=item.target_price,
            quantity=1.0,
            taker_buy=True,
        )

        label = ledger.labels[0]
        self.assertEqual(ledger.summary(now_ms=11_000)["filled_count"], 1)
        self.assertEqual(
            label.features["shadow_displayed_queue_ahead_quantity"],
            item.queue_ahead_quantity,
        )
        self.assertAlmostEqual(
            label.features["shadow_applied_queue_ahead_quantity"],
            item.queue_ahead_quantity * 0.10,
        )
        self.assertEqual(label.features["shadow_queue_ahead_fraction"], 0.10)

    def test_invalid_queue_fraction_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "queue_ahead_fraction"):
            NearBboShadowConfig(queue_ahead_fraction=0.0)

    def test_queue_proxy_requires_matching_aggressor_volume_before_fill(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=3),
            strategy_config=strategy_config,
        )
        ledger.admit([item])

        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_100, price=100.0, quantity=20.0, taker_buy=True)
        self.assertEqual(ledger.summary(now_ms=10_100)["filled_count"], 0)
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_200, price=100.0, quantity=6.0, taker_buy=False)
        self.assertEqual(ledger.summary(now_ms=10_200)["filled_count"], 0)
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_300, price=100.0, quantity=5.0, taker_buy=False)

        summary = ledger.summary(now_ms=10_300)
        self.assertEqual(summary["filled_count"], 1)
        self.assertEqual(summary["open_position_count"], 1)

    def test_target_exit_records_costed_positive_outcome(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=3),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_200, price=100.0, quantity=11.0, taker_buy=False)
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=11_000,
            price=item.target_price,
            quantity=1.0,
            taker_buy=True,
        )

        summary = ledger.summary(now_ms=11_000)
        self.assertEqual(summary["closed_count"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertGreater(summary["net_pnl_usdt"], 0.0)
        self.assertEqual(ledger.outcomes[0].exit_reason, "take_profit")

    def test_stop_exit_uses_observed_worse_price_instead_of_ideal_stop_price(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                queue_fill_mode="touch",
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=0.01,
            taker_buy=False,
        )
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_200,
            price=item.stop_price - 0.05,
            quantity=1.0,
            taker_buy=False,
        )

        outcome = ledger.outcomes[0]
        self.assertEqual(outcome.exit_reason, "stop_loss")
        ideal_stop_with_slippage = item.stop_price * (
            1.0 - strategy_config.exit_slippage_bps / 10_000.0
        )
        self.assertLess(outcome.exit_price, ideal_stop_with_slippage - 0.04)

    def test_max_hold_exit_uses_trade_that_reaches_hold_deadline(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                max_hold_ms=1_000,
                queue_fill_mode="touch",
                evidence_exit_enabled=False,
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=10_100,
            price=item.entry_price,
            quantity=0.01,
            taker_buy=False,
        )
        deadline_price = item.entry_price + 0.05
        outcomes = ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=11_100,
            price=deadline_price,
            quantity=1.0,
            taker_buy=True,
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit_reason, "max_hold_exit")
        expected_exit = deadline_price * (
            1.0 - strategy_config.exit_slippage_bps / 10_000.0
        )
        self.assertAlmostEqual(outcomes[0].exit_price, expected_exit)
        self.assertGreater(outcomes[0].mfe_bps, 0.0)

    def test_unfilled_quote_expires_and_releases_capacity(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=1),
            strategy_config=strategy_config,
        )
        ledger.admit([item])

        ledger.advance(item.expires_at_ms)

        summary = ledger.summary(now_ms=item.expires_at_ms)
        self.assertEqual(summary["expired_count"], 1)
        self.assertEqual(summary["active_intent_count"], 0)
        self.assertEqual(ledger.available_capacity, 1)
        self.assertEqual(len(ledger.labels), 1)
        self.assertFalse(ledger.labels[0].filled)
        self.assertEqual(ledger.labels[0].proposal_id, item.proposal_id)
        self.assertEqual(ledger.labels[0].features["direction_score"], item.features["direction_score"])

    def test_capacity_is_separate_from_number_of_ranked_proposals(self):
        item, strategy_config = proposal()
        proposals = [
            item.__class__(**{**item.__dict__, "symbol": f"S{index}USDT"})
            for index in range(5)
        ]
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=3),
            strategy_config=strategy_config,
        )

        admitted = ledger.admit(proposals)

        self.assertEqual(len(admitted), 3)
        self.assertEqual(ledger.summary(now_ms=10_000)["capacity_rejected_count"], 2)

    def test_evidence_exit_locks_costed_profit_after_runner_gives_back(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                evidence_exit_enabled=True,
                profit_lock_activate_net_bps=2.0,
                profit_lock_min_net_bps=0.5,
                profit_lock_giveback_fraction=0.5,
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_200, price=100.0, quantity=11.0, taker_buy=False)
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=11_000, price=100.10, quantity=1.0, taker_buy=True)
        outcomes = ledger.on_trade(symbol="TESTUSDT", event_time_ms=12_000, price=100.055, quantity=1.0, taker_buy=False)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit_reason, "evidence_profit_lock")
        self.assertGreater(outcomes[0].net_pnl_usdt, 0.0)

    def test_evidence_exit_cuts_adverse_selection_when_reversal_never_appears(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(
                notional_usdt=120.0,
                max_active_intents=3,
                evidence_exit_enabled=True,
                confirmation_ms=3_000,
                adverse_selection_exit_bps=6.0,
            ),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_200, price=100.0, quantity=11.0, taker_buy=False)
        outcomes = ledger.on_trade(symbol="TESTUSDT", event_time_ms=13_300, price=99.93, quantity=1.0, taker_buy=False)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit_reason, "evidence_adverse_selection")
        self.assertLess(abs(outcomes[0].net_pnl_usdt), self.configured_stop_loss_usdt(item, strategy_config))

    def test_closed_fill_emits_training_label_once(self):
        item, strategy_config = proposal()
        ledger = NearBboShadowLedger(
            NearBboShadowConfig(notional_usdt=120.0, max_active_intents=3),
            strategy_config=strategy_config,
        )
        ledger.admit([item])
        ledger.on_trade(symbol="TESTUSDT", event_time_ms=10_200, price=100.0, quantity=11.0, taker_buy=False)
        ledger.on_trade(
            symbol="TESTUSDT",
            event_time_ms=11_000,
            price=item.target_price,
            quantity=1.0,
            taker_buy=True,
        )

        first = ledger.drain_new_labels()
        second = ledger.drain_new_labels()

        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertTrue(first[0].filled)
        self.assertTrue(first[0].profitable)
        self.assertGreater(first[0].net_pnl_usdt, 0.0)
        self.assertEqual(first[0].lane, item.lane)
        self.assertEqual(first[0].regime, item.regime)
        self.assertEqual(first[0].features["shadow_max_hold_seconds"], 30.0)
        self.assertEqual(first[0].features["shadow_evidence_exit_enabled"], 1.0)

    @staticmethod
    def configured_stop_loss_usdt(item, strategy_config):
        gross_stop = 120.0 * item.stop_bps / 10_000.0
        cost = 120.0 * strategy_config.expected_round_trip_cost_bps / 10_000.0
        return gross_stop + cost


if __name__ == "__main__":
    unittest.main()
