import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manual_ops" / "velvet_rescue.py"
SPEC = importlib.util.spec_from_file_location("velvet_rescue_script", SCRIPT_PATH)
velvet_rescue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = velvet_rescue
SPEC.loader.exec_module(velvet_rescue)


def cap_positions(*, long_upnl=-41.0, short_upnl=52.0):
    return {
        "LONG": velvet_rescue.Position("LONG", 19055.0, 0.02612, 0.0240, long_upnl),
        "SHORT": velvet_rescue.Position("SHORT", 16811.0, 0.02703, 0.0240, short_upnl),
    }


def downtrend_context(**overrides):
    context = {
        "range_mean_60_pct": 0.55,
        "change_5m_pct": -0.6,
        "change_15m_pct": -0.9,
        "change_30m_pct": -1.3,
        "pos30": 20.0,
        "pos120": 30.0,
        "pullback_from_hi30_pct": 1.9,
        "bounce_from_lo30_pct": 0.4,
        "volume_ratio_30": 0.7,
    }
    context.update(overrides)
    return context


class ManualRescueTrendModeTests(unittest.TestCase):
    def test_downtrend_keeps_profitable_short_hedge_running(self):
        positions = cap_positions()
        guard = velvet_rescue.trend_rescue_reduce_guard(
            "SHORT",
            positions["SHORT"],
            positions,
            downtrend_context(),
        )

        self.assertFalse(guard["allowed"])
        self.assertEqual(guard["reason"], "downtrend_keep_short_hedge_running")

    def test_losing_long_trim_requires_net_book_improvement(self):
        positions = cap_positions(long_upnl=-31.0, short_upnl=50.0)
        state = {
            "baseline": {
                "total_upnl": 20.0,
                "LONG": {"upnl": -43.0},
                "SHORT": {"upnl": 63.0},
            },
            "reduced": {},
        }

        actions = velvet_rescue.decide(
            positions,
            downtrend_context(pos30=76.0, pos120=66.0, change_5m_pct=-0.05, volume_ratio_30=0.5),
            state,
            mode="trend-rescue",
            profit_trigger=10.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=240.0,
            max_imbalance_after_reduce=0.25,
            reduce_fraction=0.08,
            trend_min_book_delta=2.5,
        )

        self.assertEqual(actions, [])

    def test_losing_long_can_trim_small_size_on_fading_bounce_after_book_improves(self):
        positions = cap_positions(long_upnl=-31.0, short_upnl=56.0)
        state = {
            "baseline": {
                "total_upnl": 20.0,
                "LONG": {"upnl": -43.0},
                "SHORT": {"upnl": 63.0},
            },
            "reduced": {},
        }

        actions = velvet_rescue.decide(
            positions,
            downtrend_context(pos30=76.0, pos120=66.0, change_5m_pct=-0.05, volume_ratio_30=0.5),
            state,
            mode="trend-rescue",
            profit_trigger=10.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=240.0,
            max_imbalance_after_reduce=0.25,
            reduce_fraction=0.08,
            trend_min_book_delta=2.5,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "reduce_one_third")
        self.assertEqual(actions[0]["side"], "LONG")
        self.assertEqual(actions[0]["quantity"], 1524)
        self.assertTrue(actions[0]["trend_guard"]["book_delta_ok"])


def velvet_positions(*, long_amount=298.0, short_amount=270.0):
    return {
        "LONG": velvet_rescue.Position("LONG", long_amount, 1.7526, 1.66, -26.0),
        "SHORT": velvet_rescue.Position("SHORT", short_amount, 1.6966, 1.66, 9.0),
    }


def velvet_downtrend_context(**overrides):
    context = {
        "range_mean_60_pct": 1.45,
        "change_5m_pct": -0.2,
        "change_15m_pct": -0.7,
        "change_30m_pct": -4.2,
        "pos30": 52.0,
        "pos120": 72.0,
        "pullback_from_hi30_pct": 5.0,
        "bounce_from_lo30_pct": 2.5,
        "volume_ratio_30": 0.8,
        "last": 1.66,
    }
    context.update(overrides)
    return context


class ManualRescueDowntrendLongTTests(unittest.TestCase):
    def test_readds_reduced_short_before_long_t(self):
        actions = velvet_rescue.decide(
            velvet_positions(),
            velvet_downtrend_context(),
            {
                "reduced": {"SHORT": {"quantity": 134, "reduce_upnl": 12.0}},
                "last_action_epoch": None,
            },
            mode="downtrend-long-t",
            profit_trigger=10.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=30.0,
            max_imbalance_after_reduce=0.30,
            reduce_fraction=1 / 3,
            trend_min_book_delta=0.0,
            long_probe_fraction=0.08,
            max_long_to_short_ratio=1.02,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "readd_reduced_third")
        self.assertEqual(actions[0]["side"], "SHORT")

    def test_does_not_reduce_short_after_short_is_restored(self):
        actions = velvet_rescue.decide(
            velvet_positions(),
            velvet_downtrend_context(pos30=10.0, pos120=20.0),
            {"reduced": {}, "last_action_epoch": None},
            mode="downtrend-long-t",
            profit_trigger=1.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=30.0,
            max_imbalance_after_reduce=0.30,
            reduce_fraction=1 / 3,
            trend_min_book_delta=0.0,
            long_probe_fraction=0.08,
            max_long_to_short_ratio=1.02,
        )

        self.assertNotEqual(actions[:1] and actions[0]["side"], "SHORT")

    def test_adds_limited_long_probe_on_down_spike(self):
        actions = velvet_rescue.decide(
            velvet_positions(long_amount=250.0, short_amount=270.0),
            velvet_downtrend_context(pos30=15.0, bounce_from_lo30_pct=1.2, change_5m_pct=-1.0, volume_ratio_30=1.2),
            {"reduced": {}, "last_action_epoch": None},
            mode="downtrend-long-t",
            profit_trigger=10.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=30.0,
            max_imbalance_after_reduce=0.30,
            reduce_fraction=1 / 3,
            trend_min_book_delta=0.0,
            long_probe_fraction=0.08,
            max_long_to_short_ratio=1.02,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "add_long_probe")
        self.assertEqual(actions[0]["side"], "LONG")
        self.assertEqual(actions[0]["quantity"], 21)

    def test_sells_long_probe_after_mean_reversion(self):
        actions = velvet_rescue.decide(
            velvet_positions(long_amount=271.0, short_amount=270.0),
            velvet_downtrend_context(pos30=48.0, bounce_from_lo30_pct=3.5, last=1.68),
            {
                "reduced": {},
                "long_probe": {"quantity": 21, "entry_price": 1.66},
                "last_action_epoch": None,
            },
            mode="downtrend-long-t",
            profit_trigger=10.0,
            drawdown_readd_usdt=8.0,
            cooldown_seconds=30.0,
            max_imbalance_after_reduce=0.30,
            reduce_fraction=1 / 3,
            trend_min_book_delta=0.0,
            long_probe_fraction=0.08,
            max_long_to_short_ratio=1.02,
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "reduce_long_probe")
        self.assertEqual(actions[0]["side"], "LONG")
        self.assertEqual(actions[0]["quantity"], 21)


if __name__ == "__main__":
    unittest.main()
