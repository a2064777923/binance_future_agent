import unittest

from bfa.agent import _fuse_live_candidates
from bfa.strategy.candidates import CandidateSignal
from bfa.strategy.regime import (
    CHOP,
    RANGE,
    TREND,
    annotate_candidate,
    classify_regime,
    route_allows_candidate,
)


class StrategyRegimeRouterTests(unittest.TestCase):
    def test_trend_sample_routes_to_trend_leg(self):
        decision = classify_regime(
            {
                "kline_momentum_percent": 0.92,
                "kline_micro_momentum_percent": 0.11,
                "ema_spread_percent": 0.16,
                "range_path_efficiency": 0.64,
                "range_edge_alternation_count": 0,
                "realized_volatility_percent": 2.1,
            },
            strategy_leg="trend",
        )

        self.assertEqual(decision.label, TREND)
        self.assertEqual(decision.allowed_strategy_legs, ["trend"])
        self.assertEqual(decision.route_decision, "allow")

    def test_range_sample_routes_to_micro_and_range_legs(self):
        decision = classify_regime(
            {
                "range_path_efficiency": 0.22,
                "range_edge_alternation_count": 3,
                "range_width_percent": 0.84,
                "ema_spread_percent": 0.04,
                "range_drift_to_width": 0.35,
            },
            strategy_leg="micro_grid",
        )

        self.assertEqual(decision.label, RANGE)
        self.assertEqual(decision.allowed_strategy_legs, ["micro_grid", "range_reversion"])
        self.assertEqual(decision.route_decision, "allow")

    def test_conflict_sample_routes_to_chop(self):
        decision = classify_regime(
            {
                "kline_momentum_percent": 0.95,
                "ema_spread_percent": 0.14,
                "range_path_efficiency": 0.24,
                "range_edge_alternation_count": 3,
                "range_width_percent": 0.72,
                "range_drift_to_width": 0.25,
            },
            strategy_leg="trend",
        )

        self.assertEqual(decision.label, CHOP)
        self.assertEqual(decision.allowed_strategy_legs, [])
        self.assertFalse(decision.route_decision == "allow")

    def test_trend_edge_exhaustion_routes_to_chop(self):
        decision = classify_regime(
            {
                "kline_momentum_percent": 0.9069,
                "kline_micro_momentum_percent": -0.0464,
                "kline_quote_volume_change_percent": -75.68,
                "kline_close_position_percent": 72.72,
                "kline_range_percent": 0.1704,
                "kline_range_mean_percent": 0.2863,
                "kline_range_max_percent": 1.2496,
                "ema_spread_percent": 0.3198,
                "realized_volatility_percent": 0.2779,
            },
            strategy_leg="trend",
            shadow_only=False,
        )

        self.assertEqual(decision.label, CHOP)
        self.assertIn("regime_trend_long_edge_exhaustion:recent_spike", decision.reason_codes)
        self.assertEqual(decision.allowed_strategy_legs, [])
        self.assertEqual(decision.route_decision, "skip_chop")

    def test_micro_grid_state_can_classify_range(self):
        candidate = annotate_candidate(
            self.candidate(
                "ETHUSDT",
                84.0,
                {
                    "strategy_leg": "micro_grid",
                    "micro_grid_state": {
                        "path_efficiency": 0.18,
                        "edge_alternation_count": 4,
                        "width_percent": 0.66,
                        "stable_width_percent": 0.62,
                        "drift_to_width": 0.22,
                    },
                },
            )
        )

        self.assertEqual(candidate.features["regime_label"], RANGE)
        self.assertTrue(route_allows_candidate(candidate))

    def test_fusion_enforced_keeps_only_regime_allowed_leg_for_symbol(self):
        normal = annotate_candidate(
            self.candidate(
                "SOLUSDT",
                250.0,
                {
                    "range_path_efficiency": 0.2,
                    "range_edge_alternation_count": 4,
                    "range_width_percent": 0.9,
                    "ema_spread_percent": 0.02,
                    "range_drift_to_width": 0.2,
                },
            ),
            shadow_only=False,
        )
        micro = annotate_candidate(
            self.candidate(
                "SOLUSDT",
                80.0,
                {
                    "strategy_leg": "micro_grid",
                    "micro_grid_score": 0.4,
                    "micro_grid_state": {
                        "path_efficiency": 0.2,
                        "edge_alternation_count": 4,
                        "width_percent": 0.9,
                        "stable_width_percent": 0.8,
                        "drift_to_width": 0.2,
                    },
                },
            ),
            shadow_only=False,
        )

        fused = _fuse_live_candidates([normal], [micro], top_n=3, enforce_regime=True)

        self.assertEqual([candidate.features["strategy_leg"] for candidate in fused], ["micro_grid"])

    def candidate(self, symbol: str, score: float, features: dict):
        return CandidateSignal(
            symbol=symbol,
            score=score,
            narrative_score=0.0,
            market_score=score,
            reason_codes=[],
            data_quality_notes=[],
            source_event_ids=[],
            market_event_ids=[],
            generated_at="2026-06-23T00:00:00Z",
            features=features,
        )


if __name__ == "__main__":
    unittest.main()
