import importlib.util
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_strategy_fusion_replay.py"
SPEC = importlib.util.spec_from_file_location("strategy_fusion_replay", SCRIPT_PATH)
fusion = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = fusion
SPEC.loader.exec_module(fusion)


BASE = "2026-06-06T00:00:{:02d}Z"


class StrategyFusionReplayScriptTests(unittest.TestCase):
    def test_load_candidates_normalizes_standalone_equity_scale(self):
        payload = {
            "trades": [
                {
                    "symbol": "AAAUSDT",
                    "side": "long",
                    "entry_time": BASE.format(1),
                    "exit_time": BASE.format(5),
                    "entry_price": 100.0,
                    "exit_price": 101.0,
                    "notional_usdt": 40.0,
                    "gross_pnl_usdt": 4.0,
                    "fees_usdt": 0.4,
                    "slippage_usdt": 0.2,
                    "net_pnl_usdt": 3.4,
                    "exit_reason": "take_profit",
                    "reason_codes": ["demo"],
                    "equity_scale": 2.0,
                }
            ]
        }

        candidate = fusion.load_candidates("trend", Path("trend.json"), payload)[0]

        self.assertEqual(candidate.notional_usdt, 20.0)
        self.assertEqual(candidate.net_pnl_usdt, 1.7)

    def test_replay_uses_shared_equity_and_source_symbol_quality_gate(self):
        candidates = [
            self.candidate("micro", "AAAUSDT", 1, 5, -1.0, "stop_loss"),
            self.candidate("micro", "AAAUSDT", 20, 25, -1.0, "stop_loss"),
            self.candidate("micro", "AAAUSDT", 40, 45, 5.0, "take_profit"),
            self.candidate("trend", "BBBUSDT", 40, 45, 3.0, "take_profit"),
        ]

        replay = fusion.replay_fusion(
            candidates,
            initial_capital=30.0,
            max_open_positions=2,
            max_symbol_open_positions=1,
            daily_loss_fraction=0.0,
            quality_filter_enabled=True,
            quality_lookback_hours=72.0,
            quality_min_samples=2,
            quality_min_profit_factor=0.75,
            quality_max_stop_rate=0.65,
            quality_min_scale=0.0,
            source_quality_filter_enabled=False,
            source_quality_min_samples=8,
            source_quality_min_profit_factor=0.8,
            source_quality_max_stop_rate=0.7,
            source_quality_min_scale=0.0,
        )

        self.assertEqual([trade["source"] for trade in replay["trades"]], ["micro", "micro", "trend"])
        self.assertEqual(replay["summary"]["skip_counts"]["quality"], 1)
        self.assertEqual(replay["summary"]["source_counts"], {"micro": 2, "trend": 1})

    def test_replay_can_gate_degraded_source_globally(self):
        candidates = [
            self.candidate("trend", "AAAUSDT", 1, 5, -1.0, "stop_loss"),
            self.candidate("trend", "BBBUSDT", 20, 25, -1.0, "stop_loss"),
            self.candidate("trend", "CCCUSDT", 40, 45, 5.0, "take_profit"),
            self.candidate("micro", "DDDUSDT", 40, 45, 1.0, "take_profit"),
        ]

        replay = fusion.replay_fusion(
            candidates,
            initial_capital=30.0,
            max_open_positions=2,
            max_symbol_open_positions=1,
            daily_loss_fraction=0.0,
            quality_filter_enabled=False,
            quality_lookback_hours=72.0,
            quality_min_samples=2,
            quality_min_profit_factor=0.75,
            quality_max_stop_rate=0.65,
            quality_min_scale=0.0,
            source_quality_filter_enabled=True,
            source_quality_min_samples=2,
            source_quality_min_profit_factor=0.8,
            source_quality_max_stop_rate=0.7,
            source_quality_min_scale=0.0,
        )

        self.assertEqual([trade["source"] for trade in replay["trades"]], ["trend", "trend", "micro"])
        self.assertEqual(replay["summary"]["skip_counts"]["source_quality"], 1)

    def test_replay_can_enforce_regime_route(self):
        keep = self.candidate("trend", "AAAUSDT", 1, 5, 2.0, "take_profit")
        blocked = self.candidate("trend", "BBBUSDT", 8, 12, -2.0, "stop_loss")
        blocked = fusion.FusionCandidate(
            **{
                **blocked.__dict__,
                "regime_label": "CHOP",
                "allowed_strategy_legs": [],
                "route_decision": "skip_chop",
            }
        )

        replay = fusion.replay_fusion(
            [keep, blocked],
            initial_capital=30.0,
            max_open_positions=2,
            max_symbol_open_positions=1,
            daily_loss_fraction=0.0,
            quality_filter_enabled=False,
            quality_lookback_hours=72.0,
            quality_min_samples=2,
            quality_min_profit_factor=0.75,
            quality_max_stop_rate=0.65,
            quality_min_scale=0.0,
            source_quality_filter_enabled=False,
            source_quality_min_samples=8,
            source_quality_min_profit_factor=0.8,
            source_quality_max_stop_rate=0.7,
            source_quality_min_scale=0.0,
            regime_router_enabled=True,
            regime_router_enforced=True,
        )

        self.assertEqual([trade["symbol"] for trade in replay["trades"]], ["AAAUSDT"])
        self.assertEqual(replay["summary"]["skip_counts"]["regime_route"], 1)

    def test_replay_skips_zero_intent_scale_candidates(self):
        keep = self.candidate("micro", "AAAUSDT", 1, 5, 1.0, "take_profit")
        zero_scale = self.candidate("micro", "BBBUSDT", 8, 12, -2.0, "stop_loss")
        zero_scale = fusion.FusionCandidate(**{**zero_scale.__dict__, "intent_scale": 0.0})

        replay = fusion.replay_fusion(
            [keep, zero_scale],
            initial_capital=30.0,
            max_open_positions=2,
            max_symbol_open_positions=1,
            daily_loss_fraction=0.0,
            quality_filter_enabled=False,
            quality_lookback_hours=72.0,
            quality_min_samples=2,
            quality_min_profit_factor=0.75,
            quality_max_stop_rate=0.65,
            quality_min_scale=0.0,
            source_quality_filter_enabled=False,
            source_quality_min_samples=8,
            source_quality_min_profit_factor=0.8,
            source_quality_max_stop_rate=0.7,
            source_quality_min_scale=0.0,
        )

        self.assertEqual([trade["symbol"] for trade in replay["trades"]], ["AAAUSDT"])
        self.assertEqual(replay["summary"]["skip_counts"]["intent_scale"], 1)

    def test_inferred_micro_quality_proxy_matches_live_width_floor(self):
        scale = fusion.inferred_micro_quality_scale(
            {
                "signal_mode": "micro_smart_grid",
                "stable_width_percent": 0.21,
            }
        )

        self.assertEqual(scale, 0.0)

    def candidate(self, source, symbol, entry_second, exit_second, net_pnl, exit_reason):
        return fusion.FusionCandidate(
            source=source,
            symbol=symbol,
            side="long",
            entry_time=BASE.format(entry_second),
            exit_time=BASE.format(exit_second),
            entry_price=100.0,
            exit_price=101.0,
            notional_usdt=20.0,
            gross_pnl_usdt=net_pnl,
            fees_usdt=0.0,
            slippage_usdt=0.0,
            net_pnl_usdt=net_pnl,
            exit_reason=exit_reason,
            reason_codes=[],
            source_file=f"{source}.json",
            strategy_leg="micro_grid" if source == "micro" else "trend",
            regime_label="RANGE" if source == "micro" else "TREND",
            regime_confidence=0.6,
            regime_reason_codes=["test_regime"],
            allowed_strategy_legs=["micro_grid", "range_reversion"] if source == "micro" else ["trend"],
            route_decision="allow",
            route_shadow_only=True,
        )


if __name__ == "__main__":
    unittest.main()
