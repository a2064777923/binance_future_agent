import importlib.util
import sys
import unittest
from pathlib import Path

from bfa.backtest.models import BacktestBar


sys.dont_write_bytecode = True
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_feature_label_research.py"
SPEC = importlib.util.spec_from_file_location("feature_label_research", SCRIPT_PATH)
research = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)


def bar(symbol, index, *, open_price, high, low, close, quote_volume=1_000_000, taker_ratio=0.5):
    open_time = 1_700_000_000_000 + index * 60_000
    return BacktestBar(
        symbol=symbol,
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1_000,
        close_time=open_time + 59_999,
        quote_volume=quote_volume,
        taker_buy_quote_volume=quote_volume * taker_ratio,
    )


def trending_bars(symbol="TESTUSDT", count=130, *, step=0.08):
    bars = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = price + step
        high = max(open_price, close) + 0.04
        low = min(open_price, close) - 0.04
        bars.append(
            bar(
                symbol,
                index,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                quote_volume=1_000_000 + index * 1000,
                taker_ratio=0.56,
            )
        )
        price = close
    return bars


def ranging_bars(symbol="TESTUSDT", count=130):
    bars = []
    closes = [99.4, 100.5, 99.6, 100.4, 99.5, 100.6]
    for index in range(count):
        open_price = closes[(index - 1) % len(closes)] if index else 100.0
        close = closes[index % len(closes)]
        bars.append(
            bar(
                symbol,
                index,
                open_price=open_price,
                high=max(open_price, close) + 0.18,
                low=min(open_price, close) - 0.18,
                close=close,
                quote_volume=1_000_000 + (index % 5) * 10_000,
                taker_ratio=0.5,
            )
        )
    return bars


class FeatureLabelResearchScriptTests(unittest.TestCase):
    def test_future_path_label_scores_long_and_short_oppositely(self):
        bars = trending_bars(count=70, step=0.1)

        long_label = research.future_path_label(
            bars,
            entry_index=61,
            side="long",
            horizon_minutes=5,
            fee_bps=4,
            slippage_bps=3,
        )
        short_label = research.future_path_label(
            bars,
            entry_index=61,
            side="short",
            horizon_minutes=5,
            fee_bps=4,
            slippage_bps=3,
        )

        self.assertGreater(long_label.opportunity_score_percent, short_label.opportunity_score_percent)
        self.assertGreater(long_label.mfe_percent, 0)
        self.assertLess(short_label.close_return_percent, 0)
        self.assertEqual(long_label.first_hit, "favorable")
        self.assertEqual(short_label.first_hit, "adverse")

    def test_build_labeled_samples_emits_both_sides_when_regime_filter_is_off(self):
        bars = trending_bars("AAAUSDT", count=100, step=0.07)

        samples = research.build_labeled_samples(
            {"AAAUSDT": bars},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            regime=research.RangeRegimeConfig(enabled=False),
            candidate_mode="all",
        )

        self.assertGreater(len(samples), 0)
        self.assertEqual({sample.side for sample in samples}, {"long", "short"})
        self.assertIn("side_momentum_5m", samples[0].features)
        self.assertIn("side_reversion_edge_15m", samples[0].features)

    def test_range_regime_filter_keeps_range_and_rejects_trend(self):
        regime = research.RangeRegimeConfig(enabled=True, max_path_efficiency_60m=0.55, max_abs_return_60m=1.5)
        range_samples = research.build_labeled_samples(
            {"AAAUSDT": ranging_bars("AAAUSDT", count=120)},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            regime=regime,
            candidate_mode="all",
        )
        trend_samples = research.build_labeled_samples(
            {"BBBUSDT": trending_bars("BBBUSDT", count=120, step=0.08)},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            regime=regime,
            candidate_mode="all",
        )

        self.assertGreater(len(range_samples), 0)
        self.assertEqual(len(trend_samples), 0)

    def test_range_edge_candidate_filter_keeps_only_edge_sides(self):
        low_edge = {
            "close_position_60m": 12.0,
        }
        high_edge = {
            "close_position_60m": 88.0,
        }
        middle = {
            "close_position_60m": 50.0,
        }

        self.assertEqual(research.candidate_sides(low_edge, mode="range_edge", edge_zone_percent=25), ("long",))
        self.assertEqual(research.candidate_sides(high_edge, mode="range_edge", edge_zone_percent=25), ("short",))
        self.assertEqual(research.candidate_sides(middle, mode="range_edge", edge_zone_percent=25), ())

    def test_scorecard_prefers_samples_with_better_labels(self):
        bars = trending_bars("AAAUSDT", count=120, step=0.08)
        samples = research.build_labeled_samples(
            {"AAAUSDT": bars},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=2,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            candidate_mode="all",
        )
        scorecard = research.train_scorecard(
            samples,
            feature_names=research.FEATURE_NAMES,
            bin_count=4,
            min_bin_samples=2,
            prior_samples=1,
        )
        scored = research.score_samples(samples, scorecard)
        long_scores = [candidate.score for candidate in scored if candidate.sample.side == "long"]
        short_scores = [candidate.score for candidate in scored if candidate.sample.side == "short"]

        self.assertGreater(sum(long_scores) / len(long_scores), sum(short_scores) / len(short_scores))

    def test_scored_portfolio_backtest_records_real_trades(self):
        bars = trending_bars("AAAUSDT", count=120, step=0.08)
        samples = research.build_labeled_samples(
            {"AAAUSDT": bars},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            candidate_mode="all",
        )
        scorecard = research.train_scorecard(
            samples,
            feature_names=research.FEATURE_NAMES,
            bin_count=4,
            min_bin_samples=2,
            prior_samples=1,
        )
        profile = research.LearnedTradingProfile(
            lookback_minutes=60,
            label_horizon_minutes=10,
            score_threshold=scorecard.global_mean_score,
            target_percent=0.2,
            stop_percent=0.4,
            max_hold_minutes=10,
            fee_bps=4,
            slippage_bps=3,
            enabled=True,
        )

        result = research.run_scored_portfolio_backtest(
            samples,
            {"AAAUSDT": bars},
            scorecard=scorecard,
            profile=profile,
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertGreater(result["summary"]["trade_count"], 0)
        self.assertIn("score", result["trades"][0])
        self.assertIn(result["trades"][0]["exit_reason"], {"take_profit", "stop_loss", "max_hold_exit", "data_end"})

    def test_disabled_profile_does_not_trade(self):
        bars = trending_bars("AAAUSDT", count=120, step=0.08)
        samples = research.build_labeled_samples(
            {"AAAUSDT": bars},
            lookback_minutes=60,
            horizon_minutes=10,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            regime=research.RangeRegimeConfig(enabled=False),
            candidate_mode="all",
        )
        scorecard = research.train_scorecard(
            samples,
            feature_names=research.FEATURE_NAMES,
            bin_count=4,
            min_bin_samples=2,
            prior_samples=1,
        )
        profile = research.LearnedTradingProfile(
            lookback_minutes=60,
            label_horizon_minutes=10,
            score_threshold=0.0,
            target_percent=0.2,
            stop_percent=0.4,
            max_hold_minutes=10,
            fee_bps=4,
            slippage_bps=3,
            enabled=False,
        )

        result = research.run_scored_portfolio_backtest(
            samples,
            {"AAAUSDT": bars},
            scorecard=scorecard,
            profile=profile,
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertEqual(result["summary"]["trade_count"], 0)

    def test_negative_validation_profile_is_disabled(self):
        bars = trending_bars("AAAUSDT", count=80, step=0.0)
        samples = research.build_labeled_samples(
            {"AAAUSDT": bars},
            lookback_minutes=60,
            horizon_minutes=5,
            stride=5,
            fee_bps=4,
            slippage_bps=3,
            max_samples_per_symbol=0,
            regime=research.RangeRegimeConfig(enabled=False),
            candidate_mode="all",
        )
        scorecard = research.train_scorecard(
            samples,
            feature_names=research.FEATURE_NAMES,
            bin_count=2,
            min_bin_samples=1,
            prior_samples=1,
        )
        profile, _ = research.learn_trading_profile(
            samples,
            {"AAAUSDT": bars},
            scorecard=scorecard,
            base_profile=research.LearnedTradingProfile(
                lookback_minutes=60,
                label_horizon_minutes=5,
                score_threshold=scorecard.global_mean_score,
                target_percent=0.4,
                stop_percent=0.4,
                max_hold_minutes=5,
                fee_bps=4,
                slippage_bps=3,
            ),
            threshold_candidates=[scorecard.global_mean_score],
            target_grid=[0.4],
            stop_grid=[0.4],
            hold_grid=[5],
            min_validation_trades=1,
            max_side_imbalance=1.0,
            initial_capital=30,
            max_open_positions=1,
            max_new_entries_per_minute=1,
            risk_per_trade_fraction=0.01,
            max_notional_fraction=0.5,
        )

        self.assertFalse(profile.enabled)

    def test_trading_profile_score_penalizes_extreme_side_imbalance(self):
        summary = {
            "trade_count": 100,
            "return_percent": 1.0,
            "profit_factor": 1.2,
            "win_rate": 0.55,
            "max_drawdown_percent_of_initial": 1.0,
            "side_counts": {"long": 100},
        }

        balanced_score = research.trading_profile_score(summary, min_trades=10, max_side_imbalance=1.0)
        penalized_score = research.trading_profile_score(summary, min_trades=10, max_side_imbalance=0.7)

        self.assertLess(penalized_score, balanced_score)
        self.assertLess(penalized_score, -999_999)


if __name__ == "__main__":
    unittest.main()
