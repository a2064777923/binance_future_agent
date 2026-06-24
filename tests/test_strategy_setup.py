import unittest

from bfa.ai.schema import RiskLimits
from bfa.backtest.models import built_in_variants
from bfa.strategy.setup import build_trade_setup


class StrategySetupTests(unittest.TestCase):
    def risk_limits(self):
        return RiskLimits(
            account_capital_usdt=30,
            max_leverage=10,
            max_position_notional_usdt=25,
            max_risk_per_trade_usdt=0.6,
            max_daily_loss_usdt=2,
            max_open_positions=2,
        )

    def candidate(self, **feature_overrides):
        features = {
            "mention_count": 2,
            "source_count": 2,
            "engagement_score": 120,
            "price_change_percent": 5.5,
            "quote_volume": 25_000_000,
            "open_interest_value": 15_000_000,
            "taker_buy_sell_ratio": 1.35,
            "taker_buy_sell_ratio_change": 0.08,
            "funding_rate": -0.0001,
            "kline_range_mean_percent": 1.1,
            "kline_range_max_percent": 2.0,
            "kline_momentum_percent": 1.8,
            "kline_micro_momentum_percent": 0.4,
            "kline_close_position_percent": 78,
            "kline_quote_volume_change_percent": 35,
            "support_price": 97.8,
            "resistance_price": 103.2,
            "vwap": 99.4,
            "atr_percent": 1.05,
            "ema_fast": 100.8,
            "ema_slow": 99.6,
            "ema_spread_percent": 1.2,
            "rsi": 68.0,
            "indicator_sample_size": 12,
            "reference_price": 100.0,
            "min_executable_notional": 5.0,
        }
        features.update(feature_overrides)
        return {
            "symbol": "BTCUSDT",
            "score": 80,
            "reason_codes": ["narrative_heat", "price_momentum"],
            "features": features,
        }

    def test_builds_deterministic_long_setup_with_factor_breakdown(self):
        setup = build_trade_setup(self.candidate(), risk_limits=self.risk_limits())

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "long")
        self.assertIsNotNone(setup.entry_price)
        self.assertIsNotNone(setup.stop_price)
        self.assertIsNotNone(setup.target_price)
        self.assertLess(setup.stop_price, setup.entry_price)
        self.assertGreater(setup.target_price, setup.entry_price)
        self.assertLessEqual(setup.notional_usdt, 25)
        self.assertGreaterEqual(setup.notional_usdt, 5)
        self.assertGreaterEqual(setup.risk_reward_ratio, 1.2)
        self.assertEqual(setup.price_basis["model"], "expected_market_entry_structure_stop_target_v1")
        self.assertEqual(setup.price_basis["stop_basis"]["anchor"], "support_price")
        self.assertIn("target_basis", setup.price_basis)
        self.assertEqual(setup.factor_summary["schema"], "bfa_factor_summary_v1")
        self.assertIn("trend_momentum", setup.factor_summary["group_totals"])
        self.assertTrue(setup.factor_summary["threshold_checks"]["edge_passed"])
        self.assertIn("sizing_diagnostics", setup.price_basis)
        self.assertIn("liquidation_diagnostics", setup.price_basis)
        self.assertTrue(setup.price_basis["liquidation_diagnostics"]["stop_before_liquidation"])
        self.assertEqual(setup.price_basis["exchange_filters"]["min_executable_notional"], 5.0)
        self.assertIn("quant_long_setup", setup.reasons)
        self.assertGreaterEqual(len(setup.factor_scores), 11)
        self.assertIn("momentum", {factor.name for factor in setup.factor_scores})
        self.assertIn("taker_flow", {factor.name for factor in setup.factor_scores})
        self.assertIn("trend_structure", {factor.name for factor in setup.factor_scores})
        self.assertIn("rsi_regime", {factor.name for factor in setup.factor_scores})
        self.assertIn("group", setup.factor_scores[0].to_dict())
        self.assertIn("polarity", setup.factor_scores[0].to_dict())

    def test_builds_short_setup_when_directional_factors_flip(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=-4.0,
                taker_buy_sell_ratio=0.72,
                taker_buy_sell_ratio_change=-0.1,
                funding_rate=0.0002,
                kline_momentum_percent=-1.4,
                kline_micro_momentum_percent=-0.3,
                kline_close_position_percent=22,
                support_price=96.0,
                resistance_price=102.2,
                vwap=100.7,
                ema_fast=99.1,
                ema_slow=100.4,
                ema_spread_percent=-1.2948,
                rsi=31.0,
            ),
            risk_limits=self.risk_limits(),
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "short")
        self.assertGreater(setup.stop_price, setup.entry_price)
        self.assertLess(setup.target_price, setup.entry_price)

    def test_spike_reversal_factor_and_reference_are_exposed(self):
        setup = build_trade_setup(
            self.candidate(
                spike_reversal_signal="short",
                spike_wick_percent=3.3,
                spike_wick_to_body_ratio=12.0,
                spike_reversal_entry_price=100.2,
                spike_reversal_stop_price=103.65,
                spike_reversal_target_price=98.1,
            ),
            risk_limits=self.risk_limits(),
        )

        factor = next(item for item in setup.factor_scores if item.name == "spike_reversal")
        self.assertEqual(factor.direction, "short")
        self.assertIn("spike_reversal_short", factor.reasons)
        reference = setup.price_basis["spike_reversal_reference"]
        self.assertEqual(reference["signal"], "short")
        self.assertEqual(reference["entry_price"], 100.2)
        self.assertEqual(reference["stop_price"], 103.65)
        self.assertEqual(reference["target_price"], 98.1)
        self.assertIn("spike_reversal", {item["name"] for item in setup.factor_summary["top_factors"]})

    def test_passes_when_factor_edge_is_too_small(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=0.1,
                taker_buy_sell_ratio=1.0,
                taker_buy_sell_ratio_change=0.0,
                funding_rate=0.0,
                kline_momentum_percent=0.05,
                kline_micro_momentum_percent=0.0,
                kline_close_position_percent=50,
                kline_quote_volume_change_percent=0,
                support_price=99.5,
                resistance_price=100.5,
                vwap=100.0,
                atr_percent=1.0,
                ema_fast=100.0,
                ema_slow=100.0,
                ema_spread_percent=0.0,
                rsi=50.0,
            ),
            risk_limits=self.risk_limits(),
        )

        self.assertEqual(setup.decision, "pass")
        self.assertEqual(setup.side, "flat")
        self.assertIn("factor_edge_too_small", setup.reasons)

    def test_profile_can_require_trend_alignment_and_indicator_coverage(self):
        setup = build_trade_setup(
            self.candidate(
                indicator_sample_size=3,
                ema_spread_percent=-0.2,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "selective",
                "min_edge": 20,
                "min_indicator_sample_size": 8,
                "require_trend_alignment": True,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertEqual(setup.side, "flat")
        self.assertIn("indicator_sample_below_profile_min", setup.reasons)
        self.assertIn("trend_not_aligned", setup.reasons)
        self.assertEqual(setup.price_basis["profile"], "selective")

    def test_profile_can_disable_side_without_changing_default(self):
        short_candidate = self.candidate(
            price_change_percent=-4.0,
            taker_buy_sell_ratio=0.72,
            taker_buy_sell_ratio_change=-0.1,
            funding_rate=0.0002,
            kline_momentum_percent=-1.4,
            kline_micro_momentum_percent=-0.3,
            kline_close_position_percent=22,
            support_price=96.0,
            resistance_price=102.2,
            vwap=100.7,
            ema_fast=99.1,
            ema_slow=100.4,
            ema_spread_percent=-1.2948,
            rsi=31.0,
        )

        default_setup = build_trade_setup(short_candidate, risk_limits=self.risk_limits())
        guarded_setup = build_trade_setup(
            short_candidate,
            risk_limits=self.risk_limits(),
            profile={"name": "guarded", "disabled_sides": ["short"]},
        )

        self.assertEqual(default_setup.decision, "trade")
        self.assertEqual(default_setup.side, "short")
        self.assertEqual(guarded_setup.decision, "pass")
        self.assertEqual(guarded_setup.side, "flat")
        self.assertIn("side_disabled_by_profile", guarded_setup.reasons)

    def test_profile_can_exclude_symbol(self):
        setup = build_trade_setup(
            self.candidate(),
            risk_limits=self.risk_limits(),
            profile={"name": "guarded", "excluded_symbols": ["BTCUSDT"]},
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("symbol_excluded_by_profile", setup.reasons)

    def test_profile_can_require_open_interest_liquidity_momentum_and_volume_impulse(self):
        setup = build_trade_setup(
            self.candidate(
                open_interest_value=None,
                quote_volume=2_000_000,
                price_change_percent=0.2,
                kline_momentum_percent=0.15,
                kline_micro_momentum_percent=0.05,
                kline_quote_volume_change_percent=3.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "loss_recalibrated",
                "require_open_interest": True,
                "min_quote_volume_usdt": 10_000_000,
                "min_abs_momentum_percent": 0.8,
                "min_volume_impulse_percent": 10.0,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("missing_open_interest", setup.reasons)
        self.assertIn("quote_volume_below_profile_min", setup.reasons)
        self.assertIn("momentum_below_profile_min", setup.reasons)
        self.assertIn("volume_impulse_below_profile_min", setup.reasons)

    def test_profile_can_cap_volatility_and_require_directional_taker_flow(self):
        setup = build_trade_setup(
            self.candidate(
                atr_percent=3.5,
                taker_buy_sell_ratio=1.01,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "hf_profit_guarded",
                "max_volatility_percent": 2.2,
                "min_directional_taker_flow_edge": 0.04,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("volatility_above_profile_max", setup.reasons)
        self.assertIn("taker_flow_not_aligned", setup.reasons)

    def test_live_flow_profile_blocks_hot_long_when_micro_structure_has_rolled_over(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=28.7,
                kline_momentum_percent=2.0,
                kline_micro_momentum_percent=-0.31,
                kline_close_position_percent=13.0,
                kline_quote_volume_change_percent=27.7,
                ema_fast=0.482,
                ema_slow=0.4828,
                ema_spread_percent=-0.155,
                reference_price=0.4806,
                vwap=0.4841,
                rsi=35.5,
                taker_buy_sell_ratio=1.065,
                taker_buy_sell_ratio_change=0.39,
                spike_reversal_signal="long",
                spike_wick_percent=1.65,
                spike_wick_to_body_ratio=26.6,
                support_price=0.47,
                resistance_price=0.494,
                min_executable_notional=5.0,
            ),
            risk_limits=self.risk_limits(),
            profile=built_in_variants()["quant_setup_high_frequency_flow_guarded"].setup_profile,
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("adverse_trend_vwap_alignment", setup.reasons)
        self.assertIn("micro_momentum_against_side", setup.reasons)
        self.assertIn("rsi_below_long_profile_min", setup.reasons)
        self.assertIn("hot_move_micro_reversal", setup.reasons)
        self.assertTrue(any(reason.startswith("directional_confluence_below_profile_min") for reason in setup.reasons))

    def test_live_flow_profile_treats_negative_volume_change_as_fade_not_impulse(self):
        setup = build_trade_setup(
            self.candidate(
                kline_quote_volume_change_percent=-62.0,
                kline_micro_momentum_percent=0.2,
                taker_buy_sell_ratio=1.08,
            ),
            risk_limits=self.risk_limits(),
            profile=built_in_variants()["quant_setup_high_frequency_flow_guarded"].setup_profile,
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("volume_impulse_below_profile_min", setup.reasons)

    def test_live_flow_profile_blocks_spike_signal_against_selected_side(self):
        setup = build_trade_setup(
            self.candidate(
                spike_reversal_signal="short",
                spike_wick_percent=1.8,
                spike_wick_to_body_ratio=2.2,
            ),
            risk_limits=self.risk_limits(),
            profile=built_in_variants()["quant_setup_high_frequency_flow_guarded"].setup_profile,
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("spike_reversal_against_side", setup.reasons)

    def test_live_flow_profile_allows_short_without_symbol_blacklist_when_factors_align(self):
        candidate = self.candidate(
            price_change_percent=-9.0,
            kline_momentum_percent=-2.1,
            kline_micro_momentum_percent=-0.35,
            kline_close_position_percent=18.0,
            kline_quote_volume_change_percent=28.0,
            ema_fast=99.0,
            ema_slow=100.0,
            ema_spread_percent=-1.0,
            reference_price=100.0,
            vwap=101.0,
            rsi=36.0,
            taker_buy_sell_ratio=0.86,
            taker_buy_sell_ratio_change=-0.08,
            funding_rate=0.0001,
            support_price=97.0,
            resistance_price=102.0,
            spike_reversal_signal=None,
        )
        candidate["symbol"] = "BICOUSDT"

        setup = build_trade_setup(
            candidate,
            risk_limits=self.risk_limits(),
            profile=built_in_variants()["quant_setup_high_frequency_flow_guarded"].setup_profile,
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "short")
        self.assertNotIn("symbol_excluded_by_profile", setup.reasons)

    def test_profile_can_block_setup_reason_and_negative_factor_name(self):
        crowded = build_trade_setup(
            self.candidate(funding_rate=0.001, taker_buy_sell_ratio=1.9),
            risk_limits=self.risk_limits(),
            profile={"name": "loss_recalibrated", "blocked_setup_reasons": ["crowding_risk"]},
        )
        weak_volume = build_trade_setup(
            self.candidate(kline_quote_volume_change_percent=-30.0),
            risk_limits=self.risk_limits(),
            profile={"name": "loss_recalibrated", "blocked_factor_names": ["volume_impulse"]},
        )

        self.assertEqual(crowded.decision, "pass")
        self.assertIn("profile_blocked_setup_reason:crowding_risk", crowded.reasons)
        self.assertEqual(weak_volume.decision, "pass")
        self.assertIn("profile_blocked_factor_name:volume_impulse", weak_volume.reasons)

    def test_small_notional_pressure_is_explained(self):
        setup = build_trade_setup(
            self.candidate(min_executable_notional=8.0),
            risk_limits=RiskLimits(
                account_capital_usdt=30,
                max_leverage=10,
                max_position_notional_usdt=10,
                max_risk_per_trade_usdt=0.25,
                max_daily_loss_usdt=2,
                max_open_positions=2,
            ),
            profile={"name": "fractional", "max_notional_fraction": 0.7},
        )

        diagnostics = setup.price_basis["sizing_diagnostics"]
        self.assertIn("raised_to_min_executable_notional", setup.warnings)
        self.assertGreater(diagnostics["min_notional_pressure"], 0)
        self.assertEqual(diagnostics["max_position_notional_usdt"], 10)
        self.assertEqual(diagnostics["final_notional_usdt"], setup.notional_usdt)

    def test_limit_entry_profile_places_long_below_reference_and_short_above(self):
        long_setup = build_trade_setup(
            self.candidate(vwap=99.72, support_price=99.4),
            risk_limits=self.risk_limits(),
            profile={
                "name": "limit_entry",
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.2,
                "limit_entry_min_offset_percent": 0.05,
                "limit_entry_max_offset_percent": 0.4,
                "limit_entry_max_wait_seconds": 120,
            },
        )
        short_setup = build_trade_setup(
            self.candidate(
                price_change_percent=-4.0,
                taker_buy_sell_ratio=0.72,
                taker_buy_sell_ratio_change=-0.1,
                funding_rate=0.0002,
                kline_momentum_percent=-1.4,
                kline_micro_momentum_percent=-0.3,
                kline_close_position_percent=22,
                support_price=96.0,
                resistance_price=100.28,
                vwap=100.2,
                ema_fast=99.1,
                ema_slow=100.4,
                ema_spread_percent=-1.2948,
                rsi=31.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "limit_entry",
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.2,
                "limit_entry_min_offset_percent": 0.05,
                "limit_entry_max_offset_percent": 0.4,
                "limit_entry_max_wait_seconds": 120,
            },
        )

        self.assertEqual(long_setup.decision, "trade")
        self.assertLess(long_setup.entry_price, 100.0)
        self.assertEqual(long_setup.price_basis["entry_basis"]["order_type"], "limit")
        self.assertEqual(long_setup.price_basis["entry_basis"]["limit_entry_max_wait_seconds"], 120)
        self.assertEqual(short_setup.decision, "trade")
        self.assertGreater(short_setup.entry_price, 100.0)
        self.assertEqual(short_setup.price_basis["model"], "limit_entry_structure_stop_target_v1")

    def test_post_cost_edge_gate_rejects_target_too_small_for_costs(self):
        setup = build_trade_setup(
            self.candidate(),
            risk_limits=self.risk_limits(),
            profile={
                "name": "post_cost_gate",
                "min_post_cost_edge_ratio": 20.0,
                "fee_bps": 4.0,
                "slippage_bps": 5.0,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("post_cost_edge_below_profile_min", setup.reasons)
        self.assertFalse(setup.price_basis["post_cost_edge"]["passed"])

    def test_mtf_alignment_gate_rejects_long_when_15m_context_is_bearish(self):
        setup = build_trade_setup(
            self.candidate(
                mtf_15m_ema_spread_percent=-0.5,
                mtf_15m_momentum_percent=-1.0,
                mtf_15m_micro_momentum_percent=-0.25,
                mtf_15m_reference_price=99.0,
                mtf_15m_vwap=100.0,
                mtf_15m_taker_buy_sell_ratio=0.9,
                mtf_15m_close_position_percent=30.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "mtf_gate",
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 3,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("mtf_alignment_below_profile_min:0/3", setup.reasons)
        self.assertEqual(setup.price_basis["mtf_alignment"]["score"], 0)

    def test_adaptive_stop_uses_realized_volatility_when_enabled(self):
        default_setup = build_trade_setup(
            self.candidate(atr_percent=0.3, realized_volatility_percent=1.4),
            risk_limits=self.risk_limits(),
            profile={"name": "default_stop"},
        )
        adaptive_setup = build_trade_setup(
            self.candidate(atr_percent=0.3, realized_volatility_percent=1.4),
            risk_limits=self.risk_limits(),
            profile={
                "name": "adaptive_stop",
                "adaptive_stop_enabled": True,
                "adaptive_stop_realized_volatility_multiplier": 1.6,
                "max_stop_distance_percent": 3.0,
            },
        )

        self.assertGreater(adaptive_setup.stop_distance_percent, default_setup.stop_distance_percent)
        self.assertTrue(adaptive_setup.price_basis["stop_basis"]["adaptive_stop_enabled"])

    def test_entry_quality_gate_rejects_weak_trend_follow_signal(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=8.0,
                kline_momentum_percent=0.1,
                kline_micro_momentum_percent=0.0,
                ema_spread_percent=0.1,
                vwap=99.5,
                taker_buy_sell_ratio=1.1,
                taker_buy_sell_ratio_change=0.0,
                kline_close_position_percent=70.0,
                kline_quote_volume_change_percent=0.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "quality_gate",
                "min_edge": 10.0,
                "min_confidence": 0.0,
                "require_entry_quality": True,
                "min_entry_quality_score": 7,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("signal_mode:trend_follow", setup.reasons)
        self.assertIn("entry_quality_below_profile_min:6/7", setup.reasons)

    def test_live_action_flow_profile_requires_direction_and_limit_entry_quality(self):
        profile = built_in_variants()["quant_setup_live_action_flow"].setup_profile

        setup = build_trade_setup(
            self.candidate(
                kline_momentum_percent=0.13,
                kline_micro_momentum_percent=0.0,
                kline_close_position_percent=97.0,
                kline_quote_volume_change_percent=-8.0,
                taker_buy_sell_ratio=1.0,
                taker_buy_sell_ratio_change=-0.06,
                ema_spread_percent=0.13,
                vwap=98.0,
                support_price=97.9,
            ),
            risk_limits=self.risk_limits(),
            profile=profile,
        )

        self.assertEqual(setup.decision, "pass")
        self.assertTrue(any(reason.startswith("entry_quality_below_profile_min") for reason in setup.reasons))
        self.assertIn("limit_entry_quality", setup.price_basis)
        self.assertEqual(setup.price_basis["entry_basis"]["order_type"], "limit")

    def test_limit_entry_quality_gate_rejects_chasing_without_structure(self):
        setup = build_trade_setup(
            self.candidate(
                kline_close_position_percent=98.0,
                vwap=None,
                support_price=None,
                resistance_price=None,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "limit_quality",
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.02,
                "limit_entry_min_offset_percent": 0.0,
                "limit_entry_max_offset_percent": 0.02,
                "require_limit_entry_quality": True,
                "min_limit_entry_quality_score": 6,
            },
        )

        self.assertEqual(setup.decision, "pass")
        self.assertIn("limit_entry_quality_below_profile_min:3/6", setup.reasons)
        self.assertIn("limit_entry_anchor:volatility_retrace", setup.reasons)
        self.assertFalse(
            next(
                item
                for item in setup.price_basis["limit_entry_quality"]["checks"]
                if item["name"] == "avoids_late_extreme"
            )["passed"]
        )

    def test_counter_signal_can_flip_side_when_short_structure_confirms(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=15.0,
                kline_momentum_percent=-1.0,
                kline_micro_momentum_percent=-0.2,
                ema_spread_percent=-0.25,
                vwap=101.0,
                taker_buy_sell_ratio=0.86,
                taker_buy_sell_ratio_change=-0.04,
                kline_close_position_percent=35.0,
                kline_quote_volume_change_percent=5.0,
                support_price=96.0,
                resistance_price=102.0,
                rsi=48.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "counter_signal",
                "min_edge": 20.0,
                "min_confidence": 0.0,
                "require_trend_alignment": True,
                "require_entry_quality": True,
                "min_entry_quality_score": 6,
                "allow_counter_signal": True,
                "min_counter_signal_score": 7,
            },
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "short")
        self.assertIn("signal_mode:counter_signal", setup.reasons)
        self.assertEqual(setup.price_basis["signal_diagnostics"]["mode"], "counter_signal")

    def test_orderly_range_near_low_edge_uses_reversion_long_limit(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=0.1,
                kline_momentum_percent=0.0,
                kline_micro_momentum_percent=0.0,
                ema_spread_percent=0.04,
                reference_price=99.4,
                support_price=99.0,
                resistance_price=101.0,
                vwap=100.0,
                range_low_price=99.0,
                range_high_price=101.0,
                range_width_percent=2.012,
                range_close_position_percent=20.0,
                range_lower_touch_count=3,
                range_upper_touch_count=3,
                range_volume_cv=0.12,
                range_path_efficiency=0.18,
                kline_close_position_percent=45.0,
                kline_quote_volume_change_percent=0.0,
                taker_buy_sell_ratio=1.0,
                taker_buy_sell_ratio_change=0.0,
                rsi=50.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "range_low",
                "min_edge": 10.0,
                "min_confidence": 0.0,
                "entry_order_type": "limit",
                "enable_orderly_range": True,
                "min_orderly_range_score": 6,
                "orderly_range_min_touch_count": 2,
            },
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "long")
        self.assertIn("signal_mode:orderly_range_reversion", setup.reasons)
        self.assertEqual(setup.price_basis["entry_basis"]["anchor"], "range_low_reversion")
        self.assertLess(setup.entry_price, setup.price_basis["reference_price"])

    def test_orderly_range_near_high_edge_uses_reversion_short_limit(self):
        setup = build_trade_setup(
            self.candidate(
                price_change_percent=0.1,
                kline_momentum_percent=0.0,
                kline_micro_momentum_percent=0.0,
                ema_spread_percent=0.04,
                reference_price=100.6,
                support_price=99.0,
                resistance_price=101.0,
                vwap=100.0,
                range_low_price=99.0,
                range_high_price=101.0,
                range_width_percent=1.988,
                range_close_position_percent=80.0,
                range_lower_touch_count=3,
                range_upper_touch_count=3,
                range_volume_cv=0.12,
                range_path_efficiency=0.18,
                kline_close_position_percent=55.0,
                kline_quote_volume_change_percent=0.0,
                taker_buy_sell_ratio=1.0,
                taker_buy_sell_ratio_change=0.0,
                rsi=50.0,
            ),
            risk_limits=self.risk_limits(),
            profile={
                "name": "range_high",
                "min_edge": 10.0,
                "min_confidence": 0.0,
                "entry_order_type": "limit",
                "enable_orderly_range": True,
                "min_orderly_range_score": 6,
                "orderly_range_min_touch_count": 2,
            },
        )

        self.assertEqual(setup.decision, "trade")
        self.assertEqual(setup.side, "short")
        self.assertIn("signal_mode:orderly_range_reversion", setup.reasons)
        self.assertEqual(setup.price_basis["entry_basis"]["anchor"], "range_high_reversion")
        self.assertGreater(setup.entry_price, setup.price_basis["reference_price"])


if __name__ == "__main__":
    unittest.main()
