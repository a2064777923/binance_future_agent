import unittest

from bfa.backtest.cost import CostModel, SymbolFeeTier


class TestCostModel(unittest.TestCase):
    def test_default_tier_maker2_taker4(self):
        cm = CostModel()
        self.assertAlmostEqual(cm.tier("BTCUSDT").maker_fee_bps, 2.0)
        self.assertAlmostEqual(cm.tier("BTCUSDT").taker_fee_bps, 4.0)

    def test_per_symbol_tier_lookup_overrides_default(self):
        cm = CostModel(fee_tiers={"PUMPUSDT": SymbolFeeTier(maker_fee_bps=0.0, taker_fee_bps=0.0)})
        self.assertAlmostEqual(cm.tier("PUMPUSDT").taker_fee_bps, 0.0)
        self.assertAlmostEqual(cm.tier("BTCUSDT").taker_fee_bps, 4.0)  # falls back

    def test_round_trip_cost_percent_taker_both(self):
        cm = CostModel()
        # entry taker 4bps + exit taker 4bps + slip 5 + slip 5 = 18 bps = 0.18%
        rtc = cm.round_trip_cost_percent("BTCUSDT", entry_is_maker=False, exit_is_maker=False)
        self.assertAlmostEqual(rtc, 0.18, places=6)

    def test_round_trip_cost_percent_maker_entry(self):
        cm = CostModel()
        # entry maker 2 + exit taker 4 + maker_slip 1 + taker slip 5 = 12 bps = 0.12%
        rtc = cm.round_trip_cost_percent("BTCUSDT", entry_is_maker=True, exit_is_maker=False)
        self.assertAlmostEqual(rtc, 0.12, places=6)

    def test_trade_fees_usdt_taker_both(self):
        cm = CostModel()
        fees = cm.trade_fees_usdt("BTCUSDT", entry_price=100.0, exit_price=101.0, qty=10.0,
                                   entry_is_maker=False, exit_is_maker=False)
        # (100*10*0.0004) + (101*10*0.0004) = 0.4 + 0.404 = 0.804
        self.assertAlmostEqual(fees, 0.804, places=6)

    def test_funding_cost_long_positive_rate_pays(self):
        cm = CostModel()
        # one funding event at t=1000 with rate +0.0001, notional=1000, long => pays 0.1
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=2000,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, 0.1, places=6)

    def test_funding_cost_short_receives_when_positive_rate(self):
        cm = CostModel()
        # short with positive rate => receives => negative cost
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=2000,
                                     side="short", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, -0.1, places=6)

    def test_funding_cost_no_event_in_window_is_zero(self):
        cm = CostModel()
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=900,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_funding_cost_multiple_events_sum(self):
        cm = CostModel()
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=5000,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001), (2000, -0.0002), (4000, 0.0003)])
        # 0.1 + (-0.2) + 0.3 = 0.2
        self.assertAlmostEqual(cost, 0.2, places=6)

    def test_load_fee_tiers_json_uses_default_tier(self):
        from pathlib import Path
        import bfa.backtest.cost as cost_mod
        path = Path(cost_mod.__file__).parent / "fee_tiers.json"
        cm = CostModel.load_fee_tiers(path)
        self.assertIsInstance(cm, CostModel)
        self.assertAlmostEqual(cm.default_tier.taker_fee_bps, 4.0)


if __name__ == "__main__":
    unittest.main()
