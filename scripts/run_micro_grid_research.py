"""Research second-level smart grid trading for micro oscillations.

The earlier range research looks for stable support/resistance over tens of
minutes. This script targets a different idea: a coin jumping up and down over
the next few minutes. It reconstructs 1-second bars from Binance aggTrades,
estimates a short-window dynamic center/amplitude, places passive buy-low and
sell-high orders, and stops when the path looks like a real trend instead of a
tradable wave.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from bfa.backtest.models import BacktestBar


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_second_agg_compound_backtest import fetch_zip, load_symbol_seconds, read_aggtrade_zip  # noqa: E402


SECOND_MS = 1_000
BLOCKED_EDGE_REVERSAL_REASONS = {
    "entry_path_too_directional",
}
SOFT_EDGE_REVERSAL_REASONS = {
    "upper_extreme_too_fresh",
    "lower_extreme_too_fresh",
}


@dataclass(frozen=True)
class MicroGridProfile:
    structure_lookback_seconds: int = 600
    band_lookback_seconds: int = 240
    entry_lookback_seconds: int = 60
    signal_stride_seconds: int = 3
    order_wait_seconds: int = 45
    low_quantile: float = 12.0
    high_quantile: float = 88.0
    pivot_blend_weight: float = 0.45
    wick_opportunity_enabled: bool = True
    wick_tail_low_quantile: float = 2.0
    wick_tail_high_quantile: float = 98.0
    min_wick_opportunity_percent: float = 0.75
    min_wick_to_stable_width_ratio: float = 1.65
    bollinger_std_multiplier: float = 2.0
    min_bollinger_width_fraction: float = 0.35
    inventory_q: float = 0.0
    inventory_risk_aversion_gamma: float = 1.0
    inventory_horizon_seconds: int = 60
    grid_layer_count: int = 3
    grid_layer_spacing_fraction: float = 0.35
    grid_layer_size_decay: float = 0.70
    min_filled_grid_layers: int = 1
    min_reservation_edge_fraction: float = -0.12
    max_reservation_edge_fraction: float = 0.50
    dynamic_entry_edge_enabled: bool = False
    dynamic_entry_base_edge_fraction: float = -0.08
    dynamic_entry_max_push_fraction: float = 0.26
    dynamic_entry_flow_push_fraction: float = 0.08
    dynamic_entry_momentum_push_fraction: float = 0.08
    dynamic_entry_volatility_push_fraction: float = 0.05
    dynamic_entry_wick_push_fraction: float = 0.08
    dynamic_entry_continuation_push_fraction: float = 0.05
    dynamic_exit_geometry_enabled: bool = False
    dynamic_exit_stop_widen_fraction: float = 0.14
    dynamic_exit_max_stop_fraction: float = 0.62
    dynamic_exit_target_mean_ratio: float = 0.92
    dynamic_exit_target_quality_ratio: float = 0.08
    dynamic_exit_target_beyond_mean_fraction: float = 0.16
    dynamic_exit_max_target_fraction: float = 1.10
    dynamic_exit_min_target_stop_ratio: float = 0.88
    post_only_entry_gap_bps: float = 0.0
    dynamic_wick_enabled: bool = True
    wick_model_mode: str = "ev"
    wick_entry_quantile: float = 30.0
    wick_stop_quantile: float = 80.0
    wick_target_quantile: float = 62.0
    wick_min_samples: int = 8
    wick_min_success_rate: float = 0.20
    wick_success_fraction: float = 0.22
    wick_training_seconds: int = 900
    wick_event_gap_seconds: int = 6
    wick_ev_max_samples: int = 72
    # Tightened from (5, 0.25) to reduce in-sample overfit of the dynamic
    # wick model. z=0.25 was less than one standard error of shrinkage on the
    # same samples used to fit the model, so EV was systematically overstated
    # on low-sample symbols. min_fills 12 gives a meaningful standard error,
    # z=0.85 is a one-sided ~80% lower confidence bound.
    wick_ev_min_fills: int = 12
    wick_ev_min_fill_rate: float = 0.08
    wick_ev_min_win_rate: float = 0.45
    wick_ev_max_stop_rate: float = 0.22
    wick_ev_max_same_bar_stop_rate: float = 0.25
    wick_ev_min_avg_net_percent: float = 0.04
    wick_ev_confidence_z: float = 0.85
    # Walk-forward validation of the EV model on an out-of-sample slice.
    # Default True in production to suppress in-sample overfit; can be turned
    # off in isolation tests that exercise EV entry-placement behavior only.
    wick_ev_walk_forward_enabled: bool = True
    wick_ev_min_entry_edge_fraction: float = 0.0
    wick_require_positive_ev: bool = False
    wick_min_target_fraction: float = 0.20
    wick_max_target_fraction: float = 0.55
    wick_min_stop_fraction: float = 0.08
    wick_max_stop_fraction: float = 0.26
    wick_min_entry_fraction: float = -0.06
    wick_max_entry_fraction: float = 0.38
    edge_proximity_fraction: float = 0.22
    reversal_filter_enabled: bool = False
    reversal_check_seconds: int = 12
    reversal_momentum_check_seconds: int = 8
    reversal_min_bounce_fraction: float = 0.04
    reversal_max_continuation_fraction: float = 0.08
    reversal_max_adverse_efficiency: float = 0.82
    reversal_min_extreme_age_seconds: int = 1
    reversal_flow_filter_enabled: bool = False
    reversal_min_long_taker_buy_ratio: float = 0.35
    reversal_max_short_taker_buy_ratio: float = 0.65
    precision_entry_enabled: bool = True
    precision_entry_fraction: float = 0.04
    pullback_model_enabled: bool = True
    pullback_fast_ema_seconds: int = 8
    pullback_mid_ema_seconds: int = 21
    pullback_slow_ema_seconds: int = 55
    pullback_stoch_seconds: int = 34
    pullback_stoch_smooth_seconds: int = 3
    pullback_min_quality: float = 0.0
    pullback_entry_shift_fraction: float = 0.08
    pullback_min_size_multiplier: float = 0.35
    pullback_max_trend_bias: float = 0.70
    side_flow_filter_enabled: bool = True
    side_flow_extreme_taker_ratio: float = 0.64
    side_flow_min_pullback_quality: float = 0.58
    side_flow_block_cooldown_seconds: int = 45
    level_fraction: float = 0.78
    drift_projection_seconds: int = 15
    min_width_percent: float = 0.42
    max_width_percent: float = 22.0
    min_width_cost_ratio: float = 2.0
    min_center_crosses: int = 1
    min_turn_count: int = 4
    min_edge_alternations: int = 3
    min_reversal_response_rate: float = 0.50
    edge_zone_fraction: float = 0.16
    edge_response_seconds: int = 45
    edge_response_fraction: float = 0.22
    edge_response_max_adverse_fraction: float = 0.12
    post_stop_lookahead_seconds: int = 90
    max_path_efficiency: float = 0.55
    max_drift_to_width: float = 0.60
    trend_pause_path_efficiency: float = 0.72
    trend_pause_drift_to_width: float = 0.75
    trend_pause_close_position: float = 82.0
    max_symbol_losses_per_day: int = 0
    target_fraction: float = 0.76
    target_edge_buffer_fraction: float = 0.06
    target_extension_enabled: bool = True
    target_extension_max_fraction: float = 0.65
    stop_fraction: float = 0.20
    min_reward_percent: float = 0.0
    min_target_net_usdt: float = 0.0
    target_net_filter_notional_usdt: float = 120.0
    min_reward_cost_ratio: float = 1.0
    fee_filter_leverage: float = 10.0
    min_net_margin_reward_percent: float = 0.0
    min_net_notional_reward_percent: float = 0.0
    max_hold_seconds: int = 420
    dynamic_hold_enabled: bool = True
    dynamic_hold_min_seconds: int = 120
    dynamic_hold_multiplier: float = 2.5
    # --- volatility regime adaptive scaling (偵察/快進快出/動態適配) ---
    # The micro leg's stop/target/hold were fixed scalars of the span, which
    # made it either get stopped by noise in high vol or sit dead in low vol.
    # These three vol-regime thresholds (on instantaneous_vol_percent) bucket
    # the regime and apply multipliers so the leg adapts: high vol widens the
    # stop (avoid noise stops) and shortens hold (fast in/out); low vol
    # tightens the width gate (no dead-water entries).
    vol_regime_enabled: bool = True
    vol_regime_low_threshold: float = 0.05    # %/s below this = low vol
    vol_regime_high_threshold: float = 0.15   # %/s above this = high vol
    # multipliers applied to stop/target/hold per regime (1.0 = no change)
    vol_regime_low_stop_mult: float = 0.80
    vol_regime_low_target_mult: float = 0.70
    vol_regime_low_hold_mult: float = 0.60
    vol_regime_high_stop_mult: float = 1.25
    vol_regime_high_target_mult: float = 1.40
    vol_regime_high_hold_mult: float = 0.45  # fast in/out when volatile
    # width gate also adapts: low vol demands a tighter minimum width
    vol_regime_low_min_width_mult: float = 0.6
    vol_regime_high_max_width_mult: float = 1.3
    # --- dynamic spike-depth entry prediction (偵察 + 計算掛單點位) ---
    # Instead of posting at a fixed fraction of the span, scout recent spike
    # depth (max excursion from local mean over a lookback) and post the
    # passive entry at that predicted depth. Volatility clusters (lag-1 autocorr
    # ~0.36 on real data), so recent spike depth is a usable predictor of where
    # the next wick will reach. This lets the leg挂深一點 when the market is
    # spiking and挂淺/不做 when it is dead.
    spike_depth_entry_enabled: bool = True
    spike_depth_lookback_seconds: int = 300  # scout last 5 min of spike depth
    spike_depth_min_percent: float = 0.15   # below this the market is too dead to bother
    spike_depth_max_percent: float = 4.0    # cap to avoid posting absurdly deep
    spike_depth_entry_fraction: float = 0.85  # post at 85% of predicted depth (don't catch the exact tip)
    spike_depth_stop_fraction: float = 1.3   # stop beyond the predicted depth
    spike_depth_target_fraction: float = 0.5  # target: capture half the spike back toward center
    trailing_activate_fraction: float = 2.20
    trailing_lock_fraction: float = 0.35
    trailing_giveback_fraction: float = 0.90
    dynamic_level_planner_enabled: bool = False
    planner_min_recovery_probability: float = 0.55
    planner_wrong_direction_probability: float = 0.55
    planner_vol_entry_multiplier: float = 1.20
    planner_vol_stop_multiplier: float = 2.20
    planner_vol_target_multiplier: float = 2.80
    planner_min_target_stop_ratio: float = 0.82
    planner_max_stop_fraction: float = 0.44
    planner_max_target_fraction: float = 0.68
    planner_history_min_fills: int = 3
    spike_depth_tail_buffer_fraction: float = 0.18
    spike_depth_max_entry_edge_fraction: float = -1.45
    spike_depth_max_stop_fraction: float = 1.20
    reentry_cooldown_seconds: int = 8
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 4.0
    exit_slippage_bps: float = 1.0
    # When True the entry leg is costed as maker (post-only fills). When False
    # (legacy default) the entry leg conservatively carries the taker fee too,
    # which overstates cost for a strategy whose entries are post-only limits.
    # The legacy value is preserved so existing backtests stay reproducible;
    # live can opt into the maker-accurate model.
    entry_maker_cost: bool = False
    # Extra bps added when a post-only entry is reprice-attempted and may slip
    # to taker; only applied when entry_maker_cost is True.
    entry_taker_risk_bps: float = 0.5

    @property
    def round_trip_cost_percent(self) -> float:
        if self.entry_maker_cost:
            entry_fee = max(self.maker_fee_bps, 0.0) + max(self.entry_taker_risk_bps, 0.0)
        else:
            # Legacy model: entry leg charged maker + taker, exit leg slippage.
            # Preserved exactly so existing backtests stay reproducible.
            entry_fee = max(self.maker_fee_bps, 0.0) + max(self.taker_fee_bps, 0.0)
        return (entry_fee + max(self.exit_slippage_bps, 0.0)) / 100.0

    @property
    def required_history_seconds(self) -> int:
        return max(
            1,
            int(self.structure_lookback_seconds),
            int(self.band_lookback_seconds),
            int(self.entry_lookback_seconds),
        )


@dataclass(frozen=True)
class BandSnapshot:
    lower: float
    upper: float
    center: float
    projected_center: float
    width_percent: float
    stable_width_percent: float
    raw_range_percent: float
    wick_tail_range_percent: float
    wick_opportunity: bool
    close_position_percent: float
    amplitude_percent: float
    bollinger_lower: float
    bollinger_upper: float
    bollinger_width_percent: float
    instantaneous_vol_percent: float
    reservation_price: float
    reservation_skew_percent: float


@dataclass(frozen=True)
class MicroGridState:
    signal_index: int
    signal_time: str
    center_price: float
    projected_center_price: float
    lower_price: float
    upper_price: float
    width_percent: float
    close_position_percent: float
    center_cross_count: int
    turn_count: int
    lower_touch_count: int
    upper_touch_count: int
    edge_alternation_count: int
    reversal_response_rate: float
    path_efficiency: float
    drift_percent: float
    drift_to_width: float
    recent_path_efficiency: float
    recent_drift_percent: float
    recent_drift_to_width: float
    amplitude_percent: float
    score: float
    trend_pause: bool
    trend_direction: str | None
    current_price: float = 0.0
    stable_width_percent: float = 0.0
    raw_range_percent: float = 0.0
    wick_tail_range_percent: float = 0.0
    wick_opportunity: bool = False
    instantaneous_vol_percent: float = 0.0
    bollinger_width_percent: float = 0.0
    reservation_price: float = 0.0
    reservation_skew_percent: float = 0.0
    # scouted recent spike depth (max excursion from local mean, %), used by
    # the dynamic spike-depth entry predictor to post at predicted wick depth.
    recent_spike_depth_percent: float = 0.0
    long_entry_edge_fraction: float = 0.04
    short_entry_edge_fraction: float = 0.04
    long_stop_span_fraction: float = 0.20
    short_stop_span_fraction: float = 0.20
    long_target_span_fraction: float = 0.76
    short_target_span_fraction: float = 0.76
    long_wick_sample_count: int = 0
    short_wick_sample_count: int = 0
    long_wick_success_rate: float = 0.0
    short_wick_success_rate: float = 0.0
    long_wick_model: str = "default"
    short_wick_model: str = "default"
    long_wick_fill_count: int = 0
    short_wick_fill_count: int = 0
    long_wick_fill_rate: float = 0.0
    short_wick_fill_rate: float = 0.0
    long_wick_stop_rate: float = 0.0
    short_wick_stop_rate: float = 0.0
    long_wick_same_bar_stop_rate: float = 0.0
    short_wick_same_bar_stop_rate: float = 0.0
    long_wick_win_rate: float = 0.0
    short_wick_win_rate: float = 0.0
    long_wick_recovery_rate: float = 0.0
    short_wick_recovery_rate: float = 0.0
    long_wick_stop_then_target_rate: float = 0.0
    short_wick_stop_then_target_rate: float = 0.0
    long_wick_true_wrong_rate: float = 0.0
    short_wick_true_wrong_rate: float = 0.0
    long_wick_avg_net_percent: float = 0.0
    short_wick_avg_net_percent: float = 0.0
    long_wick_score: float = 0.0
    short_wick_score: float = 0.0
    long_hold_seconds: int = 420
    short_hold_seconds: int = 420
    long_reversal_ready: bool = True
    short_reversal_ready: bool = True
    long_reversal_reason: str = "not_checked"
    short_reversal_reason: str = "not_checked"
    long_entry_reversal_fraction: float = 0.0
    short_entry_reversal_fraction: float = 0.0
    long_entry_continuation_fraction: float = 0.0
    short_entry_continuation_fraction: float = 0.0
    entry_taker_buy_ratio: float = 0.5
    triple_ema_fast: float = 0.0
    triple_ema_mid: float = 0.0
    triple_ema_slow: float = 0.0
    triple_ema_bias: float = 0.0
    stochastic_k: float = 50.0
    stochastic_d: float = 50.0
    stochastic_slope: float = 0.0
    long_pullback_quality: float = 0.0
    short_pullback_quality: float = 0.0
    pullback_model_reason: str = "disabled"


@dataclass(frozen=True)
class GridOrder:
    symbol: str
    side: str
    signal_index: int
    signal_time: str
    entry_price: float
    stop_price: float
    target_price: float
    state: MicroGridState
    reason_codes: list[str]
    max_hold_seconds: int = 420
    size_weight: float = 1.0


@dataclass(frozen=True)
class DynamicLevelPlan:
    entry_edge_fraction: float
    stop_span_fraction: float
    target_span_fraction: float
    hold_seconds: int
    trailing_activate_fraction: float
    trailing_lock_fraction: float
    trailing_giveback_fraction: float
    recovery_probability: float
    wrong_direction_probability: float
    take_profit_probability: float
    mode: str
    reason_codes: list[str]


@dataclass(frozen=True)
class BasketFill:
    order: GridOrder
    fill_time_ms: int


@dataclass(frozen=True)
class AggTradeTick:
    symbol: str
    time_ms: int
    price: float
    quantity: float
    buyer_maker: bool


@dataclass(frozen=True)
class TickStream:
    ticks: list[AggTradeTick]
    time_ms: list[int]


@dataclass
class TickReplaySource:
    symbol: str
    start: date
    end: date
    cache_dir: Path
    daily_streams: dict[date, TickStream] = field(default_factory=dict)
    missing_dates: list[str] = field(default_factory=list)
    zip_bytes: int = 0

    def stream_for_order(self, seconds: list[BacktestBar], order: GridOrder, profile: MicroGridProfile) -> TickStream:
        if not seconds:
            return TickStream(ticks=[], time_ms=[])
        signal_ms = seconds[order.signal_index].open_time
        end_ms = signal_ms + (max(1, profile.order_wait_seconds) + max(1, order.max_hold_seconds) + 2) * SECOND_MS
        return self.stream_for_range(signal_ms, end_ms)

    def stream_for_range(self, start_ms: int, end_ms: int) -> TickStream:
        ticks: list[AggTradeTick] = []
        current = ms_to_date(start_ms)
        end_day = ms_to_date(end_ms)
        while current <= end_day:
            stream = self.load_day(current)
            if stream.ticks:
                start_pos = bisect_left(stream.time_ms, start_ms)
                end_pos = bisect_left(stream.time_ms, end_ms + 1, lo=start_pos)
                ticks.extend(stream.ticks[start_pos:end_pos])
            current += timedelta(days=1)
        if len(ticks) > 1 and ticks[0].time_ms > ticks[-1].time_ms:
            ticks.sort(key=lambda item: item.time_ms)
        return TickStream(ticks=ticks, time_ms=[tick.time_ms for tick in ticks])

    def load_day(self, day: date) -> TickStream:
        if day in self.daily_streams:
            return self.daily_streams[day]
        if day < self.start or day > self.end:
            stream = TickStream(ticks=[], time_ms=[])
            self.daily_streams[day] = stream
            return stream
        try:
            path = fetch_zip(self.symbol, day, self.cache_dir)
        except Exception as exc:  # noqa: BLE001 - keep research payload diagnostic.
            self.missing_dates.append(f"{day.isoformat()}:{type(exc).__name__}:{exc}")
            stream = TickStream(ticks=[], time_ms=[])
            self.daily_streams[day] = stream
            return stream
        self.zip_bytes += path.stat().st_size
        ticks = [
            AggTradeTick(
                symbol=self.symbol.upper(),
                time_ms=int(row["time_ms"]),
                price=float(row["price"]),
                quantity=float(row["quantity"]),
                buyer_maker=bool(row["buyer_maker"]),
            )
            for row in read_aggtrade_zip(path)
        ]
        ticks.sort(key=lambda item: item.time_ms)
        stream = TickStream(ticks=ticks, time_ms=[tick.time_ms for tick in ticks])
        self.daily_streams[day] = stream
        return stream

    def coverage(self) -> dict[str, Any]:
        loaded_dates = sorted(day.isoformat() for day in self.daily_streams if self.daily_streams[day].ticks)
        loaded_ticks = sum(len(stream.ticks) for stream in self.daily_streams.values())
        first_tick = next((stream.ticks[0] for day, stream in sorted(self.daily_streams.items()) if stream.ticks), None)
        last_tick = next((stream.ticks[-1] for day, stream in sorted(self.daily_streams.items(), reverse=True) if stream.ticks), None)
        return {
            "mode": "lazy_candidate_windows",
            "loaded_dates": loaded_dates,
            "loaded_date_count": len(loaded_dates),
            "loaded_ticks": loaded_ticks,
            "zip_bytes": self.zip_bytes,
            "missing_dates": list(self.missing_dates),
            "first_loaded_trade_time": ms_to_iso(first_tick.time_ms) if first_tick else None,
            "last_loaded_trade_time": ms_to_iso(last_tick.time_ms) if last_tick else None,
            "tick_replay_enabled": bool(loaded_ticks),
        }


@dataclass(frozen=True)
class MicroGridTrade:
    symbol: str
    side: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    notional_usdt: float
    initial_risk_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    slippage_usdt: float
    net_pnl_usdt: float
    hold_seconds: int
    mfe_percent: float
    mae_percent: float
    realized_r: float
    exit_reason: str
    reason_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="comma-separated USD-M symbols")
    parser.add_argument("--start-date", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--cache-dir", default="runtime/aggTrades-cache")
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=30.0)
    parser.add_argument("--max-open-positions", type=int, default=2)
    parser.add_argument("--risk-per-trade-fraction", type=float, default=0.01)
    parser.add_argument("--max-notional-fraction", type=float, default=4.0)
    parser.add_argument("--max-margin-fraction", type=float, default=0.4)
    parser.add_argument("--max-leverage", type=float, default=10.0)
    parser.add_argument("--symbol-quality-filter-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--symbol-quality-lookback-hours", type=float, default=72.0)
    parser.add_argument("--symbol-quality-min-samples", type=int, default=3)
    parser.add_argument("--symbol-quality-min-profit-factor", type=float, default=0.75)
    parser.add_argument("--symbol-quality-max-stop-rate", type=float, default=0.65)
    parser.add_argument("--symbol-quality-min-scale", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=1, help="parallel symbol workers for candidate generation")
    parser.add_argument("--lookback-seconds", type=int, default=None, help="backward-compatible alias for --structure-lookback-seconds")
    parser.add_argument("--structure-lookback-seconds", type=int, default=MicroGridProfile.structure_lookback_seconds)
    parser.add_argument("--band-lookback-seconds", type=int, default=MicroGridProfile.band_lookback_seconds)
    parser.add_argument("--entry-lookback-seconds", type=int, default=MicroGridProfile.entry_lookback_seconds)
    parser.add_argument("--signal-stride-seconds", type=int, default=MicroGridProfile.signal_stride_seconds)
    parser.add_argument("--order-wait-seconds", type=int, default=MicroGridProfile.order_wait_seconds)
    parser.add_argument("--max-hold-seconds", type=int, default=MicroGridProfile.max_hold_seconds)
    parser.add_argument("--target-fraction", type=float, default=MicroGridProfile.target_fraction)
    parser.add_argument("--wick-opportunity-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.wick_opportunity_enabled)
    parser.add_argument("--wick-tail-low-quantile", type=float, default=MicroGridProfile.wick_tail_low_quantile)
    parser.add_argument("--wick-tail-high-quantile", type=float, default=MicroGridProfile.wick_tail_high_quantile)
    parser.add_argument("--min-wick-opportunity-percent", type=float, default=MicroGridProfile.min_wick_opportunity_percent)
    parser.add_argument("--min-wick-to-stable-width-ratio", type=float, default=MicroGridProfile.min_wick_to_stable_width_ratio)
    parser.add_argument("--bollinger-std-multiplier", type=float, default=MicroGridProfile.bollinger_std_multiplier)
    parser.add_argument("--min-bollinger-width-fraction", type=float, default=MicroGridProfile.min_bollinger_width_fraction)
    parser.add_argument("--inventory-q", type=float, default=MicroGridProfile.inventory_q)
    parser.add_argument("--inventory-risk-aversion-gamma", type=float, default=MicroGridProfile.inventory_risk_aversion_gamma)
    parser.add_argument("--inventory-horizon-seconds", type=int, default=MicroGridProfile.inventory_horizon_seconds)
    parser.add_argument("--grid-layer-count", type=int, default=MicroGridProfile.grid_layer_count)
    parser.add_argument("--grid-layer-spacing-fraction", type=float, default=MicroGridProfile.grid_layer_spacing_fraction)
    parser.add_argument("--grid-layer-size-decay", type=float, default=MicroGridProfile.grid_layer_size_decay)
    parser.add_argument("--min-filled-grid-layers", type=int, default=MicroGridProfile.min_filled_grid_layers)
    parser.add_argument("--min-reservation-edge-fraction", type=float, default=MicroGridProfile.min_reservation_edge_fraction)
    parser.add_argument("--max-reservation-edge-fraction", type=float, default=MicroGridProfile.max_reservation_edge_fraction)
    parser.add_argument("--dynamic-entry-edge-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.dynamic_entry_edge_enabled)
    parser.add_argument("--dynamic-entry-base-edge-fraction", type=float, default=MicroGridProfile.dynamic_entry_base_edge_fraction)
    parser.add_argument("--dynamic-entry-max-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_max_push_fraction)
    parser.add_argument("--dynamic-entry-flow-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_flow_push_fraction)
    parser.add_argument("--dynamic-entry-momentum-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_momentum_push_fraction)
    parser.add_argument("--dynamic-entry-volatility-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_volatility_push_fraction)
    parser.add_argument("--dynamic-entry-wick-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_wick_push_fraction)
    parser.add_argument("--dynamic-entry-continuation-push-fraction", type=float, default=MicroGridProfile.dynamic_entry_continuation_push_fraction)
    parser.add_argument("--dynamic-exit-geometry-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.dynamic_exit_geometry_enabled)
    parser.add_argument("--dynamic-exit-stop-widen-fraction", type=float, default=MicroGridProfile.dynamic_exit_stop_widen_fraction)
    parser.add_argument("--dynamic-exit-max-stop-fraction", type=float, default=MicroGridProfile.dynamic_exit_max_stop_fraction)
    parser.add_argument("--dynamic-exit-target-mean-ratio", type=float, default=MicroGridProfile.dynamic_exit_target_mean_ratio)
    parser.add_argument("--dynamic-exit-target-quality-ratio", type=float, default=MicroGridProfile.dynamic_exit_target_quality_ratio)
    parser.add_argument("--dynamic-exit-target-beyond-mean-fraction", type=float, default=MicroGridProfile.dynamic_exit_target_beyond_mean_fraction)
    parser.add_argument("--dynamic-exit-max-target-fraction", type=float, default=MicroGridProfile.dynamic_exit_max_target_fraction)
    parser.add_argument("--dynamic-exit-min-target-stop-ratio", type=float, default=MicroGridProfile.dynamic_exit_min_target_stop_ratio)
    parser.add_argument("--post-only-entry-gap-bps", type=float, default=MicroGridProfile.post_only_entry_gap_bps)
    parser.add_argument("--min-width-percent", type=float, default=MicroGridProfile.min_width_percent)
    parser.add_argument("--max-width-percent", type=float, default=MicroGridProfile.max_width_percent)
    parser.add_argument("--min-width-cost-ratio", type=float, default=MicroGridProfile.min_width_cost_ratio)
    parser.add_argument("--min-center-crosses", type=int, default=MicroGridProfile.min_center_crosses)
    parser.add_argument("--min-turn-count", type=int, default=MicroGridProfile.min_turn_count)
    parser.add_argument("--min-edge-alternations", type=int, default=MicroGridProfile.min_edge_alternations)
    parser.add_argument("--min-reversal-response-rate", type=float, default=MicroGridProfile.min_reversal_response_rate)
    parser.add_argument("--edge-response-fraction", type=float, default=MicroGridProfile.edge_response_fraction)
    parser.add_argument("--edge-response-max-adverse-fraction", type=float, default=MicroGridProfile.edge_response_max_adverse_fraction)
    parser.add_argument("--max-path-efficiency", type=float, default=MicroGridProfile.max_path_efficiency)
    parser.add_argument("--max-drift-to-width", type=float, default=MicroGridProfile.max_drift_to_width)
    parser.add_argument("--target-extension-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.target_extension_enabled)
    parser.add_argument("--target-extension-max-fraction", type=float, default=MicroGridProfile.target_extension_max_fraction)
    parser.add_argument("--dynamic-wick-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.dynamic_wick_enabled)
    parser.add_argument("--wick-model-mode", choices=["quantile", "ev"], default=MicroGridProfile.wick_model_mode)
    parser.add_argument("--wick-entry-quantile", type=float, default=MicroGridProfile.wick_entry_quantile)
    parser.add_argument("--wick-stop-quantile", type=float, default=MicroGridProfile.wick_stop_quantile)
    parser.add_argument("--wick-target-quantile", type=float, default=MicroGridProfile.wick_target_quantile)
    parser.add_argument("--wick-min-success-rate", type=float, default=MicroGridProfile.wick_min_success_rate)
    parser.add_argument("--wick-training-seconds", type=int, default=MicroGridProfile.wick_training_seconds)
    parser.add_argument("--wick-event-gap-seconds", type=int, default=MicroGridProfile.wick_event_gap_seconds)
    parser.add_argument("--wick-ev-max-samples", type=int, default=MicroGridProfile.wick_ev_max_samples)
    parser.add_argument("--wick-ev-min-fills", type=int, default=MicroGridProfile.wick_ev_min_fills)
    parser.add_argument("--wick-ev-min-fill-rate", type=float, default=MicroGridProfile.wick_ev_min_fill_rate)
    parser.add_argument("--wick-ev-min-win-rate", type=float, default=MicroGridProfile.wick_ev_min_win_rate)
    parser.add_argument("--wick-ev-max-stop-rate", type=float, default=MicroGridProfile.wick_ev_max_stop_rate)
    parser.add_argument("--wick-ev-max-same-bar-stop-rate", type=float, default=MicroGridProfile.wick_ev_max_same_bar_stop_rate)
    parser.add_argument("--wick-ev-min-avg-net-percent", type=float, default=MicroGridProfile.wick_ev_min_avg_net_percent)
    parser.add_argument("--wick-ev-confidence-z", type=float, default=MicroGridProfile.wick_ev_confidence_z)
    parser.add_argument("--wick-ev-min-entry-edge-fraction", type=float, default=MicroGridProfile.wick_ev_min_entry_edge_fraction)
    parser.add_argument("--wick-require-positive-ev", action=argparse.BooleanOptionalAction, default=MicroGridProfile.wick_require_positive_ev)
    parser.add_argument("--wick-min-entry-fraction", type=float, default=MicroGridProfile.wick_min_entry_fraction)
    parser.add_argument("--wick-max-entry-fraction", type=float, default=MicroGridProfile.wick_max_entry_fraction)
    parser.add_argument("--wick-min-stop-fraction", type=float, default=MicroGridProfile.wick_min_stop_fraction)
    parser.add_argument("--wick-max-stop-fraction", type=float, default=MicroGridProfile.wick_max_stop_fraction)
    parser.add_argument("--wick-min-target-fraction", type=float, default=MicroGridProfile.wick_min_target_fraction)
    parser.add_argument("--wick-max-target-fraction", type=float, default=MicroGridProfile.wick_max_target_fraction)
    parser.add_argument("--reversal-filter-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.reversal_filter_enabled)
    parser.add_argument("--reversal-check-seconds", type=int, default=MicroGridProfile.reversal_check_seconds)
    parser.add_argument("--reversal-momentum-check-seconds", type=int, default=MicroGridProfile.reversal_momentum_check_seconds)
    parser.add_argument("--reversal-min-bounce-fraction", type=float, default=MicroGridProfile.reversal_min_bounce_fraction)
    parser.add_argument("--reversal-max-continuation-fraction", type=float, default=MicroGridProfile.reversal_max_continuation_fraction)
    parser.add_argument("--reversal-max-adverse-efficiency", type=float, default=MicroGridProfile.reversal_max_adverse_efficiency)
    parser.add_argument("--reversal-min-extreme-age-seconds", type=int, default=MicroGridProfile.reversal_min_extreme_age_seconds)
    parser.add_argument("--reversal-flow-filter-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.reversal_flow_filter_enabled)
    parser.add_argument("--reversal-min-long-taker-buy-ratio", type=float, default=MicroGridProfile.reversal_min_long_taker_buy_ratio)
    parser.add_argument("--reversal-max-short-taker-buy-ratio", type=float, default=MicroGridProfile.reversal_max_short_taker_buy_ratio)
    parser.add_argument("--pullback-model-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.pullback_model_enabled)
    parser.add_argument("--pullback-fast-ema-seconds", type=int, default=MicroGridProfile.pullback_fast_ema_seconds)
    parser.add_argument("--pullback-mid-ema-seconds", type=int, default=MicroGridProfile.pullback_mid_ema_seconds)
    parser.add_argument("--pullback-slow-ema-seconds", type=int, default=MicroGridProfile.pullback_slow_ema_seconds)
    parser.add_argument("--pullback-stoch-seconds", type=int, default=MicroGridProfile.pullback_stoch_seconds)
    parser.add_argument("--pullback-stoch-smooth-seconds", type=int, default=MicroGridProfile.pullback_stoch_smooth_seconds)
    parser.add_argument("--pullback-min-quality", type=float, default=MicroGridProfile.pullback_min_quality)
    parser.add_argument("--pullback-entry-shift-fraction", type=float, default=MicroGridProfile.pullback_entry_shift_fraction)
    parser.add_argument("--pullback-min-size-multiplier", type=float, default=MicroGridProfile.pullback_min_size_multiplier)
    parser.add_argument("--pullback-max-trend-bias", type=float, default=MicroGridProfile.pullback_max_trend_bias)
    parser.add_argument("--side-flow-filter-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.side_flow_filter_enabled)
    parser.add_argument("--side-flow-extreme-taker-ratio", type=float, default=MicroGridProfile.side_flow_extreme_taker_ratio)
    parser.add_argument("--side-flow-min-pullback-quality", type=float, default=MicroGridProfile.side_flow_min_pullback_quality)
    parser.add_argument("--side-flow-block-cooldown-seconds", type=int, default=MicroGridProfile.side_flow_block_cooldown_seconds)
    parser.add_argument("--precision-entry-fraction", type=float, default=MicroGridProfile.precision_entry_fraction)
    parser.add_argument("--min-reward-percent", type=float, default=MicroGridProfile.min_reward_percent)
    parser.add_argument("--min-target-net-usdt", type=float, default=MicroGridProfile.min_target_net_usdt)
    parser.add_argument("--target-net-filter-notional-usdt", type=float, default=MicroGridProfile.target_net_filter_notional_usdt)
    parser.add_argument("--fee-filter-leverage", type=float, default=MicroGridProfile.fee_filter_leverage)
    parser.add_argument("--min-net-margin-reward-percent", type=float, default=MicroGridProfile.min_net_margin_reward_percent)
    parser.add_argument("--min-net-notional-reward-percent", type=float, default=MicroGridProfile.min_net_notional_reward_percent)
    parser.add_argument("--trailing-activate-fraction", type=float, default=MicroGridProfile.trailing_activate_fraction)
    parser.add_argument("--trailing-lock-fraction", type=float, default=MicroGridProfile.trailing_lock_fraction)
    parser.add_argument("--trailing-giveback-fraction", type=float, default=MicroGridProfile.trailing_giveback_fraction)
    parser.add_argument("--dynamic-hold-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.dynamic_hold_enabled)
    parser.add_argument("--dynamic-hold-min-seconds", type=int, default=MicroGridProfile.dynamic_hold_min_seconds)
    parser.add_argument("--dynamic-hold-multiplier", type=float, default=MicroGridProfile.dynamic_hold_multiplier)
    parser.add_argument("--dynamic-level-planner-enabled", action=argparse.BooleanOptionalAction, default=MicroGridProfile.dynamic_level_planner_enabled)
    parser.add_argument("--planner-min-recovery-probability", type=float, default=MicroGridProfile.planner_min_recovery_probability)
    parser.add_argument("--planner-wrong-direction-probability", type=float, default=MicroGridProfile.planner_wrong_direction_probability)
    parser.add_argument("--planner-vol-entry-multiplier", type=float, default=MicroGridProfile.planner_vol_entry_multiplier)
    parser.add_argument("--planner-vol-stop-multiplier", type=float, default=MicroGridProfile.planner_vol_stop_multiplier)
    parser.add_argument("--planner-vol-target-multiplier", type=float, default=MicroGridProfile.planner_vol_target_multiplier)
    parser.add_argument("--planner-min-target-stop-ratio", type=float, default=MicroGridProfile.planner_min_target_stop_ratio)
    parser.add_argument("--planner-max-stop-fraction", type=float, default=MicroGridProfile.planner_max_stop_fraction)
    parser.add_argument("--planner-max-target-fraction", type=float, default=MicroGridProfile.planner_max_target_fraction)
    parser.add_argument("--planner-history-min-fills", type=int, default=MicroGridProfile.planner_history_min_fills)
    parser.add_argument("--spike-depth-tail-buffer-fraction", type=float, default=MicroGridProfile.spike_depth_tail_buffer_fraction)
    parser.add_argument("--spike-depth-max-entry-edge-fraction", type=float, default=MicroGridProfile.spike_depth_max_entry_edge_fraction)
    parser.add_argument("--spike-depth-max-stop-fraction", type=float, default=MicroGridProfile.spike_depth_max_stop_fraction)
    parser.add_argument("--max-symbol-losses-per-day", type=int, default=MicroGridProfile.max_symbol_losses_per_day)
    parser.add_argument("--max-candidate-trades-per-symbol", type=int, default=0)
    parser.add_argument("--quiet", action="store_true", help="write JSON output without printing the full payload")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        raise SystemExit("--symbols must include at least one symbol")
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise SystemExit("--end-date must be on or after --start-date")

    profile = MicroGridProfile(
        structure_lookback_seconds=args.lookback_seconds if args.lookback_seconds is not None else args.structure_lookback_seconds,
        band_lookback_seconds=args.band_lookback_seconds,
        entry_lookback_seconds=args.entry_lookback_seconds,
        signal_stride_seconds=args.signal_stride_seconds,
        order_wait_seconds=args.order_wait_seconds,
        max_hold_seconds=args.max_hold_seconds,
        target_fraction=args.target_fraction,
        wick_opportunity_enabled=args.wick_opportunity_enabled,
        wick_tail_low_quantile=args.wick_tail_low_quantile,
        wick_tail_high_quantile=args.wick_tail_high_quantile,
        min_wick_opportunity_percent=args.min_wick_opportunity_percent,
        min_wick_to_stable_width_ratio=args.min_wick_to_stable_width_ratio,
        bollinger_std_multiplier=args.bollinger_std_multiplier,
        min_bollinger_width_fraction=args.min_bollinger_width_fraction,
        inventory_q=args.inventory_q,
        inventory_risk_aversion_gamma=args.inventory_risk_aversion_gamma,
        inventory_horizon_seconds=args.inventory_horizon_seconds,
        grid_layer_count=args.grid_layer_count,
        grid_layer_spacing_fraction=args.grid_layer_spacing_fraction,
        grid_layer_size_decay=args.grid_layer_size_decay,
        min_filled_grid_layers=args.min_filled_grid_layers,
        min_reservation_edge_fraction=args.min_reservation_edge_fraction,
        max_reservation_edge_fraction=args.max_reservation_edge_fraction,
        dynamic_entry_edge_enabled=args.dynamic_entry_edge_enabled,
        dynamic_entry_base_edge_fraction=args.dynamic_entry_base_edge_fraction,
        dynamic_entry_max_push_fraction=args.dynamic_entry_max_push_fraction,
        dynamic_entry_flow_push_fraction=args.dynamic_entry_flow_push_fraction,
        dynamic_entry_momentum_push_fraction=args.dynamic_entry_momentum_push_fraction,
        dynamic_entry_volatility_push_fraction=args.dynamic_entry_volatility_push_fraction,
        dynamic_entry_wick_push_fraction=args.dynamic_entry_wick_push_fraction,
        dynamic_entry_continuation_push_fraction=args.dynamic_entry_continuation_push_fraction,
        dynamic_exit_geometry_enabled=args.dynamic_exit_geometry_enabled,
        dynamic_exit_stop_widen_fraction=args.dynamic_exit_stop_widen_fraction,
        dynamic_exit_max_stop_fraction=args.dynamic_exit_max_stop_fraction,
        dynamic_exit_target_mean_ratio=args.dynamic_exit_target_mean_ratio,
        dynamic_exit_target_quality_ratio=args.dynamic_exit_target_quality_ratio,
        dynamic_exit_target_beyond_mean_fraction=args.dynamic_exit_target_beyond_mean_fraction,
        dynamic_exit_max_target_fraction=args.dynamic_exit_max_target_fraction,
        dynamic_exit_min_target_stop_ratio=args.dynamic_exit_min_target_stop_ratio,
        post_only_entry_gap_bps=args.post_only_entry_gap_bps,
        min_width_percent=args.min_width_percent,
        max_width_percent=args.max_width_percent,
        min_width_cost_ratio=args.min_width_cost_ratio,
        min_center_crosses=args.min_center_crosses,
        min_turn_count=args.min_turn_count,
        min_edge_alternations=args.min_edge_alternations,
        min_reversal_response_rate=args.min_reversal_response_rate,
        edge_response_fraction=args.edge_response_fraction,
        edge_response_max_adverse_fraction=args.edge_response_max_adverse_fraction,
        max_path_efficiency=args.max_path_efficiency,
        max_drift_to_width=args.max_drift_to_width,
        target_extension_enabled=args.target_extension_enabled,
        target_extension_max_fraction=args.target_extension_max_fraction,
        dynamic_wick_enabled=args.dynamic_wick_enabled,
        wick_model_mode=args.wick_model_mode,
        wick_entry_quantile=args.wick_entry_quantile,
        wick_stop_quantile=args.wick_stop_quantile,
        wick_target_quantile=args.wick_target_quantile,
        wick_min_success_rate=args.wick_min_success_rate,
        wick_training_seconds=args.wick_training_seconds,
        wick_event_gap_seconds=args.wick_event_gap_seconds,
        wick_ev_max_samples=args.wick_ev_max_samples,
        wick_ev_min_fills=args.wick_ev_min_fills,
        wick_ev_min_fill_rate=args.wick_ev_min_fill_rate,
        wick_ev_min_win_rate=args.wick_ev_min_win_rate,
        wick_ev_max_stop_rate=args.wick_ev_max_stop_rate,
        wick_ev_max_same_bar_stop_rate=args.wick_ev_max_same_bar_stop_rate,
        wick_ev_min_avg_net_percent=args.wick_ev_min_avg_net_percent,
        wick_ev_confidence_z=args.wick_ev_confidence_z,
        wick_ev_min_entry_edge_fraction=args.wick_ev_min_entry_edge_fraction,
        wick_require_positive_ev=args.wick_require_positive_ev,
        wick_min_entry_fraction=args.wick_min_entry_fraction,
        wick_max_entry_fraction=args.wick_max_entry_fraction,
        wick_min_stop_fraction=args.wick_min_stop_fraction,
        wick_max_stop_fraction=args.wick_max_stop_fraction,
        wick_min_target_fraction=args.wick_min_target_fraction,
        wick_max_target_fraction=args.wick_max_target_fraction,
        reversal_filter_enabled=args.reversal_filter_enabled,
        reversal_check_seconds=args.reversal_check_seconds,
        reversal_momentum_check_seconds=args.reversal_momentum_check_seconds,
        reversal_min_bounce_fraction=args.reversal_min_bounce_fraction,
        reversal_max_continuation_fraction=args.reversal_max_continuation_fraction,
        reversal_max_adverse_efficiency=args.reversal_max_adverse_efficiency,
        reversal_min_extreme_age_seconds=args.reversal_min_extreme_age_seconds,
        reversal_flow_filter_enabled=args.reversal_flow_filter_enabled,
        reversal_min_long_taker_buy_ratio=args.reversal_min_long_taker_buy_ratio,
        reversal_max_short_taker_buy_ratio=args.reversal_max_short_taker_buy_ratio,
        pullback_model_enabled=args.pullback_model_enabled,
        pullback_fast_ema_seconds=args.pullback_fast_ema_seconds,
        pullback_mid_ema_seconds=args.pullback_mid_ema_seconds,
        pullback_slow_ema_seconds=args.pullback_slow_ema_seconds,
        pullback_stoch_seconds=args.pullback_stoch_seconds,
        pullback_stoch_smooth_seconds=args.pullback_stoch_smooth_seconds,
        pullback_min_quality=args.pullback_min_quality,
        pullback_entry_shift_fraction=args.pullback_entry_shift_fraction,
        pullback_min_size_multiplier=args.pullback_min_size_multiplier,
        pullback_max_trend_bias=args.pullback_max_trend_bias,
        side_flow_filter_enabled=args.side_flow_filter_enabled,
        side_flow_extreme_taker_ratio=args.side_flow_extreme_taker_ratio,
        side_flow_min_pullback_quality=args.side_flow_min_pullback_quality,
        side_flow_block_cooldown_seconds=args.side_flow_block_cooldown_seconds,
        precision_entry_fraction=args.precision_entry_fraction,
        min_reward_percent=args.min_reward_percent,
        min_target_net_usdt=args.min_target_net_usdt,
        target_net_filter_notional_usdt=args.target_net_filter_notional_usdt,
        fee_filter_leverage=args.fee_filter_leverage,
        min_net_margin_reward_percent=args.min_net_margin_reward_percent,
        min_net_notional_reward_percent=args.min_net_notional_reward_percent,
        trailing_activate_fraction=args.trailing_activate_fraction,
        trailing_lock_fraction=args.trailing_lock_fraction,
        trailing_giveback_fraction=args.trailing_giveback_fraction,
        dynamic_hold_enabled=args.dynamic_hold_enabled,
        dynamic_hold_min_seconds=args.dynamic_hold_min_seconds,
        dynamic_hold_multiplier=args.dynamic_hold_multiplier,
        dynamic_level_planner_enabled=args.dynamic_level_planner_enabled,
        planner_min_recovery_probability=args.planner_min_recovery_probability,
        planner_wrong_direction_probability=args.planner_wrong_direction_probability,
        planner_vol_entry_multiplier=args.planner_vol_entry_multiplier,
        planner_vol_stop_multiplier=args.planner_vol_stop_multiplier,
        planner_vol_target_multiplier=args.planner_vol_target_multiplier,
        planner_min_target_stop_ratio=args.planner_min_target_stop_ratio,
        planner_max_stop_fraction=args.planner_max_stop_fraction,
        planner_max_target_fraction=args.planner_max_target_fraction,
        planner_history_min_fills=args.planner_history_min_fills,
        spike_depth_tail_buffer_fraction=args.spike_depth_tail_buffer_fraction,
        spike_depth_max_entry_edge_fraction=args.spike_depth_max_entry_edge_fraction,
        spike_depth_max_stop_fraction=args.spike_depth_max_stop_fraction,
        max_symbol_losses_per_day=args.max_symbol_losses_per_day,
    )
    coverage: dict[str, Any] = {}
    cache_dir = Path(args.cache_dir)

    candidate_trades: list[MicroGridTrade] = []
    scan_diagnostics: dict[str, Any] = {}
    order_stats = empty_order_stats()
    worker_count = max(1, min(int(args.workers), len(symbols), os.cpu_count() or 1))
    started_at = time.perf_counter()
    if worker_count <= 1:
        symbol_results = [
            run_symbol_candidate_job(
                symbol,
                start.isoformat(),
                end.isoformat(),
                str(cache_dir),
                profile,
                args.max_candidate_trades_per_symbol,
            )
            for symbol in symbols
        ]
    else:
        symbol_results = []
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    run_symbol_candidate_job,
                    symbol,
                    start.isoformat(),
                    end.isoformat(),
                    str(cache_dir),
                    profile,
                    args.max_candidate_trades_per_symbol,
                )
                for symbol in symbols
            ]
            for future in as_completed(futures):
                symbol_results.append(future.result())
        symbol_results.sort(key=lambda item: symbols.index(item["symbol"]))
    scan_seconds = time.perf_counter() - started_at
    for result in symbol_results:
        symbol = str(result["symbol"])
        trades = result["trades"]
        diagnostics = result["diagnostics"]
        symbol_order_stats = result["order_stats"]
        candidate_trades.extend(trades)
        scan_diagnostics[symbol] = diagnostics
        merge_order_stats(order_stats, symbol_order_stats)
        coverage[symbol] = result["coverage"]

    replay = replay_portfolio(
        candidate_trades,
        profile=profile,
        initial_capital=args.initial_capital,
        max_open_positions=args.max_open_positions,
        risk_per_trade_fraction=args.risk_per_trade_fraction,
        max_notional_fraction=args.max_notional_fraction,
        max_margin_fraction=args.max_margin_fraction,
        max_leverage=args.max_leverage,
        symbol_quality_filter_enabled=args.symbol_quality_filter_enabled,
        symbol_quality_lookback_hours=args.symbol_quality_lookback_hours,
        symbol_quality_min_samples=args.symbol_quality_min_samples,
        symbol_quality_min_profit_factor=args.symbol_quality_min_profit_factor,
        symbol_quality_max_stop_rate=args.symbol_quality_max_stop_rate,
        symbol_quality_min_scale=args.symbol_quality_min_scale,
    )
    payload = {
        "schema": "bfa_micro_grid_research_v1",
        "method": {
            "data_source": "Binance USD-M public daily aggTrades for tick-order fill/exit replay plus continuous 1-second OHLCV bars for signal features",
            "signal": "second-level short-window dynamic band, edge alternation/response, center-cross count, turn count, drift-vs-width, and trend-pause filter",
            "orders": "when a micro oscillation passes, place both passive low-buy and high-short orders near predicted wick zones; unfilled orders expire quickly",
            "exit": "ride the oscillation toward the opposite band, then target, stop beyond local wick zone, cost-aware trailing lock, or max-hold failsafe",
            "sizing": "portfolio replay scales notional by risk, max notional, margin x leverage caps, pullback quality, and optional rolling per-symbol trade quality; leverage changes margin efficiency, not price edge",
            "intent": "research a smart-grid micro-oscillation supplement: second/tick data captures information, while trades may hold across a full multi-second or multi-minute wave",
        },
        "symbols": symbols,
        "window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "inclusive_days": (end - start).days + 1,
        },
        "profile": asdict(profile),
        "coverage": coverage,
        "performance": {
            "symbol_worker_count": worker_count,
            "candidate_generation_seconds": round(scan_seconds, 6),
        },
        "scan_diagnostics": scan_diagnostics,
        "candidate_order_stats": order_stats,
        "candidate_trade_summary": summarize_trades(candidate_trades, initial_capital=args.initial_capital),
        "portfolio_summary": replay["summary"],
        "failure_summary": failure_summary(replay["trades"], profile=profile),
        "trades": replay["trades"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.quiet:
        print(json.dumps({"output": str(output), "portfolio_summary": replay["summary"]}, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def run_symbol_candidate_job(
    symbol: str,
    start_date: str,
    end_date: str,
    cache_dir: str,
    profile: MicroGridProfile,
    max_candidate_trades: int,
) -> dict[str, Any]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    cache_path = Path(cache_dir)
    seconds, coverage = load_symbol_seconds(symbol, start, end, cache_path)
    tick_source = TickReplaySource(symbol=symbol, start=start, end=end, cache_dir=cache_path)
    trades, diagnostics, order_stats = generate_symbol_candidate_trades(
        symbol,
        seconds,
        tick_source=tick_source,
        profile=profile,
        max_candidate_trades=max_candidate_trades,
    )
    coverage["tick_stream"] = tick_source.coverage()
    return {
        "symbol": symbol,
        "coverage": coverage,
        "trades": trades,
        "diagnostics": diagnostics,
        "order_stats": order_stats,
    }


def generate_symbol_candidate_trades(
    symbol: str,
    seconds: list[BacktestBar],
    *,
    tick_stream: TickStream | None = None,
    tick_source: TickReplaySource | None = None,
    profile: MicroGridProfile,
    max_candidate_trades: int = 0,
) -> tuple[list[MicroGridTrade], dict[str, Any], dict[str, Any]]:
    trades: list[MicroGridTrade] = []
    diagnostics = empty_scan_diagnostics()
    order_stats = empty_order_stats()
    required_history = profile.required_history_seconds
    next_allowed_index = required_history
    side_flow_block_until_index = {"long": -1, "short": -1}
    end_index = len(seconds) - max(profile.max_hold_seconds, profile.order_wait_seconds) - 1
    for index in range(required_history, max(required_history, end_index), max(1, profile.signal_stride_seconds)):
        diagnostics["evaluated_windows"] += 1
        if index < next_allowed_index:
            diagnostics["cooldown_windows"] += 1
            continue
        state, reasons = build_micro_grid_state(seconds, index, profile)
        if state is None:
            for reason in reasons:
                diagnostics["rejection_counts"][reason] = diagnostics["rejection_counts"].get(reason, 0) + 1
            continue
        diagnostics["passed_windows"] += 1
        orders = build_grid_orders(symbol, state, profile)
        orders, side_flow_rejections = apply_side_flow_cooldowns(orders, state, profile, index, side_flow_block_until_index)
        for reason in side_flow_rejections:
            diagnostics["rejection_counts"][reason] = diagnostics["rejection_counts"].get(reason, 0) + 1
        if not orders:
            reasons = grid_order_rejection_reasons(state, profile)
            for reason in reasons or ["no_valid_grid_orders"]:
                diagnostics["rejection_counts"][reason] = diagnostics["rejection_counts"].get(reason, 0) + 1
            continue
        order_stats["orders_created"] += len(orders)
        filled: list[tuple[int, MicroGridTrade]] = []
        orders_by_side = {
            side: sorted([order for order in orders if order.side == side], key=lambda item: item.entry_price, reverse=side == "long")
            for side in ("long", "short")
        }
        for side_orders in orders_by_side.values():
            if not side_orders:
                continue
            order_tick_stream = tick_stream
            if order_tick_stream is None and tick_source is not None:
                order_tick_stream = tick_source.stream_for_order(seconds, side_orders[0], profile)
            trade, status, fill_index = simulate_grid_basket(
                seconds,
                side_orders,
                profile,
                base_notional_usdt=20.0,
                tick_stream=order_tick_stream,
            )
            order_stats[f"baskets_{status}"] = order_stats.get(f"baskets_{status}", 0) + 1
            if trade is None:
                order_stats["orders_expired"] = order_stats.get("orders_expired", 0) + len(side_orders)
            else:
                filled_layers = filled_layer_count_from_trade(trade)
                status_key = "same_bar_stop" if trade.exit_reason == "same_bar_stop" else "filled"
                order_stats[f"orders_{status_key}"] = order_stats.get(f"orders_{status_key}", 0) + filled_layers
                order_stats["orders_expired"] = order_stats.get("orders_expired", 0) + max(0, len(side_orders) - filled_layers)
            if trade is not None and fill_index is not None:
                filled.append((parse_iso_ms(trade.entry_time), trade))
        if not filled:
            continue
        _, trade = sorted(filled, key=lambda item: trade_selection_key(item[1], item[0]))[0]
        trades.append(trade)
        next_allowed_index = index + profile.reentry_cooldown_seconds
        if max_candidate_trades > 0 and len(trades) >= max_candidate_trades:
            break
    order_stats["fill_rate"] = round(
        (order_stats.get("orders_filled", 0) + order_stats.get("orders_same_bar_stop", 0)) / order_stats["orders_created"],
        8,
    ) if order_stats["orders_created"] else 0.0
    diagnostics["passed_rate"] = round(diagnostics["passed_windows"] / diagnostics["evaluated_windows"], 8) if diagnostics["evaluated_windows"] else 0.0
    diagnostics["rejection_counts"] = dict(sorted(diagnostics["rejection_counts"].items(), key=lambda item: item[1], reverse=True))
    return trades, diagnostics, order_stats


def apply_side_flow_cooldowns(
    orders: list[GridOrder],
    state: MicroGridState,
    profile: MicroGridProfile,
    index: int,
    side_flow_block_until_index: dict[str, int],
) -> tuple[list[GridOrder], list[str]]:
    if not profile.side_flow_filter_enabled:
        return orders, []
    rejections: list[str] = []
    kept: list[GridOrder] = []
    cooldown = max(0, int(profile.side_flow_block_cooldown_seconds))
    stride = max(1, int(profile.signal_stride_seconds))
    cooldown_steps = max(1, math.ceil(cooldown / stride))
    for order in orders:
        if index < side_flow_block_until_index.get(order.side, -1):
            rejections.append(f"{order.side}_side_flow_cooldown")
            continue
        if side_flow_blocks_order(order.side, state, profile):
            side_flow_block_until_index[order.side] = max(
                side_flow_block_until_index.get(order.side, -1),
                index + cooldown_steps * stride,
            )
            rejections.append(f"{order.side}_side_flow_against_order")
            continue
        kept.append(order)
    return kept, rejections


def trade_selection_key(trade: MicroGridTrade, entry_ms: int) -> tuple[float, int, int]:
    side_rank = 0 if trade.side == "long" else 1
    return (-trade_selection_score(trade), entry_ms, side_rank)


def trade_selection_score(trade: MicroGridTrade) -> float:
    values = reason_code_map(trade.reason_codes)
    quality_scale, _quality_reasons = micro_trade_quality_scale_from_reason_codes(trade.reason_codes)
    if quality_scale <= 0:
        return -1_000_000.0
    side = trade.side
    pullback_key = "long_pullback_quality" if side == "long" else "short_pullback_quality"
    pullback_quality = code_float(values, pullback_key, 0.0)
    reversal_ready = 1.0 if values.get("edge_reversal_ready") == "True" else 0.0
    entry_reversal = code_float(values, "entry_reversal_fraction", 0.0)
    entry_continuation = code_float(values, "entry_continuation_fraction", 0.0)
    wick_success = code_float(values, "wick_success_rate", 0.0)
    wick_score = code_float(values, "wick_score", 0.0)
    net_reward = code_float(values, "net_notional_reward_percent", 0.0)
    stop_fraction = code_float(values, "stop_span_fraction", 0.0)
    basket_layers = max(1.0, code_float(values, "basket_fill_count", 1.0))
    basket_weight = max(0.01, code_float(values, "basket_size_weight", 0.75))
    entry_edge = code_float(values, "entry_edge_fraction", 0.0)
    raw_score = (
        pullback_quality * 1.6
        + reversal_ready * 0.9
        + min(entry_reversal, 0.6) * 1.2
        + wick_success * 0.6
        + wick_score * 0.5
        + max(net_reward, 0.0) * 1.4
        + min(max(-entry_edge, 0.0), 0.18) * 1.2
        - entry_continuation * 2.4
        - min(basket_layers - 1.0, 2.0) * 0.28
        - max(basket_weight - 0.75, 0.0) * 0.55
        - max(stop_fraction - 0.28, 0.0) * 0.8
    )
    return raw_score * quality_scale


def reason_code_map(reason_codes: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for code in reason_codes:
        if ":" not in code:
            continue
        key, value = code.split(":", 1)
        values[key] = value
    return values


def code_float(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default


def micro_trade_quality_scale_from_reason_codes(reason_codes: list[str]) -> tuple[float, list[str]]:
    return micro_trade_quality_scale_from_values(reason_code_map(reason_codes))


def micro_trade_quality_scale_from_values(values: dict[str, str]) -> tuple[float, list[str]]:
    scale = 1.0
    reasons: list[str] = []

    stable_width = code_float(values, "stable_width_percent", math.inf)
    if stable_width < 0.20:
        return 0.0, ["quality_width_too_narrow"]
    if stable_width < 0.22:
        scale *= 0.55
        reasons.append("quality_width_near_floor")

    edge_reason = str(values.get("edge_reversal_reason") or "")
    if edge_reason in BLOCKED_EDGE_REVERSAL_REASONS:
        return 0.0, [f"quality_edge_reversal_blocked:{edge_reason}"]
    if edge_reason in SOFT_EDGE_REVERSAL_REASONS:
        scale *= 0.65
        reasons.append(f"quality_edge_reversal_fresh:{edge_reason}")

    if "basket_size_weight" in values:
        basket_weight = max(0.01, code_float(values, "basket_size_weight", 0.75))
        if basket_weight > 1.0:
            scale *= 0.25
            reasons.append("quality_basket_weight_extreme")
        elif basket_weight > 0.75:
            scale *= 0.55
            reasons.append("quality_basket_weight_high")

    basket_fill_count = max(1.0, code_float(values, "basket_fill_count", 1.0))
    if basket_fill_count > 1.0:
        scale *= 0.55
        reasons.append("quality_multi_layer_dca")

    wick_avg_net = code_float(values, "wick_avg_net_percent", 0.0)
    if "wick_avg_net_percent" in values:
        if wick_avg_net <= -0.04:
            scale *= 0.35
            reasons.append("quality_wick_ev_negative")
        elif wick_avg_net < 0.04:
            scale *= 0.75
            reasons.append("quality_wick_ev_weak")

    wick_stop_rate = code_float(values, "wick_stop_rate", 0.0)
    if wick_stop_rate > 0.45:
        scale *= 0.35
        reasons.append("quality_wick_stop_rate_extreme")
    elif wick_stop_rate > 0.22:
        scale *= 0.65
        reasons.append("quality_wick_stop_rate_high")

    drift_to_width = code_float(values, "drift_to_width", 0.0)
    if drift_to_width > 0.85:
        scale *= 0.55
        reasons.append("quality_structure_drift_high")
    elif drift_to_width > 0.75:
        scale *= 0.75
        reasons.append("quality_structure_drift_elevated")

    recent_drift = code_float(values, "recent_drift_to_width", 0.0)
    if recent_drift > 1.0:
        scale *= 0.40
        reasons.append("quality_recent_drift_extreme")
    elif recent_drift > 0.80:
        scale *= 0.65
        reasons.append("quality_recent_drift_high")

    return clamp(scale, 0.0, 1.0), reasons or ["quality_clean"]


def load_symbol_tick_stream(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Path,
) -> tuple[TickStream, dict[str, Any]]:
    ticks: list[AggTradeTick] = []
    missing_dates: list[str] = []
    zip_bytes = 0
    current = start
    while current <= end:
        try:
            path = fetch_zip(symbol, current, cache_dir)
        except Exception as exc:  # noqa: BLE001 - keep research payload diagnostic.
            missing_dates.append(f"{current.isoformat()}:{type(exc).__name__}:{exc}")
            current += timedelta(days=1)
            continue
        zip_bytes += path.stat().st_size
        for row in read_aggtrade_zip(path):
            ticks.append(
                AggTradeTick(
                    symbol=symbol.upper(),
                    time_ms=int(row["time_ms"]),
                    price=float(row["price"]),
                    quantity=float(row["quantity"]),
                    buyer_maker=bool(row["buyer_maker"]),
                )
            )
        current += timedelta(days=1)
    ticks.sort(key=lambda item: item.time_ms)
    stream = TickStream(ticks=ticks, time_ms=[tick.time_ms for tick in ticks])
    coverage = {
        "agg_trade_ticks": len(ticks),
        "zip_bytes": zip_bytes,
        "missing_dates": missing_dates,
        "first_trade_time": ms_to_iso(ticks[0].time_ms) if ticks else None,
        "last_trade_time": ms_to_iso(ticks[-1].time_ms) if ticks else None,
        "tick_replay_enabled": bool(ticks),
    }
    return stream, coverage


def build_band_snapshot(window: list[BacktestBar], profile: MicroGridProfile) -> BandSnapshot | None:
    closes = [bar.close for bar in window if bar.close > 0]
    if len(closes) < max(20, int(profile.band_lookback_seconds) // 3):
        return None
    current = window[-1].close
    low_values = [bar.low for bar in window if bar.low > 0]
    high_values = [bar.high for bar in window if bar.high > 0]
    raw_lower = percentile(low_values, profile.low_quantile)
    raw_upper = percentile(high_values, profile.high_quantile)
    tail_lower = percentile(low_values, profile.wick_tail_low_quantile)
    tail_upper = percentile(high_values, profile.wick_tail_high_quantile)
    raw_low = min(low_values) if low_values else 0.0
    raw_high = max(high_values) if high_values else 0.0
    center = percentile(closes, 50)
    preliminary_span = raw_upper - raw_lower
    pivot_noise = max(profile.round_trip_cost_percent * 0.35, 0.018)
    pivot_lows, pivot_highs = pivot_extremes(window, noise_percent=pivot_noise)
    lower = blended_level(raw_lower, pivot_lows, profile.pivot_blend_weight)
    upper = blended_level(raw_upper, pivot_highs, profile.pivot_blend_weight)
    if preliminary_span > 0 and (upper <= lower or lower > center or upper < center):
        lower = raw_lower
        upper = raw_upper
    if lower <= 0 or upper <= lower or current <= 0:
        return None
    stable_span = upper - lower
    stable_width_percent = stable_span / current * 100.0
    raw_range_percent = (raw_high - raw_low) / current * 100.0 if raw_high > raw_low and current > 0 else 0.0
    wick_tail_span = max(0.0, tail_upper - tail_lower)
    wick_tail_range_percent = wick_tail_span / current * 100.0 if current > 0 else 0.0
    wick_ratio = wick_tail_span / stable_span if stable_span > 0 else 0.0
    wick_opportunity = (
        bool(profile.wick_opportunity_enabled)
        and tail_lower > 0
        and tail_upper > tail_lower
        and wick_tail_range_percent >= max(0.0, profile.min_wick_opportunity_percent)
        and wick_ratio >= max(1.0, profile.min_wick_to_stable_width_ratio)
    )
    if wick_opportunity:
        lower = min(lower, tail_lower)
        upper = max(upper, tail_upper)
    span = upper - lower
    close_std = sample_std(closes)
    bb_width = max(close_std * max(0.0, profile.bollinger_std_multiplier), span * max(0.0, profile.min_bollinger_width_fraction))
    bollinger_lower = center - bb_width
    bollinger_upper = center + bb_width
    instantaneous_vol_percent = realized_vol_percent(window)
    horizon_scale = math.sqrt(max(1.0, float(profile.inventory_horizon_seconds)) / max(1.0, float(profile.entry_lookback_seconds)))
    reservation_skew_percent = clamp(profile.inventory_q, -3.0, 3.0) * max(0.0, profile.inventory_risk_aversion_gamma) * instantaneous_vol_percent * horizon_scale
    reservation_price = current * (1.0 - reservation_skew_percent / 100.0)
    slope_per_second = linear_slope(closes)
    band_center = (lower + upper) / 2.0
    drift_shift = slope_per_second * max(0, profile.drift_projection_seconds)
    projected_center = clamp(
        band_center + clamp(drift_shift, -span * 0.18, span * 0.18),
        lower + span * 0.25,
        upper - span * 0.25,
    )
    return BandSnapshot(
        lower=lower,
        upper=upper,
        center=center,
        projected_center=projected_center,
        width_percent=span / current * 100.0,
        stable_width_percent=stable_width_percent,
        raw_range_percent=raw_range_percent,
        wick_tail_range_percent=wick_tail_range_percent,
        wick_opportunity=wick_opportunity,
        close_position_percent=(current - lower) / span * 100.0,
        amplitude_percent=(span / 2.0) / current * 100.0,
        bollinger_lower=bollinger_lower,
        bollinger_upper=bollinger_upper,
        bollinger_width_percent=(bollinger_upper - bollinger_lower) / current * 100.0,
        instantaneous_vol_percent=instantaneous_vol_percent,
        reservation_price=reservation_price,
        reservation_skew_percent=reservation_skew_percent,
    )


def build_pullback_features(
    band_window: list[BacktestBar],
    entry_window: list[BacktestBar],
    lower: float,
    upper: float,
    profile: MicroGridProfile,
) -> dict[str, float | str]:
    default = {
        "triple_ema_fast": 0.0,
        "triple_ema_mid": 0.0,
        "triple_ema_slow": 0.0,
        "triple_ema_bias": 0.0,
        "stochastic_k": 50.0,
        "stochastic_d": 50.0,
        "stochastic_slope": 0.0,
        "long_pullback_quality": 0.0,
        "short_pullback_quality": 0.0,
        "pullback_model_reason": "disabled",
    }
    if not profile.pullback_model_enabled:
        return default
    window = band_window[-max(3, int(profile.pullback_slow_ema_seconds), int(profile.pullback_stoch_seconds)) :]
    closes = [bar.close for bar in window if bar.close > 0]
    if len(closes) < max(3, int(profile.pullback_fast_ema_seconds)):
        return {**default, "pullback_model_reason": "insufficient_pullback_window"}
    current = closes[-1]
    span = upper - lower
    if current <= 0 or span <= 0:
        return {**default, "pullback_model_reason": "invalid_pullback_geometry"}

    fast = ema_last(closes, max(1, int(profile.pullback_fast_ema_seconds)))
    mid = ema_last(closes, max(1, int(profile.pullback_mid_ema_seconds)))
    slow = ema_last(closes, max(1, int(profile.pullback_slow_ema_seconds)))
    ema_spread_percent = (fast - slow) / current * 100.0
    bias_scale = max(profile.round_trip_cost_percent * 2.0, realized_vol_percent(entry_window) * 2.5, 0.03)
    trend_bias = clamp(ema_spread_percent / bias_scale, -1.0, 1.0)
    if fast > mid > slow:
        trend_bias = max(trend_bias, min(1.0, abs(trend_bias) + 0.12))
    elif fast < mid < slow:
        trend_bias = min(trend_bias, -min(1.0, abs(trend_bias) + 0.12))

    stoch_values = stochastic_series(window, max(3, int(profile.pullback_stoch_seconds)))
    stoch_k = stoch_values[-1] if stoch_values else 50.0
    smooth = max(1, int(profile.pullback_stoch_smooth_seconds))
    stoch_d = sum(stoch_values[-smooth:]) / min(smooth, len(stoch_values)) if stoch_values else stoch_k
    stoch_slope = stoch_k - stoch_values[-min(3, len(stoch_values))] if len(stoch_values) >= 2 else 0.0

    close_position = clamp((current - lower) / span, 0.0, 1.0)
    lower_edge = 1.0 - clamp(close_position / 0.35, 0.0, 1.0)
    upper_edge = 1.0 - clamp((1.0 - close_position) / 0.35, 0.0, 1.0)
    oversold_recovery = clamp((35.0 - stoch_k) / 35.0, 0.0, 1.0) * 0.55 + clamp(stoch_slope / 18.0, 0.0, 1.0) * 0.45
    overbought_rejection = clamp((stoch_k - 65.0) / 35.0, 0.0, 1.0) * 0.55 + clamp(-stoch_slope / 18.0, 0.0, 1.0) * 0.45
    trend_cap = max(0.0, float(profile.pullback_max_trend_bias))
    long_trend = 1.0 - clamp(abs(min(0.0, trend_bias)) / max(0.01, trend_cap), 0.0, 1.0) * 0.45
    short_trend = 1.0 - clamp(abs(max(0.0, trend_bias)) / max(0.01, trend_cap), 0.0, 1.0) * 0.45
    long_quality = clamp(lower_edge * 0.36 + oversold_recovery * 0.44 + long_trend * 0.20, 0.0, 1.0)
    short_quality = clamp(upper_edge * 0.36 + overbought_rejection * 0.44 + short_trend * 0.20, 0.0, 1.0)

    return {
        "triple_ema_fast": fast,
        "triple_ema_mid": mid,
        "triple_ema_slow": slow,
        "triple_ema_bias": trend_bias,
        "stochastic_k": stoch_k,
        "stochastic_d": stoch_d,
        "stochastic_slope": stoch_slope,
        "long_pullback_quality": long_quality,
        "short_pullback_quality": short_quality,
        "pullback_model_reason": "ok",
    }


def ema_last(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (max(1, period) + 1.0)
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1.0 - alpha) * current
    return current


def stochastic_series(window: list[BacktestBar], period: int) -> list[float]:
    values: list[float] = []
    lookback = max(2, int(period))
    for index in range(len(window)):
        start = max(0, index + 1 - lookback)
        sample = window[start : index + 1]
        high = max((bar.high for bar in sample if bar.high > 0), default=0.0)
        low = min((bar.low for bar in sample if bar.low > 0), default=0.0)
        close = window[index].close
        if high <= low or close <= 0:
            values.append(values[-1] if values else 50.0)
        else:
            values.append(clamp((close - low) / (high - low) * 100.0, 0.0, 100.0))
    return values


def build_micro_grid_state(
    seconds: list[BacktestBar],
    signal_index: int,
    profile: MicroGridProfile,
) -> tuple[MicroGridState | None, list[str]]:
    required_history = profile.required_history_seconds
    if signal_index < required_history or signal_index >= len(seconds):
        return None, ["insufficient_lookback"]
    structure_window = seconds[signal_index - int(profile.structure_lookback_seconds) : signal_index]
    band_window = seconds[signal_index - int(profile.band_lookback_seconds) : signal_index]
    entry_window = seconds[signal_index - int(profile.entry_lookback_seconds) : signal_index]
    structure_closes = [bar.close for bar in structure_window if bar.close > 0]
    if len(structure_closes) < max(20, int(profile.structure_lookback_seconds) // 3):
        return None, ["insufficient_prices"]
    current = structure_window[-1].close
    band = build_band_snapshot(band_window, profile)
    if band is None or current <= 0:
        return None, ["invalid_band"]
    lower = band.lower
    upper = band.upper
    width_percent = band.width_percent
    drift_percent = percent_delta(structure_window[0].open, structure_window[-1].close)
    drift_to_width = abs(drift_percent) / width_percent if width_percent > 0 else math.inf
    recent = entry_window
    recent_drift_percent = percent_delta(recent[0].open, recent[-1].close)
    recent_path_eff = path_efficiency(recent)
    recent_drift_to_width = abs(recent_drift_percent) / width_percent if width_percent > 0 else math.inf
    path_eff = path_efficiency(structure_window)
    cross_count = center_cross_count(structure_closes, center=band.center)
    turns = turn_count(structure_closes, noise_percent=max(profile.round_trip_cost_percent * 0.25, 0.015))
    lower_touches, upper_touches, edge_alternations, response_rate = edge_touch_stats(structure_window, lower, upper, profile)
    wick_model = default_dynamic_wick_model(profile)
    pullback = build_pullback_features(band_window, entry_window, lower, upper, profile)
    long_reversal_ready, short_reversal_ready = True, True
    trend_direction = None
    trend_pause = False
    if path_eff >= profile.trend_pause_path_efficiency and drift_to_width >= profile.trend_pause_drift_to_width:
        if drift_percent > 0 and band.close_position_percent >= profile.trend_pause_close_position:
            trend_pause = True
            trend_direction = "up"
        elif drift_percent < 0 and band.close_position_percent <= 100.0 - profile.trend_pause_close_position:
            trend_pause = True
            trend_direction = "down"
    state = MicroGridState(
        signal_index=signal_index,
        signal_time=seconds[signal_index].open_time_iso,
        center_price=band.center,
        projected_center_price=band.projected_center,
        lower_price=lower,
        upper_price=upper,
        width_percent=width_percent,
        close_position_percent=band.close_position_percent,
        center_cross_count=cross_count,
        turn_count=turns,
        lower_touch_count=lower_touches,
        upper_touch_count=upper_touches,
        edge_alternation_count=edge_alternations,
        reversal_response_rate=response_rate,
        path_efficiency=path_eff,
        drift_percent=drift_percent,
        drift_to_width=drift_to_width,
        recent_path_efficiency=recent_path_eff,
        recent_drift_percent=recent_drift_percent,
        recent_drift_to_width=recent_drift_to_width,
        instantaneous_vol_percent=band.instantaneous_vol_percent,
        bollinger_width_percent=band.bollinger_width_percent,
        reservation_price=band.reservation_price,
        reservation_skew_percent=band.reservation_skew_percent,
        amplitude_percent=band.amplitude_percent,
        score=score_state(
            width_percent=width_percent,
            cross_count=cross_count,
            turns=turns,
            edge_alternations=edge_alternations,
            response_rate=response_rate,
            path_efficiency=path_eff,
            drift_to_width=drift_to_width,
            cost_percent=profile.round_trip_cost_percent,
        ),
        trend_pause=trend_pause,
        trend_direction=trend_direction,
        current_price=current,
        stable_width_percent=band.stable_width_percent,
        raw_range_percent=band.raw_range_percent,
        wick_tail_range_percent=band.wick_tail_range_percent,
        wick_opportunity=band.wick_opportunity,
        long_entry_edge_fraction=wick_model["long"]["entry_edge_fraction"],
        short_entry_edge_fraction=wick_model["short"]["entry_edge_fraction"],
        long_stop_span_fraction=wick_model["long"]["stop_span_fraction"],
        short_stop_span_fraction=wick_model["short"]["stop_span_fraction"],
        long_target_span_fraction=wick_model["long"]["target_span_fraction"],
        short_target_span_fraction=wick_model["short"]["target_span_fraction"],
        long_wick_sample_count=wick_model["long"]["sample_count"],
        short_wick_sample_count=wick_model["short"]["sample_count"],
        long_wick_success_rate=wick_model["long"]["success_rate"],
        short_wick_success_rate=wick_model["short"]["success_rate"],
        long_wick_model=str(wick_model["long"]["model"]),
        short_wick_model=str(wick_model["short"]["model"]),
        long_wick_fill_count=int(wick_model["long"]["fill_count"]),
        short_wick_fill_count=int(wick_model["short"]["fill_count"]),
        long_wick_fill_rate=float(wick_model["long"]["fill_rate"]),
        short_wick_fill_rate=float(wick_model["short"]["fill_rate"]),
        long_wick_stop_rate=float(wick_model["long"]["stop_rate"]),
        short_wick_stop_rate=float(wick_model["short"]["stop_rate"]),
        long_wick_same_bar_stop_rate=float(wick_model["long"]["same_bar_stop_rate"]),
        short_wick_same_bar_stop_rate=float(wick_model["short"]["same_bar_stop_rate"]),
        long_wick_win_rate=float(wick_model["long"]["win_rate"]),
        short_wick_win_rate=float(wick_model["short"]["win_rate"]),
        long_wick_recovery_rate=float(wick_model["long"]["recovery_rate"]),
        short_wick_recovery_rate=float(wick_model["short"]["recovery_rate"]),
        long_wick_stop_then_target_rate=float(wick_model["long"]["stop_then_target_rate"]),
        short_wick_stop_then_target_rate=float(wick_model["short"]["stop_then_target_rate"]),
        long_wick_true_wrong_rate=float(wick_model["long"]["true_wrong_rate"]),
        short_wick_true_wrong_rate=float(wick_model["short"]["true_wrong_rate"]),
        long_wick_avg_net_percent=float(wick_model["long"]["avg_net_percent"]),
        short_wick_avg_net_percent=float(wick_model["short"]["avg_net_percent"]),
        long_wick_score=float(wick_model["long"]["score"]),
        short_wick_score=float(wick_model["short"]["score"]),
        long_reversal_ready=long_reversal_ready,
        short_reversal_ready=short_reversal_ready,
    )
    reasons = state_rejection_reasons(state, profile)
    if reasons:
        return None, reasons
    if profile.dynamic_wick_enabled:
        training_start = max(0, signal_index - max(profile.required_history_seconds, int(profile.wick_training_seconds)))
        training_window = seconds[training_start:signal_index]
        wick_model = fit_dynamic_wick_model(training_window, lower, upper, profile)
    reversal = edge_reversal_readiness_detail(entry_window, lower, upper, profile)
    long_reversal_ready = bool(reversal["long_ready"])
    short_reversal_ready = bool(reversal["short_ready"])
    state = replace(
        state,
        long_entry_edge_fraction=float(wick_model["long"]["entry_edge_fraction"]),
        short_entry_edge_fraction=float(wick_model["short"]["entry_edge_fraction"]),
        long_stop_span_fraction=float(wick_model["long"]["stop_span_fraction"]),
        short_stop_span_fraction=float(wick_model["short"]["stop_span_fraction"]),
        long_target_span_fraction=float(wick_model["long"]["target_span_fraction"]),
        short_target_span_fraction=float(wick_model["short"]["target_span_fraction"]),
        long_wick_sample_count=int(wick_model["long"]["sample_count"]),
        short_wick_sample_count=int(wick_model["short"]["sample_count"]),
        long_wick_success_rate=float(wick_model["long"]["success_rate"]),
        short_wick_success_rate=float(wick_model["short"]["success_rate"]),
        long_wick_model=str(wick_model["long"]["model"]),
        short_wick_model=str(wick_model["short"]["model"]),
        long_wick_fill_count=int(wick_model["long"]["fill_count"]),
        short_wick_fill_count=int(wick_model["short"]["fill_count"]),
        long_wick_fill_rate=float(wick_model["long"]["fill_rate"]),
        short_wick_fill_rate=float(wick_model["short"]["fill_rate"]),
        long_wick_stop_rate=float(wick_model["long"]["stop_rate"]),
        short_wick_stop_rate=float(wick_model["short"]["stop_rate"]),
        long_wick_same_bar_stop_rate=float(wick_model["long"]["same_bar_stop_rate"]),
        short_wick_same_bar_stop_rate=float(wick_model["short"]["same_bar_stop_rate"]),
        long_wick_win_rate=float(wick_model["long"]["win_rate"]),
        short_wick_win_rate=float(wick_model["short"]["win_rate"]),
        long_wick_recovery_rate=float(wick_model["long"]["recovery_rate"]),
        short_wick_recovery_rate=float(wick_model["short"]["recovery_rate"]),
        long_wick_stop_then_target_rate=float(wick_model["long"]["stop_then_target_rate"]),
        short_wick_stop_then_target_rate=float(wick_model["short"]["stop_then_target_rate"]),
        long_wick_true_wrong_rate=float(wick_model["long"]["true_wrong_rate"]),
        short_wick_true_wrong_rate=float(wick_model["short"]["true_wrong_rate"]),
        long_wick_avg_net_percent=float(wick_model["long"]["avg_net_percent"]),
        short_wick_avg_net_percent=float(wick_model["short"]["avg_net_percent"]),
        long_wick_score=float(wick_model["long"]["score"]),
        short_wick_score=float(wick_model["short"]["score"]),
        long_hold_seconds=int(wick_model["long"]["hold_seconds"]),
        short_hold_seconds=int(wick_model["short"]["hold_seconds"]),
        long_reversal_ready=long_reversal_ready,
        short_reversal_ready=short_reversal_ready,
        long_reversal_reason=str(reversal["long_reason"]),
        short_reversal_reason=str(reversal["short_reason"]),
        long_entry_reversal_fraction=float(reversal["long_reversal_fraction"]),
        short_entry_reversal_fraction=float(reversal["short_reversal_fraction"]),
        long_entry_continuation_fraction=float(reversal["long_continuation_fraction"]),
        short_entry_continuation_fraction=float(reversal["short_continuation_fraction"]),
        entry_taker_buy_ratio=float(reversal["taker_buy_ratio"]),
        triple_ema_fast=float(pullback["triple_ema_fast"]),
        triple_ema_mid=float(pullback["triple_ema_mid"]),
        triple_ema_slow=float(pullback["triple_ema_slow"]),
        triple_ema_bias=float(pullback["triple_ema_bias"]),
        stochastic_k=float(pullback["stochastic_k"]),
        stochastic_d=float(pullback["stochastic_d"]),
        stochastic_slope=float(pullback["stochastic_slope"]),
        long_pullback_quality=float(pullback["long_pullback_quality"]),
        short_pullback_quality=float(pullback["short_pullback_quality"]),
        pullback_model_reason=str(pullback["pullback_model_reason"]),
        recent_spike_depth_percent=recent_spike_depth_percent(structure_window, profile),
    )
    return state, []


def state_rejection_reasons(state: MicroGridState, profile: MicroGridProfile) -> list[str]:
    reasons: list[str] = []
    # Width gate adapts to vol regime: low vol demands a tighter min width so
    # the leg does not post dead-water entries; high vol allows wider ranges.
    min_width = profile.min_width_percent
    max_width = profile.max_width_percent
    vol_regime = classify_vol_regime(state.instantaneous_vol_percent, profile)
    if profile.vol_regime_enabled and vol_regime is not None:
        if state.instantaneous_vol_percent < profile.vol_regime_low_threshold:
            min_width = profile.min_width_percent * profile.vol_regime_low_min_width_mult
        elif state.instantaneous_vol_percent > profile.vol_regime_high_threshold:
            max_width = profile.max_width_percent * profile.vol_regime_high_max_width_mult
    if not (min_width <= state.width_percent <= max_width):
        reasons.append("width_outside_profile")
    if profile.round_trip_cost_percent > 0 and state.width_percent / profile.round_trip_cost_percent < profile.min_width_cost_ratio:
        reasons.append("width_does_not_cover_cost")
    if (
        state.center_cross_count < profile.min_center_crosses
        and state.turn_count < profile.min_turn_count * 2
        and state.edge_alternation_count < profile.min_edge_alternations
    ):
        reasons.append("not_enough_center_crosses")
    if state.turn_count < profile.min_turn_count:
        reasons.append("not_enough_turns")
    if state.edge_alternation_count < profile.min_edge_alternations:
        reasons.append("not_enough_edge_alternations")
    if state.reversal_response_rate < profile.min_reversal_response_rate:
        reasons.append("weak_edge_reversal_response")
    if state.path_efficiency > profile.max_path_efficiency:
        reasons.append("path_too_directional")
    if state.drift_to_width > profile.max_drift_to_width:
        reasons.append("drift_too_large_vs_width")
    if state.trend_pause:
        reasons.append(f"trend_pause_{state.trend_direction}")
    return reasons


def recent_spike_depth_percent(window: list[BacktestBar], profile: "MicroGridProfile") -> float:
    """Scout the max price excursion from local mean over the lookback.

    This is the 偵察 step: measure how deep recent wicks reached, so the entry
    can be posted at that predicted depth instead of a fixed span fraction.
    Returns a percent of price (e.g. 1.5 = 1.5% spike). 0.0 if unavailable.
    """
    lookback = max(60, int(profile.spike_depth_lookback_seconds))
    chunk = window[-lookback:]
    if len(chunk) < 30:
        return 0.0
    closes = [b.close for b in chunk if b.close > 0]
    if len(closes) < 30:
        return 0.0
    mean = sum(closes) / len(closes)
    if mean <= 0:
        return 0.0
    # max excursion using highs/lows (captures wicks, not just closes)
    max_dev = 0.0
    for b in chunk:
        if b.high > 0:
            max_dev = max(max_dev, abs(b.high - mean) / mean * 100.0)
        if b.low > 0:
            max_dev = max(max_dev, abs(b.low - mean) / mean * 100.0)
    return max_dev


def classify_vol_regime(instantaneous_vol_percent: float, profile: "MicroGridProfile") -> tuple[float, float, float] | None:
    """Return (stop_mult, target_mult, hold_mult) for the current vol regime.

    The micro leg's geometry was fixed scalars of the span; this lets it adapt:
      - low vol:  tighter stop/target, shorter hold (avoid dead-water entries)
      - high vol: wider stop (avoid noise stops), wider target, much shorter
                  hold (fast in/out before a directional break)
    Returns None when vol-regime scaling is disabled or vol is unavailable.
    """
    if not profile.vol_regime_enabled:
        return None
    if not isinstance(instantaneous_vol_percent, (int, float)):
        return None
    vol = float(instantaneous_vol_percent)
    if vol != vol:  # NaN
        return None
    if vol < profile.vol_regime_low_threshold:
        return (
            profile.vol_regime_low_stop_mult,
            profile.vol_regime_low_target_mult,
            profile.vol_regime_low_hold_mult,
        )
    if vol > profile.vol_regime_high_threshold:
        return (
            profile.vol_regime_high_stop_mult,
            profile.vol_regime_high_target_mult,
            profile.vol_regime_high_hold_mult,
        )
    return (1.0, 1.0, 1.0)  # mid regime: no scaling


def minimum_entry_edge_fraction(profile: MicroGridProfile) -> float:
    lower = profile.min_reservation_edge_fraction
    if profile.dynamic_entry_edge_enabled:
        lower = min(
            lower,
            profile.dynamic_entry_base_edge_fraction - max(0.0, profile.dynamic_entry_max_push_fraction),
            profile.wick_min_entry_fraction,
        )
    return lower


def dynamic_entry_edge_fraction(side: str, state: MicroGridState, profile: MicroGridProfile) -> tuple[float, list[str]]:
    lower = minimum_entry_edge_fraction(profile)
    base = clamp(profile.dynamic_entry_base_edge_fraction, lower, profile.max_reservation_edge_fraction)
    if not profile.dynamic_entry_edge_enabled:
        return base, []

    pressures = dynamic_entry_pressure_components(side, state, profile)

    flow_push = max(0.0, profile.dynamic_entry_flow_push_fraction) * pressures["flow_pressure"]
    momentum_push = max(0.0, profile.dynamic_entry_momentum_push_fraction) * pressures["momentum_pressure"]
    volatility_push = max(0.0, profile.dynamic_entry_volatility_push_fraction) * pressures["volatility_pressure"]
    wick_push = max(0.0, profile.dynamic_entry_wick_push_fraction) * pressures["wick_pressure"]
    continuation_push = max(0.0, profile.dynamic_entry_continuation_push_fraction) * pressures["continuation_pressure"]
    total_push = min(
        max(0.0, profile.dynamic_entry_max_push_fraction),
        flow_push + momentum_push + volatility_push + wick_push + continuation_push,
    )
    edge = clamp(base - total_push, lower, profile.max_reservation_edge_fraction)
    multiplier = abs(edge) / max(abs(base), 1e-9)
    return edge, [
        f"dynamic_entry_enabled:{profile.dynamic_entry_edge_enabled}",
        f"dynamic_entry_base_edge_fraction:{round(base, 6)}",
        f"dynamic_entry_min_edge_fraction:{round(lower, 6)}",
        f"dynamic_entry_flow_pressure:{round(pressures['flow_pressure'], 6)}",
        f"dynamic_entry_flow_push_fraction:{round(flow_push, 6)}",
        f"dynamic_entry_momentum_pressure:{round(pressures['momentum_pressure'], 6)}",
        f"dynamic_entry_momentum_push_fraction:{round(momentum_push, 6)}",
        f"dynamic_entry_volatility_pressure:{round(pressures['volatility_pressure'], 6)}",
        f"dynamic_entry_volatility_push_fraction:{round(volatility_push, 6)}",
        f"dynamic_entry_wick_pressure:{round(pressures['wick_pressure'], 6)}",
        f"dynamic_entry_wick_push_fraction:{round(wick_push, 6)}",
        f"dynamic_entry_continuation_pressure:{round(pressures['continuation_pressure'], 6)}",
        f"dynamic_entry_continuation_push_fraction:{round(continuation_push, 6)}",
        f"dynamic_entry_total_push_fraction:{round(total_push, 6)}",
        f"dynamic_entry_push_multiplier:{round(multiplier, 6)}",
        f"dynamic_entry_model_edge_fraction:{round(edge, 6)}",
    ]


def dynamic_entry_pressure_components(side: str, state: MicroGridState, profile: MicroGridProfile) -> dict[str, float]:
    width = max(abs(state.width_percent), 0.0001)
    if side == "long":
        flow_pressure = clamp((0.50 - state.entry_taker_buy_ratio) / 0.18, 0.0, 1.0)
        directional_drift = max(0.0, -state.recent_drift_percent)
        continuation_fraction = state.long_entry_continuation_fraction
    else:
        flow_pressure = clamp((state.entry_taker_buy_ratio - 0.50) / 0.18, 0.0, 1.0)
        directional_drift = max(0.0, state.recent_drift_percent)
        continuation_fraction = state.short_entry_continuation_fraction

    momentum_pressure = clamp(
        directional_drift / max(width * 0.35, profile.round_trip_cost_percent * 1.5, 0.04),
        0.0,
        1.0,
    )
    volatility_pressure = clamp(
        state.instantaneous_vol_percent / max(width * 0.25, profile.round_trip_cost_percent, 0.03),
        0.0,
        1.0,
    )
    wick_pressure = clamp(
        state.recent_spike_depth_percent / max(width * 0.75, profile.spike_depth_min_percent, 0.01),
        0.0,
        1.0,
    )
    continuation_pressure = clamp(
        continuation_fraction / max(profile.reversal_max_continuation_fraction, 0.02),
        0.0,
        1.0,
    )
    return {
        "flow_pressure": flow_pressure,
        "momentum_pressure": momentum_pressure,
        "volatility_pressure": volatility_pressure,
        "wick_pressure": wick_pressure,
        "continuation_pressure": continuation_pressure,
    }


def dynamic_exit_span_fractions(
    side: str,
    *,
    edge_fraction: float,
    base_stop_fraction: float,
    base_target_fraction: float,
    state: MicroGridState,
    profile: MicroGridProfile,
) -> tuple[float, float, list[str]]:
    if not profile.dynamic_exit_geometry_enabled:
        return base_stop_fraction, base_target_fraction, []
    pressures = dynamic_entry_pressure_components(side, state, profile)
    pullback_quality = clamp(pullback_quality_for_side(side, state), 0.0, 1.0)
    wick_success = clamp(state.long_wick_success_rate if side == "long" else state.short_wick_success_rate, 0.0, 1.0)
    response = clamp(state.reversal_response_rate, 0.0, 1.0)
    chaos = max(
        clamp((state.recent_path_efficiency - 0.55) / 0.35, 0.0, 1.0),
        clamp((state.recent_drift_to_width - max(profile.max_drift_to_width * 0.75, 0.01)) / max(profile.max_drift_to_width, 0.01), 0.0, 1.0),
        clamp((state.drift_to_width - max(profile.max_drift_to_width, 0.01)) / max(profile.max_drift_to_width, 0.01), 0.0, 1.0),
    )
    quality = clamp(
        pullback_quality * 0.28
        + response * 0.28
        + wick_success * 0.16
        + (1.0 - pressures["continuation_pressure"]) * 0.14
        + (1.0 - chaos) * 0.14,
        0.0,
        1.0,
    )
    stop_pressure = clamp(
        pressures["volatility_pressure"] * 0.34
        + pressures["wick_pressure"] * 0.26
        + pressures["momentum_pressure"] * 0.22
        + pressures["flow_pressure"] * 0.18,
        0.0,
        1.0,
    )
    stop_widen = max(0.0, profile.dynamic_exit_stop_widen_fraction) * stop_pressure * (0.70 + quality * 0.30) * (1.0 - chaos * 0.45)
    stop_fraction = max(base_stop_fraction, base_stop_fraction + stop_widen)
    stop_cap = max(
        base_stop_fraction,
        min(profile.dynamic_exit_max_stop_fraction, profile.wick_max_stop_fraction + 0.32),
    )
    stop_fraction = clamp(stop_fraction, profile.wick_min_stop_fraction, stop_cap)

    mean_distance = max(0.0, 0.50 - edge_fraction)
    target_mean_ratio = clamp(
        profile.dynamic_exit_target_mean_ratio + profile.dynamic_exit_target_quality_ratio * quality - 0.08 * chaos,
        0.70,
        1.05,
    )
    beyond_mean = max(0.0, profile.dynamic_exit_target_beyond_mean_fraction) * clamp((quality - 0.68) / 0.32, 0.0, 1.0) * (1.0 - chaos * 0.65)
    target_from_mean = mean_distance * target_mean_ratio + beyond_mean
    target_fraction = max(
        base_target_fraction,
        target_from_mean,
        stop_fraction * max(0.0, profile.dynamic_exit_min_target_stop_ratio),
    )
    target_fraction = clamp(target_fraction, profile.wick_min_target_fraction, min(profile.dynamic_exit_max_target_fraction, profile.wick_max_target_fraction + 0.60))
    return stop_fraction, target_fraction, [
        f"dynamic_exit_geometry_enabled:{profile.dynamic_exit_geometry_enabled}",
        f"dynamic_exit_quality:{round(quality, 6)}",
        f"dynamic_exit_chaos_pressure:{round(chaos, 6)}",
        f"dynamic_exit_stop_pressure:{round(stop_pressure, 6)}",
        f"dynamic_exit_stop_widen_fraction:{round(stop_widen, 6)}",
        f"dynamic_exit_stop_cap_fraction:{round(stop_cap, 6)}",
        f"dynamic_exit_mean_distance_fraction:{round(mean_distance, 6)}",
        f"dynamic_exit_target_mean_ratio:{round(target_mean_ratio, 6)}",
        f"dynamic_exit_beyond_mean_fraction:{round(beyond_mean, 6)}",
        f"dynamic_exit_stop_span_fraction:{round(stop_fraction, 6)}",
        f"dynamic_exit_target_span_fraction:{round(target_fraction, 6)}",
    ]


def build_grid_orders(symbol: str, state: MicroGridState, profile: MicroGridProfile) -> list[GridOrder]:
    span = state.upper_price - state.lower_price
    if span <= 0:
        return []
    half = span / 2.0
    buy_entry = state.projected_center_price - half * profile.level_fraction
    sell_entry = state.projected_center_price + half * profile.level_fraction
    buy_stop_fraction = profile.stop_fraction
    sell_stop_fraction = profile.stop_fraction
    buy_target_fraction = profile.target_fraction
    sell_target_fraction = profile.target_fraction
    buy_hold_seconds = int(profile.max_hold_seconds)
    sell_hold_seconds = int(profile.max_hold_seconds)
    entry_min_edge_fraction = minimum_entry_edge_fraction(profile)
    if profile.dynamic_wick_enabled:
        buy_entry = state.lower_price + span * state.long_entry_edge_fraction
        sell_entry = state.upper_price - span * state.short_entry_edge_fraction
        buy_stop_fraction = state.long_stop_span_fraction
        sell_stop_fraction = state.short_stop_span_fraction
        buy_target_fraction = state.long_target_span_fraction
        sell_target_fraction = state.short_target_span_fraction
        buy_hold_seconds = state.long_hold_seconds
        sell_hold_seconds = state.short_hold_seconds
    elif profile.precision_entry_enabled:
        entry_fraction = clamp(profile.precision_entry_fraction, 0.0, 0.45)
        buy_entry = min(buy_entry, state.lower_price + span * entry_fraction)
        sell_entry = max(sell_entry, state.upper_price - span * entry_fraction)
    buy_edge_fraction = reservation_adjusted_edge_fraction("long", edge_fraction_for_price("long", buy_entry, state), state, profile)
    sell_edge_fraction = reservation_adjusted_edge_fraction("short", edge_fraction_for_price("short", sell_entry, state), state, profile)
    entry_reason_codes: dict[str, list[str]] = {"long": [], "short": []}
    # --- volatility regime adaptive scaling (偵察 + 動態適配 + 快進快出) ---
    # Bucket the instantaneous vol into low/mid/high and rescale stop/target/hold
    # so the leg is not stopped by noise in high vol nor dead in low vol.
    vol_regime = classify_vol_regime(state.instantaneous_vol_percent, profile)
    if profile.vol_regime_enabled and vol_regime is not None:
        stop_mult, target_mult, hold_mult = vol_regime
        buy_stop_fraction *= stop_mult
        sell_stop_fraction *= stop_mult
        buy_target_fraction *= target_mult
        sell_target_fraction *= target_mult
        buy_hold_seconds = max(int(buy_hold_seconds * hold_mult), 1)
        sell_hold_seconds = max(int(sell_hold_seconds * hold_mult), 1)
    # --- dynamic spike-depth entry (偵察近期插針深度 -> 計算掛單點位) ---
    # Post the passive entry at the predicted next-wick depth, derived from
    # the scouted recent spike depth. This replaces the fixed span-fraction
    # entry with a volatility-adapted depth: 挂深一點 when the market is
    # spiking, skip (fall back to band edge) when dead. Stop/target are also
    # rescaled to the predicted depth so the geometry is internally consistent.
    if profile.spike_depth_entry_enabled and state.recent_spike_depth_percent >= profile.spike_depth_min_percent:
        spike_pct = clamp(state.recent_spike_depth_percent, 0.0, profile.spike_depth_max_percent) / 100.0
        # predicted depth as a fraction of span (so it composes with the grid layer math)
        width_frac = state.width_percent / 100.0
        if width_frac > 0:
            depth_in_span = spike_pct / width_frac
            tail_buffer = max(0.0, profile.spike_depth_tail_buffer_fraction)
            spike_entry_cap = min(profile.spike_depth_max_entry_edge_fraction, entry_min_edge_fraction)
            spike_stop_cap = max(profile.spike_depth_max_stop_fraction, profile.wick_min_stop_fraction)
            # Entry is posted just beyond the observed spike depth plus a
            # tail-risk buffer. The buffer is strongest when flow/momentum are
            # still pushing into the wick; this is the SLXUSDT failure mode.
            buy_pressures = dynamic_entry_pressure_components("long", state, profile)
            sell_pressures = dynamic_entry_pressure_components("short", state, profile)
            buy_tail_pressure = clamp(
                buy_pressures["flow_pressure"] * 0.28
                + buy_pressures["momentum_pressure"] * 0.30
                + buy_pressures["volatility_pressure"] * 0.18
                + buy_pressures["wick_pressure"] * 0.14
                + buy_pressures["continuation_pressure"] * 0.10,
                0.0,
                1.0,
            )
            sell_tail_pressure = clamp(
                sell_pressures["flow_pressure"] * 0.28
                + sell_pressures["momentum_pressure"] * 0.30
                + sell_pressures["volatility_pressure"] * 0.18
                + sell_pressures["wick_pressure"] * 0.14
                + sell_pressures["continuation_pressure"] * 0.10,
                0.0,
                1.0,
            )
            buy_spike_entry_edge = -depth_in_span * (profile.spike_depth_entry_fraction + tail_buffer * buy_tail_pressure)
            sell_spike_entry_edge = -depth_in_span * (profile.spike_depth_entry_fraction + tail_buffer * sell_tail_pressure)
            buy_spike_entry_edge = clamp(buy_spike_entry_edge, spike_entry_cap, profile.max_reservation_edge_fraction)
            sell_spike_entry_edge = clamp(sell_spike_entry_edge, spike_entry_cap, profile.max_reservation_edge_fraction)
            spike_stop_frac = min(spike_stop_cap, depth_in_span * profile.spike_depth_stop_fraction * (1.0 + tail_buffer * max(buy_tail_pressure, sell_tail_pressure)))
            spike_target_frac = depth_in_span * profile.spike_depth_target_fraction
            # only override if it posts deeper (more passive) than the current edge
            buy_edge_fraction = min(buy_edge_fraction, buy_spike_entry_edge)
            sell_edge_fraction = min(sell_edge_fraction, sell_spike_entry_edge)
            buy_stop_fraction = max(buy_stop_fraction, spike_stop_frac)
            sell_stop_fraction = max(sell_stop_fraction, spike_stop_frac)
            buy_target_fraction = max(buy_target_fraction, spike_target_frac)
            sell_target_fraction = max(sell_target_fraction, spike_target_frac)
            entry_min_edge_fraction = min(entry_min_edge_fraction, buy_edge_fraction, sell_edge_fraction)
            spike_reasons = [
                f"spike_depth_entry_edge_fraction:{round(min(buy_spike_entry_edge, sell_spike_entry_edge), 6)}",
                f"spike_depth_long_entry_edge_fraction:{round(buy_spike_entry_edge, 6)}",
                f"spike_depth_short_entry_edge_fraction:{round(sell_spike_entry_edge, 6)}",
                f"spike_depth_percent:{round(state.recent_spike_depth_percent, 6)}",
                f"spike_depth_in_span:{round(depth_in_span, 6)}",
                f"spike_depth_tail_buffer_fraction:{round(tail_buffer, 6)}",
                f"spike_depth_long_tail_pressure:{round(buy_tail_pressure, 6)}",
                f"spike_depth_short_tail_pressure:{round(sell_tail_pressure, 6)}",
                f"spike_depth_stop_span_fraction:{round(spike_stop_frac, 6)}",
                f"spike_depth_dynamic_min_edge_fraction:{round(entry_min_edge_fraction, 6)}",
            ]
            entry_reason_codes["long"].extend(spike_reasons)
            entry_reason_codes["short"].extend(spike_reasons)
    if profile.dynamic_entry_edge_enabled:
        long_dynamic_edge, long_dynamic_reasons = dynamic_entry_edge_fraction("long", state, profile)
        short_dynamic_edge, short_dynamic_reasons = dynamic_entry_edge_fraction("short", state, profile)
        long_existing_edge = buy_edge_fraction
        short_existing_edge = sell_edge_fraction
        buy_edge_fraction = min(buy_edge_fraction, long_dynamic_edge)
        sell_edge_fraction = min(sell_edge_fraction, short_dynamic_edge)
        entry_reason_codes["long"].extend(
            [
                *long_dynamic_reasons,
                f"dynamic_entry_existing_edge_fraction:{round(long_existing_edge, 6)}",
                f"dynamic_entry_existing_deeper:{long_existing_edge < long_dynamic_edge}",
                f"dynamic_entry_applied_edge_fraction:{round(buy_edge_fraction, 6)}",
            ]
        )
        entry_reason_codes["short"].extend(
            [
                *short_dynamic_reasons,
                f"dynamic_entry_existing_edge_fraction:{round(short_existing_edge, 6)}",
                f"dynamic_entry_existing_deeper:{short_existing_edge < short_dynamic_edge}",
                f"dynamic_entry_applied_edge_fraction:{round(sell_edge_fraction, 6)}",
            ]
        )
    if profile.dynamic_level_planner_enabled:
        long_plan = dynamic_level_plan(
            "long",
            state,
            profile,
            base_entry_edge_fraction=buy_edge_fraction,
            base_stop_fraction=buy_stop_fraction,
            base_target_fraction=buy_target_fraction,
            base_hold_seconds=buy_hold_seconds,
        )
        short_plan = dynamic_level_plan(
            "short",
            state,
            profile,
            base_entry_edge_fraction=sell_edge_fraction,
            base_stop_fraction=sell_stop_fraction,
            base_target_fraction=sell_target_fraction,
            base_hold_seconds=sell_hold_seconds,
        )
        buy_edge_fraction = long_plan.entry_edge_fraction
        sell_edge_fraction = short_plan.entry_edge_fraction
        buy_stop_fraction = long_plan.stop_span_fraction
        sell_stop_fraction = short_plan.stop_span_fraction
        buy_target_fraction = long_plan.target_span_fraction
        sell_target_fraction = short_plan.target_span_fraction
        buy_hold_seconds = long_plan.hold_seconds
        sell_hold_seconds = short_plan.hold_seconds
    else:
        long_plan = None
        short_plan = None
        buy_edge_fraction = pullback_adjusted_edge_fraction("long", buy_edge_fraction, state, profile)
        sell_edge_fraction = pullback_adjusted_edge_fraction("short", sell_edge_fraction, state, profile)
    if profile.dynamic_entry_edge_enabled:
        entry_reason_codes["long"].append(f"dynamic_entry_post_pullback_edge_fraction:{round(buy_edge_fraction, 6)}")
        entry_reason_codes["short"].append(f"dynamic_entry_post_pullback_edge_fraction:{round(sell_edge_fraction, 6)}")
    grid_range_fraction = dynamic_grid_range_fraction(state, profile)
    target_buffer = span * clamp(profile.target_edge_buffer_fraction, 0.0, 0.35)
    orders: list[GridOrder] = []
    layers = max(1, int(profile.grid_layer_count))
    layer_spacing = grid_range_fraction * max(0.0, profile.grid_layer_spacing_fraction) / max(1, layers - 1)
    seen_entries: set[tuple[str, int]] = set()
    min_edge_fraction = entry_min_edge_fraction
    for side, base_edge_fraction, target_fraction, stop_fraction, hold_seconds, plan, side_entry_reasons in (
        ("long", buy_edge_fraction, buy_target_fraction, buy_stop_fraction, buy_hold_seconds, long_plan, entry_reason_codes["long"]),
        ("short", sell_edge_fraction, sell_target_fraction, sell_stop_fraction, sell_hold_seconds, short_plan, entry_reason_codes["short"]),
    ):
        for layer in range(layers):
            edge_fraction = clamp(
                base_edge_fraction - layer * layer_spacing,
                min_edge_fraction,
                profile.max_reservation_edge_fraction,
            )
            layer_stop_fraction, layer_target_fraction, exit_reason_codes = dynamic_exit_span_fractions(
                side,
                edge_fraction=edge_fraction,
                base_stop_fraction=stop_fraction,
                base_target_fraction=target_fraction,
                state=state,
                profile=profile,
            )
            if side == "long":
                entry = state.lower_price + span * edge_fraction
                target = min(entry + span * layer_target_fraction, state.upper_price - target_buffer)
                stop = entry - span * layer_stop_fraction
            else:
                entry = state.upper_price - span * edge_fraction
                target = max(entry - span * layer_target_fraction, state.lower_price + target_buffer)
                stop = entry + span * layer_stop_fraction
            adjusted_target, target_adjustment = cost_aware_target(side, entry, target, state, profile)
            dedupe_key = (side, round(entry, 10))
            if dedupe_key in seen_entries:
                continue
            seen_entries.add(dedupe_key)
            layer_size = max(0.01, (profile.grid_layer_size_decay ** layer) * pullback_size_multiplier(side, state, profile))
            orders.extend(
                build_single_grid_order(
                    symbol,
                    state,
                    profile,
                    side=side,
                    entry=entry,
                    target=adjusted_target,
                    stop=stop,
                    hold_seconds=hold_seconds,
                    stop_fraction=layer_stop_fraction,
                    target_fraction=layer_target_fraction,
                    target_adjustment=target_adjustment,
                    layer=layer,
                    layer_size=layer_size,
                    edge_fraction=edge_fraction,
                    dynamic_plan=plan,
                    entry_reason_codes=[*side_entry_reasons, *exit_reason_codes],
                )
            )
    return orders


def build_single_grid_order(
    symbol: str,
    state: MicroGridState,
    profile: MicroGridProfile,
    *,
    side: str,
    entry: float,
    target: float,
    stop: float,
    hold_seconds: int,
    stop_fraction: float,
    target_fraction: float,
    target_adjustment: str,
    layer: int,
    layer_size: float,
    edge_fraction: float,
    dynamic_plan: DynamicLevelPlan | None = None,
    entry_reason_codes: list[str] | None = None,
) -> list[GridOrder]:
    reward = (target - entry) if side == "long" else (entry - target)
    risk = (entry - stop) if side == "long" else (stop - entry)
    reward_percent = reward / entry * 100.0 if entry > 0 else 0.0
    net_notional_reward_percent = net_reward_percent_after_cost(reward_percent, profile)
    net_margin_reward_percent = net_margin_reward_percent_after_cost(reward_percent, profile)
    estimated_net_reward_usdt = estimated_target_net_reward_usdt(reward_percent, profile)
    if entry <= 0 or reward <= 0 or risk <= 0:
        return []
    if not is_passive_entry(side, entry, state.current_price, profile):
        return []
    if profile.dynamic_wick_enabled and profile.reversal_filter_enabled:
        ready = state.long_reversal_ready if side == "long" else state.short_reversal_ready
        if not ready:
            return []
    if profile.dynamic_wick_enabled:
        edge_reason = state.long_reversal_reason if side == "long" else state.short_reversal_reason
        if edge_reason in BLOCKED_EDGE_REVERSAL_REASONS:
            return []
    if profile.dynamic_wick_enabled and profile.wick_require_positive_ev:
        model = state.long_wick_model if side == "long" else state.short_wick_model
        avg_net = state.long_wick_avg_net_percent if side == "long" else state.short_wick_avg_net_percent
        if model == "ev" and avg_net < profile.wick_ev_min_avg_net_percent:
            return []
    if profile.pullback_model_enabled and pullback_quality_for_side(side, state) < profile.pullback_min_quality:
        return []
    if profile.round_trip_cost_percent > 0 and reward_percent / profile.round_trip_cost_percent < profile.min_reward_cost_ratio:
        return []
    if net_notional_reward_percent < profile.min_net_notional_reward_percent:
        return []
    if net_margin_reward_percent < profile.min_net_margin_reward_percent:
        return []
    if reward_percent < profile.min_reward_percent:
        return []
    if estimated_net_reward_usdt < profile.min_target_net_usdt:
        return []
    return [
        GridOrder(
            symbol=symbol.upper(),
            side=side,
            signal_index=state.signal_index,
            signal_time=state.signal_time,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            state=state,
            reason_codes=[
                "signal_mode:micro_smart_grid",
                f"grid_layer:{layer}",
                f"grid_layer_size:{round(layer_size, 6)}",
                f"min_filled_grid_layers:{int(profile.min_filled_grid_layers)}",
                f"structure_lookback_seconds:{profile.structure_lookback_seconds}",
                f"band_lookback_seconds:{profile.band_lookback_seconds}",
                f"entry_lookback_seconds:{profile.entry_lookback_seconds}",
                f"grid_width_percent:{round(state.width_percent, 6)}",
                f"bb_width_percent:{round(state.bollinger_width_percent, 6)}",
                f"instantaneous_vol_percent:{round(state.instantaneous_vol_percent, 6)}",
                f"reservation_price:{round(state.reservation_price, 8)}",
                f"reservation_skew_percent:{round(state.reservation_skew_percent, 6)}",
                f"inventory_q:{round(profile.inventory_q, 6)}",
                f"inventory_gamma:{round(profile.inventory_risk_aversion_gamma, 6)}",
                f"post_only_entry_gap_bps:{round(profile.post_only_entry_gap_bps, 6)}",
                f"current_price:{round(state.current_price, 8)}",
                f"stable_width_percent:{round(state.stable_width_percent, 6)}",
                f"raw_range_percent:{round(state.raw_range_percent, 6)}",
                f"wick_tail_range_percent:{round(state.wick_tail_range_percent, 6)}",
                f"wick_opportunity:{state.wick_opportunity}",
                f"center_cross_count:{state.center_cross_count}",
                f"turn_count:{state.turn_count}",
                f"edge_alternation_count:{state.edge_alternation_count}",
                f"reversal_response_rate:{round(state.reversal_response_rate, 6)}",
                f"path_efficiency:{round(state.path_efficiency, 6)}",
                f"drift_to_width:{round(state.drift_to_width, 6)}",
                f"recent_path_efficiency:{round(state.recent_path_efficiency, 6)}",
                f"recent_drift_to_width:{round(state.recent_drift_to_width, 6)}",
                f"precision_entry_enabled:{profile.precision_entry_enabled}",
                f"dynamic_wick_enabled:{profile.dynamic_wick_enabled}",
                f"wick_model:{state.long_wick_model if side == 'long' else state.short_wick_model}",
                f"entry_edge_fraction:{round(edge_fraction, 6)}",
                f"wick_sample_count:{state.long_wick_sample_count if side == 'long' else state.short_wick_sample_count}",
                f"wick_success_rate:{round(state.long_wick_success_rate if side == 'long' else state.short_wick_success_rate, 6)}",
                f"wick_fill_count:{state.long_wick_fill_count if side == 'long' else state.short_wick_fill_count}",
                f"wick_fill_rate:{round(state.long_wick_fill_rate if side == 'long' else state.short_wick_fill_rate, 6)}",
                f"wick_stop_rate:{round(state.long_wick_stop_rate if side == 'long' else state.short_wick_stop_rate, 6)}",
                f"wick_same_bar_stop_rate:{round(state.long_wick_same_bar_stop_rate if side == 'long' else state.short_wick_same_bar_stop_rate, 6)}",
                f"wick_win_rate:{round(state.long_wick_win_rate if side == 'long' else state.short_wick_win_rate, 6)}",
                f"wick_recovery_rate:{round(state.long_wick_recovery_rate if side == 'long' else state.short_wick_recovery_rate, 6)}",
                f"wick_stop_then_target_rate:{round(state.long_wick_stop_then_target_rate if side == 'long' else state.short_wick_stop_then_target_rate, 6)}",
                f"wick_true_wrong_rate:{round(state.long_wick_true_wrong_rate if side == 'long' else state.short_wick_true_wrong_rate, 6)}",
                f"wick_avg_net_percent:{round(state.long_wick_avg_net_percent if side == 'long' else state.short_wick_avg_net_percent, 6)}",
                f"wick_score:{round(state.long_wick_score if side == 'long' else state.short_wick_score, 6)}",
                f"dynamic_hold_seconds:{int(hold_seconds)}",
                f"edge_reversal_ready:{state.long_reversal_ready if side == 'long' else state.short_reversal_ready}",
                f"edge_reversal_reason:{state.long_reversal_reason if side == 'long' else state.short_reversal_reason}",
                f"entry_reversal_fraction:{round(state.long_entry_reversal_fraction if side == 'long' else state.short_entry_reversal_fraction, 6)}",
                f"entry_continuation_fraction:{round(state.long_entry_continuation_fraction if side == 'long' else state.short_entry_continuation_fraction, 6)}",
                f"entry_taker_buy_ratio:{round(state.entry_taker_buy_ratio, 6)}",
                f"triple_ema_fast:{round(state.triple_ema_fast, 8)}",
                f"triple_ema_mid:{round(state.triple_ema_mid, 8)}",
                f"triple_ema_slow:{round(state.triple_ema_slow, 8)}",
                f"triple_ema_bias:{round(state.triple_ema_bias, 6)}",
                f"stochastic_k:{round(state.stochastic_k, 6)}",
                f"stochastic_d:{round(state.stochastic_d, 6)}",
                f"stochastic_slope:{round(state.stochastic_slope, 6)}",
                f"long_pullback_quality:{round(state.long_pullback_quality, 6)}",
                f"short_pullback_quality:{round(state.short_pullback_quality, 6)}",
                f"pullback_size_multiplier:{round(pullback_size_multiplier(side, state, profile), 6)}",
                f"pullback_model_reason:{state.pullback_model_reason}",
                f"stop_span_fraction:{round(stop_fraction, 6)}",
                f"target_span_fraction:{round(target_fraction, 6)}",
                f"target_adjustment:{target_adjustment}",
                f"reward_percent:{round(reward_percent, 6)}",
                f"net_notional_reward_percent:{round(net_notional_reward_percent, 6)}",
                f"fee_filter_leverage:{round(profile.fee_filter_leverage, 6)}",
                f"net_margin_reward_percent:{round(net_margin_reward_percent, 6)}",
                f"estimated_target_net_usdt:{round(estimated_net_reward_usdt, 6)}",
                f"entry_price:{round(entry, 8)}",
                f"target_price:{round(target, 8)}",
                f"stop_price:{round(stop, 8)}",
                *(entry_reason_codes or []),
                *dynamic_level_reason_codes(dynamic_plan),
            ],
            max_hold_seconds=max(1, int(hold_seconds)),
            size_weight=layer_size,
        )
    ]


def grid_order_rejection_reasons(state: MicroGridState, profile: MicroGridProfile) -> list[str]:
    span = state.upper_price - state.lower_price
    if span <= 0:
        return ["invalid_span"]
    orders_without_strict_ev = build_grid_orders(symbol="DIAGUSDT", state=state, profile=replace(profile, wick_require_positive_ev=False))
    if not orders_without_strict_ev:
        reasons = grid_price_or_reward_rejection_reasons(state, profile)
        return reasons or ["price_or_reward_filters"]
    if not profile.wick_require_positive_ev:
        return []
    reasons: list[str] = []
    for side in ("long", "short"):
        model = state.long_wick_model if side == "long" else state.short_wick_model
        avg_net = state.long_wick_avg_net_percent if side == "long" else state.short_wick_avg_net_percent
        entry_fraction = state.long_entry_edge_fraction if side == "long" else state.short_entry_edge_fraction
        same_bar_stop_rate = state.long_wick_same_bar_stop_rate if side == "long" else state.short_wick_same_bar_stop_rate
        if model != "ev":
            continue
        if avg_net < profile.wick_ev_min_avg_net_percent:
            reasons.append(f"{side}_wick_ev_net_too_low")
        elif entry_fraction < profile.wick_ev_min_entry_edge_fraction:
            reasons.append(f"{side}_wick_ev_entry_too_shallow")
        elif same_bar_stop_rate > profile.wick_ev_max_same_bar_stop_rate:
            reasons.append(f"{side}_wick_ev_same_bar_stop_too_high")
    return reasons or ["strict_ev_filtered"]


def grid_price_or_reward_rejection_reasons(state: MicroGridState, profile: MicroGridProfile) -> list[str]:
    span = state.upper_price - state.lower_price
    if span <= 0:
        return ["invalid_span"]
    reasons: list[str] = []
    buy_entry = state.lower_price + span * state.long_entry_edge_fraction if profile.dynamic_wick_enabled else state.projected_center_price - span * profile.level_fraction / 2.0
    sell_entry = state.upper_price - span * state.short_entry_edge_fraction if profile.dynamic_wick_enabled else state.projected_center_price + span * profile.level_fraction / 2.0
    buy_edge_fraction = reservation_adjusted_edge_fraction("long", edge_fraction_for_price("long", buy_entry, state), state, profile)
    sell_edge_fraction = reservation_adjusted_edge_fraction("short", edge_fraction_for_price("short", sell_entry, state), state, profile)
    grid_range_fraction = dynamic_grid_range_fraction(state, profile)
    layers = max(1, int(profile.grid_layer_count))
    layer_spacing = grid_range_fraction * max(0.0, profile.grid_layer_spacing_fraction) / max(1, layers - 1)
    target_buffer = span * clamp(profile.target_edge_buffer_fraction, 0.0, 0.35)
    for side, base_edge_fraction, target_fraction, stop_fraction, hold_seconds in (
        ("long", buy_edge_fraction, state.long_target_span_fraction if profile.dynamic_wick_enabled else profile.target_fraction, state.long_stop_span_fraction if profile.dynamic_wick_enabled else profile.stop_fraction, state.long_hold_seconds if profile.dynamic_wick_enabled else profile.max_hold_seconds),
        ("short", sell_edge_fraction, state.short_target_span_fraction if profile.dynamic_wick_enabled else profile.target_fraction, state.short_stop_span_fraction if profile.dynamic_wick_enabled else profile.stop_fraction, state.short_hold_seconds if profile.dynamic_wick_enabled else profile.max_hold_seconds),
    ):
        for layer in range(layers):
            edge_fraction = clamp(base_edge_fraction - layer * layer_spacing, minimum_entry_edge_fraction(profile), profile.max_reservation_edge_fraction)
            layer_stop_fraction, layer_target_fraction, _exit_reasons = dynamic_exit_span_fractions(
                side,
                edge_fraction=edge_fraction,
                base_stop_fraction=stop_fraction,
                base_target_fraction=target_fraction,
                state=state,
                profile=profile,
            )
            if side == "long":
                entry = state.lower_price + span * edge_fraction
                target = min(entry + span * layer_target_fraction, state.upper_price - target_buffer)
                stop = entry - span * layer_stop_fraction
            else:
                entry = state.upper_price - span * edge_fraction
                target = max(entry - span * layer_target_fraction, state.lower_price + target_buffer)
                stop = entry + span * layer_stop_fraction
            target, _ = cost_aware_target(side, entry, target, state, profile)
            reasons.extend(single_grid_order_rejection_reasons(state, profile, side=side, entry=entry, target=target, stop=stop))
    return sorted(set(reasons))


def single_grid_order_rejection_reasons(
    state: MicroGridState,
    profile: MicroGridProfile,
    *,
    side: str,
    entry: float,
    target: float,
    stop: float,
) -> list[str]:
    reasons: list[str] = []
    reward = (target - entry) if side == "long" else (entry - target)
    risk = (entry - stop) if side == "long" else (stop - entry)
    reward_percent = reward / entry * 100.0 if entry > 0 else 0.0
    net_notional_reward_percent = net_reward_percent_after_cost(reward_percent, profile)
    net_margin_reward_percent = net_margin_reward_percent_after_cost(reward_percent, profile)
    estimated_net_reward_usdt = estimated_target_net_reward_usdt(reward_percent, profile)
    if entry <= 0 or reward <= 0 or risk <= 0:
        reasons.append(f"{side}_invalid_price_geometry")
    if not is_passive_entry(side, entry, state.current_price, profile):
        reasons.append(f"{side}_post_only_not_passive")
    if profile.dynamic_wick_enabled and profile.reversal_filter_enabled:
        ready = state.long_reversal_ready if side == "long" else state.short_reversal_ready
        if not ready:
            reason = state.long_reversal_reason if side == "long" else state.short_reversal_reason
            reasons.append(f"{side}_reversal_not_ready:{reason}")
    if side_flow_blocks_order(side, state, profile):
        reasons.append(f"{side}_side_flow_against_order")
    if profile.pullback_model_enabled and pullback_quality_for_side(side, state) < profile.pullback_min_quality:
        reasons.append(f"{side}_pullback_quality_too_low")
    if profile.round_trip_cost_percent > 0 and reward_percent / profile.round_trip_cost_percent < profile.min_reward_cost_ratio:
        reasons.append(f"{side}_reward_cost_ratio_too_low")
    if net_notional_reward_percent < profile.min_net_notional_reward_percent:
        reasons.append(f"{side}_net_notional_reward_too_low")
    if net_margin_reward_percent < profile.min_net_margin_reward_percent:
        reasons.append(f"{side}_net_margin_reward_too_low")
    if reward_percent < profile.min_reward_percent:
        reasons.append(f"{side}_reward_percent_too_low")
    if estimated_net_reward_usdt < profile.min_target_net_usdt:
        reasons.append(f"{side}_target_net_too_low")
    return reasons


def edge_fraction_for_order(side: str, entry: float, state: MicroGridState) -> float:
    return edge_fraction_for_price(side, entry, state)


def edge_fraction_for_price(side: str, price: float, state: MicroGridState) -> float:
    span = state.upper_price - state.lower_price
    if span <= 0:
        return 0.0
    if side == "long":
        return (price - state.lower_price) / span
    return (state.upper_price - price) / span


def reservation_adjusted_edge_fraction(side: str, base_edge_fraction: float, state: MicroGridState, profile: MicroGridProfile) -> float:
    span = state.upper_price - state.lower_price
    if span <= 0 or abs(profile.inventory_q) <= 1e-12:
        return base_edge_fraction
    reservation_edge_long = edge_fraction_for_price("long", state.reservation_price, state)
    reservation_edge_short = edge_fraction_for_price("short", state.reservation_price, state)
    if side == "long" and profile.inventory_q > 0:
        adjusted = max(base_edge_fraction, reservation_edge_long)
    elif side == "short" and profile.inventory_q < 0:
        adjusted = max(base_edge_fraction, reservation_edge_short)
    else:
        adjusted = base_edge_fraction
    return clamp(adjusted, minimum_entry_edge_fraction(profile), profile.max_reservation_edge_fraction)


def pullback_quality_for_side(side: str, state: MicroGridState) -> float:
    return state.long_pullback_quality if side == "long" else state.short_pullback_quality


def pullback_adjusted_edge_fraction(side: str, base_edge_fraction: float, state: MicroGridState, profile: MicroGridProfile) -> float:
    if not profile.pullback_model_enabled:
        return base_edge_fraction
    quality = pullback_quality_for_side(side, state)
    shift = max(0.0, float(profile.pullback_entry_shift_fraction)) * (1.0 - clamp(quality, 0.0, 1.0))
    model = state.long_wick_model if side == "long" else state.short_wick_model
    min_entry = minimum_entry_edge_fraction(profile)
    ev_min_entry = profile.wick_ev_min_entry_edge_fraction if profile.dynamic_wick_enabled and model == "ev" else min_entry
    lower = max(min_entry, ev_min_entry)
    lower = min(base_edge_fraction, lower)
    return clamp(base_edge_fraction - shift, lower, profile.max_reservation_edge_fraction)


def pullback_size_multiplier(side: str, state: MicroGridState, profile: MicroGridProfile) -> float:
    if not profile.pullback_model_enabled:
        return 1.0
    floor = clamp(float(profile.pullback_min_size_multiplier), 0.01, 1.0)
    quality = clamp(pullback_quality_for_side(side, state), 0.0, 1.0)
    return floor + (1.0 - floor) * quality


def side_flow_blocks_order(side: str, state: MicroGridState, profile: MicroGridProfile) -> bool:
    if not profile.side_flow_filter_enabled:
        return False
    threshold = clamp(profile.side_flow_extreme_taker_ratio, 0.50, 0.95)
    min_quality = clamp(profile.side_flow_min_pullback_quality, 0.0, 1.0)
    if side == "short":
        return state.entry_taker_buy_ratio >= threshold and state.short_pullback_quality < min_quality
    return state.entry_taker_buy_ratio <= 1.0 - threshold and state.long_pullback_quality < min_quality


def planner_min_entry_edge_fraction(profile: MicroGridProfile) -> float:
    if not profile.dynamic_level_planner_enabled:
        return minimum_entry_edge_fraction(profile)
    return min(minimum_entry_edge_fraction(profile), profile.wick_min_entry_fraction)


def dynamic_level_plan(
    side: str,
    state: MicroGridState,
    profile: MicroGridProfile,
    *,
    base_entry_edge_fraction: float,
    base_stop_fraction: float,
    base_target_fraction: float,
    base_hold_seconds: int,
) -> DynamicLevelPlan:
    width = max(state.width_percent, 0.0001)
    vol_fraction = clamp(state.instantaneous_vol_percent / width, 0.0, 0.65)
    bb_fraction = clamp(state.bollinger_width_percent / width, 0.0, 3.0)
    pullback_quality = clamp(pullback_quality_for_side(side, state), 0.0, 1.0)
    reversal_ready = state.long_reversal_ready if side == "long" else state.short_reversal_ready
    reversal_fraction = state.long_entry_reversal_fraction if side == "long" else state.short_entry_reversal_fraction
    continuation_fraction = state.long_entry_continuation_fraction if side == "long" else state.short_entry_continuation_fraction
    wick_success_rate = state.long_wick_success_rate if side == "long" else state.short_wick_success_rate
    wick_score = state.long_wick_score if side == "long" else state.short_wick_score
    wick_avg_net = state.long_wick_avg_net_percent if side == "long" else state.short_wick_avg_net_percent
    wick_stop_rate = state.long_wick_stop_rate if side == "long" else state.short_wick_stop_rate
    same_bar_stop_rate = state.long_wick_same_bar_stop_rate if side == "long" else state.short_wick_same_bar_stop_rate
    wick_fill_count = state.long_wick_fill_count if side == "long" else state.short_wick_fill_count
    wick_win_rate = state.long_wick_win_rate if side == "long" else state.short_wick_win_rate
    wick_recovery_rate = state.long_wick_recovery_rate if side == "long" else state.short_wick_recovery_rate
    wick_stop_then_target_rate = state.long_wick_stop_then_target_rate if side == "long" else state.short_wick_stop_then_target_rate
    wick_true_wrong_rate = state.long_wick_true_wrong_rate if side == "long" else state.short_wick_true_wrong_rate

    response_quality = clamp((state.reversal_response_rate - profile.min_reversal_response_rate) / max(0.05, 1.0 - profile.min_reversal_response_rate), 0.0, 1.0)
    drift_pressure = clamp(max(state.drift_to_width, state.recent_drift_to_width * 0.75) / max(0.01, profile.max_drift_to_width), 0.0, 2.0)
    continuation_pressure = clamp(continuation_fraction / max(0.02, profile.reversal_max_continuation_fraction), 0.0, 2.5)

    formula_take_profit_probability = clamp(
        0.18
        + 0.32 * response_quality
        + 0.22 * pullback_quality
        + 0.16 * clamp(wick_success_rate, 0.0, 1.0)
        + 0.08 * clamp(wick_score, 0.0, 1.0)
        + 0.06 * (1.0 if reversal_ready else 0.0)
        - 0.18 * max(0.0, drift_pressure - 1.0)
        - 0.16 * continuation_pressure,
        0.02,
        0.92,
    )
    formula_recovery_probability = clamp(
        0.12
        + 0.28 * min(reversal_fraction, 0.75)
        + 0.22 * pullback_quality
        + 0.16 * response_quality
        + 0.10 * clamp(wick_success_rate, 0.0, 1.0)
        - 0.18 * continuation_pressure
        - 0.10 * max(0.0, drift_pressure - 1.0),
        0.02,
        0.90,
    )
    formula_wrong_direction_probability = clamp(
        0.18
        + 0.24 * max(0.0, drift_pressure - 0.7)
        + 0.26 * continuation_pressure
        + 0.16 * (0.0 if reversal_ready else 1.0)
        + 0.18 * clamp(wick_stop_rate + same_bar_stop_rate, 0.0, 1.0)
        - 0.18 * pullback_quality
        - 0.12 * response_quality
        - 0.08 * clamp(max(wick_avg_net, 0.0) / max(profile.round_trip_cost_percent, 0.01), 0.0, 1.0),
        0.02,
        0.92,
    )
    history_weight = clamp(
        (float(wick_fill_count) - max(1.0, float(profile.planner_history_min_fills))) / max(1.0, float(profile.wick_ev_max_samples) * 0.35),
        0.0,
        0.75,
    )
    historical_take_profit_probability = clamp(0.70 * wick_win_rate + 0.30 * wick_success_rate, 0.02, 0.92)
    historical_recovery_probability = clamp(0.70 * wick_recovery_rate + 0.30 * wick_stop_then_target_rate, 0.02, 0.90)
    historical_wrong_direction_probability = clamp(0.75 * wick_true_wrong_rate + 0.25 * wick_stop_rate, 0.02, 0.92)
    take_profit_probability = clamp(
        formula_take_profit_probability * (1.0 - history_weight) + historical_take_profit_probability * history_weight,
        0.02,
        0.92,
    )
    recovery_probability = clamp(
        formula_recovery_probability * (1.0 - history_weight) + historical_recovery_probability * history_weight,
        0.02,
        0.90,
    )
    wrong_direction_probability = clamp(
        formula_wrong_direction_probability * (1.0 - history_weight) + historical_wrong_direction_probability * history_weight,
        0.02,
        0.92,
    )
    intervention = clamp((wrong_direction_probability - 0.35) / 0.35, 0.0, 1.0)
    intervention = max(intervention, clamp((0.55 - take_profit_probability) / 0.35, 0.0, 1.0) * 0.65)
    historical_recovery_edge = wick_fill_count >= profile.planner_history_min_fills and wick_recovery_rate >= 0.55 and wick_true_wrong_rate <= 0.35
    historical_target_recovery_edge = historical_recovery_edge and wick_stop_then_target_rate >= 0.30
    historical_reprice_edge = historical_recovery_edge and not historical_target_recovery_edge
    if historical_recovery_edge:
        intervention = max(intervention, 0.35)
    strong_historical_edge = (
        wick_fill_count >= profile.planner_history_min_fills
        and wick_win_rate >= max(0.50, profile.wick_ev_min_win_rate)
        and wick_avg_net >= profile.wick_ev_min_avg_net_percent
        and wick_true_wrong_rate <= 0.30
    )
    if strong_historical_edge:
        intervention = min(intervention, 0.25)

    volatility_entry_add = profile.planner_vol_entry_multiplier * vol_fraction
    recovery_entry_add = (
        0.05 * (1.0 - pullback_quality)
        + 0.06 * max(0.0, wrong_direction_probability - 0.45)
        + 0.05 * history_weight * max(0.0, wick_recovery_rate - wick_true_wrong_rate)
    )
    entry_edge = base_entry_edge_fraction - (volatility_entry_add + recovery_entry_add) * intervention
    entry_edge = clamp(entry_edge, planner_min_entry_edge_fraction(profile), profile.max_reservation_edge_fraction)

    stop_fraction = max(base_stop_fraction, profile.wick_min_stop_fraction)
    recovery_dominant = (
        historical_target_recovery_edge
        or recovery_probability >= profile.planner_min_recovery_probability and recovery_probability >= wrong_direction_probability and wick_stop_then_target_rate >= 0.25
    )
    wrong_direction_dominant = wrong_direction_probability >= profile.planner_wrong_direction_probability and wrong_direction_probability > recovery_probability + 0.10
    if not wrong_direction_dominant and recovery_dominant:
        stop_fraction += (0.08 + profile.planner_vol_stop_multiplier * vol_fraction * 0.45) * intervention
        mode = "recovery_allowed"
    elif wrong_direction_dominant:
        stop_fraction -= 0.05 * intervention
        mode = "wrong_direction_fast_exit"
    elif historical_reprice_edge:
        stop_fraction += profile.planner_vol_stop_multiplier * vol_fraction * 0.06 * intervention
        mode = "reprice_only"
    else:
        stop_fraction += profile.planner_vol_stop_multiplier * vol_fraction * 0.25 * intervention
        mode = "balanced"
    planner_stop_cap = max(
        base_stop_fraction,
        min(profile.planner_max_stop_fraction, profile.wick_max_stop_fraction + 0.18),
    )
    stop_fraction = clamp(stop_fraction, profile.wick_min_stop_fraction, planner_stop_cap)

    target_fraction = max(base_target_fraction, profile.wick_min_target_fraction)
    target_from_vol = profile.planner_vol_target_multiplier * vol_fraction
    if strong_historical_edge:
        target_fraction = max(target_fraction, stop_fraction * profile.planner_min_target_stop_ratio)
    elif take_profit_probability >= 0.58:
        target_fraction = max(target_fraction, target_from_vol, stop_fraction * profile.planner_min_target_stop_ratio)
    elif wrong_direction_dominant:
        target_fraction = max(
            min(target_fraction, profile.planner_max_target_fraction),
            stop_fraction * profile.planner_min_target_stop_ratio,
            target_from_vol * 0.60,
        )
    else:
        target_fraction = max(min(target_fraction, profile.planner_max_target_fraction), stop_fraction * profile.planner_min_target_stop_ratio)
    target_fraction = clamp(target_fraction, profile.wick_min_target_fraction, min(profile.planner_max_target_fraction, profile.wick_max_target_fraction + 0.20))

    hold_seconds = int(base_hold_seconds)
    if mode == "wrong_direction_fast_exit":
        hold_seconds = int(clamp(base_hold_seconds * 0.65, profile.dynamic_hold_min_seconds, profile.max_hold_seconds))
    elif mode == "recovery_allowed":
        hold_seconds = int(clamp(base_hold_seconds * 1.15, profile.dynamic_hold_min_seconds, profile.max_hold_seconds))
    elif mode == "reprice_only":
        hold_seconds = int(clamp(base_hold_seconds, profile.dynamic_hold_min_seconds, profile.max_hold_seconds))
    else:
        hold_seconds = int(clamp(base_hold_seconds, profile.dynamic_hold_min_seconds, profile.max_hold_seconds))

    trailing_activate = profile.trailing_activate_fraction
    trailing_lock = profile.trailing_lock_fraction
    trailing_giveback = profile.trailing_giveback_fraction
    if mode == "wrong_direction_fast_exit":
        trailing_activate = max(1.05, profile.trailing_activate_fraction * 0.70)
        trailing_lock = min(0.70, profile.trailing_lock_fraction + 0.18)
        trailing_giveback = max(0.45, profile.trailing_giveback_fraction * 0.70)
    elif mode == "recovery_allowed":
        trailing_activate = max(1.40, profile.trailing_activate_fraction * 0.85)
        trailing_lock = min(0.60, profile.trailing_lock_fraction + 0.08)
        trailing_giveback = max(0.55, profile.trailing_giveback_fraction * 0.85)
    elif mode == "reprice_only":
        trailing_activate = max(1.25, profile.trailing_activate_fraction * 0.80)
        trailing_lock = min(0.62, profile.trailing_lock_fraction + 0.10)
        trailing_giveback = max(0.52, profile.trailing_giveback_fraction * 0.80)

    return DynamicLevelPlan(
        entry_edge_fraction=entry_edge,
        stop_span_fraction=stop_fraction,
        target_span_fraction=target_fraction,
        hold_seconds=hold_seconds,
        trailing_activate_fraction=trailing_activate,
        trailing_lock_fraction=trailing_lock,
        trailing_giveback_fraction=trailing_giveback,
        recovery_probability=recovery_probability,
        wrong_direction_probability=wrong_direction_probability,
        take_profit_probability=take_profit_probability,
        mode=mode,
        reason_codes=[
            f"dynamic_level_planner_enabled:{profile.dynamic_level_planner_enabled}",
            f"planner_mode:{mode}",
            f"planner_take_profit_probability:{round(take_profit_probability, 6)}",
            f"planner_recovery_probability:{round(recovery_probability, 6)}",
            f"planner_wrong_direction_probability:{round(wrong_direction_probability, 6)}",
            f"planner_history_weight:{round(history_weight, 6)}",
            f"planner_formula_take_profit_probability:{round(formula_take_profit_probability, 6)}",
            f"planner_formula_recovery_probability:{round(formula_recovery_probability, 6)}",
            f"planner_formula_wrong_direction_probability:{round(formula_wrong_direction_probability, 6)}",
            f"planner_history_win_rate:{round(wick_win_rate, 6)}",
            f"planner_history_recovery_rate:{round(wick_recovery_rate, 6)}",
            f"planner_history_stop_then_target_rate:{round(wick_stop_then_target_rate, 6)}",
            f"planner_history_true_wrong_rate:{round(wick_true_wrong_rate, 6)}",
            f"planner_historical_recovery_edge:{historical_recovery_edge}",
            f"planner_historical_target_recovery_edge:{historical_target_recovery_edge}",
            f"planner_historical_reprice_edge:{historical_reprice_edge}",
            f"planner_strong_historical_edge:{strong_historical_edge}",
            f"planner_vol_fraction:{round(vol_fraction, 6)}",
            f"planner_bb_fraction:{round(bb_fraction, 6)}",
            f"planner_response_quality:{round(response_quality, 6)}",
            f"planner_drift_pressure:{round(drift_pressure, 6)}",
            f"planner_continuation_pressure:{round(continuation_pressure, 6)}",
            f"planner_intervention:{round(intervention, 6)}",
            f"planner_base_entry_edge_fraction:{round(base_entry_edge_fraction, 6)}",
            f"planner_base_stop_fraction:{round(base_stop_fraction, 6)}",
            f"planner_stop_cap_fraction:{round(planner_stop_cap, 6)}",
            f"planner_base_target_fraction:{round(base_target_fraction, 6)}",
            f"planner_entry_edge_fraction:{round(entry_edge, 6)}",
            f"planner_stop_span_fraction:{round(stop_fraction, 6)}",
            f"planner_target_span_fraction:{round(target_fraction, 6)}",
            f"planner_trailing_activate_fraction:{round(trailing_activate, 6)}",
            f"planner_trailing_lock_fraction:{round(trailing_lock, 6)}",
            f"planner_trailing_giveback_fraction:{round(trailing_giveback, 6)}",
        ],
    )


def dynamic_level_reason_codes(plan: DynamicLevelPlan | None) -> list[str]:
    return list(plan.reason_codes) if plan is not None else []


def dynamic_grid_range_fraction(state: MicroGridState, profile: MicroGridProfile) -> float:
    span = state.upper_price - state.lower_price
    if span <= 0 or state.reservation_price <= 0:
        return max(0.01, profile.grid_layer_spacing_fraction)
    bb_fraction = (state.bollinger_width_percent / max(state.width_percent, 0.0001)) * 0.5
    vol_fraction = state.instantaneous_vol_percent / max(state.width_percent, 0.0001)
    return clamp(max(bb_fraction, vol_fraction, 0.08), 0.02, 0.60)


def is_passive_entry(side: str, entry: float, current_price: float, profile: MicroGridProfile) -> bool:
    if entry <= 0 or current_price <= 0:
        return True
    configured_gap = max(0.0, profile.post_only_entry_gap_bps) / 10_000.0
    cost_gap = profile.round_trip_cost_percent / 100.0 * 0.5 if configured_gap > 0 else 0.0
    gap = max(configured_gap, cost_gap)
    if side == "long":
        return entry <= current_price * (1.0 - gap)
    return entry >= current_price * (1.0 + gap)


def cost_aware_target(side: str, entry: float, target: float, state: MicroGridState, profile: MicroGridProfile) -> tuple[float, str]:
    if not profile.target_extension_enabled or entry <= 0:
        return target, "disabled"
    span = state.upper_price - state.lower_price
    if span <= 0:
        return target, "invalid_span"
    current_reward = (target - entry) if side == "long" else (entry - target)
    current_reward_percent = current_reward / entry * 100.0 if current_reward > 0 else 0.0
    required_for_margin = profile.round_trip_cost_percent + max(0.0, profile.min_net_margin_reward_percent) / max(1.0, float(profile.fee_filter_leverage))
    required_for_notional = profile.round_trip_cost_percent + max(0.0, profile.min_net_notional_reward_percent)
    required_percent = max(profile.min_reward_percent, required_for_margin, required_for_notional)
    if current_reward_percent >= required_percent:
        return target, "not_needed"
    required_move = entry * required_percent / 100.0
    max_fraction = clamp(profile.target_extension_max_fraction, 0.0, 1.0)
    if side == "long":
        extended = entry + required_move
        cap = state.lower_price + span * max_fraction
        bounded = min(extended, cap, state.upper_price)
    else:
        extended = entry - required_move
        cap = state.upper_price - span * max_fraction
        bounded = max(extended, cap, state.lower_price)
    adjusted_reward = (bounded - entry) if side == "long" else (entry - bounded)
    if adjusted_reward <= current_reward:
        return target, "insufficient_room"
    adjusted_reward_percent = adjusted_reward / entry * 100.0
    reason = "extended_to_cost_floor" if adjusted_reward_percent >= required_percent else "extended_but_still_below_cost_floor"
    return bounded, reason


def estimated_target_net_reward_usdt(reward_percent: float, profile: MicroGridProfile) -> float:
    notional = max(profile.target_net_filter_notional_usdt, 0.0)
    if notional <= 0:
        return 0.0
    gross = notional * max(reward_percent, 0.0) / 100.0
    fees = notional * (max(profile.maker_fee_bps, 0.0) + max(profile.taker_fee_bps, 0.0)) / 10_000.0
    slippage = notional * max(profile.exit_slippage_bps, 0.0) / 10_000.0
    return gross - fees - slippage


def net_reward_percent_after_cost(reward_percent: float, profile: MicroGridProfile) -> float:
    return reward_percent - profile.round_trip_cost_percent


def net_margin_reward_percent_after_cost(reward_percent: float, profile: MicroGridProfile) -> float:
    leverage = max(1.0, float(profile.fee_filter_leverage))
    return net_reward_percent_after_cost(reward_percent, profile) * leverage


def simulate_grid_order(
    seconds: list[BacktestBar],
    order: GridOrder,
    profile: MicroGridProfile,
    *,
    notional_usdt: float,
    tick_stream: TickStream | None = None,
) -> tuple[MicroGridTrade | None, str, int | None]:
    if tick_stream is not None and tick_stream.ticks:
        return simulate_grid_order_on_ticks(seconds, order, profile, notional_usdt=notional_usdt, tick_stream=tick_stream)
    fill_index = find_fill_index(seconds, order, profile)
    if fill_index is None:
        return None, "expired", None
    if notional_usdt <= 0:
        return None, "rejected_sizing", fill_index
    quantity = notional_usdt / order.entry_price
    entry_fee = notional_usdt * profile.maker_fee_bps / 10_000.0
    best_price = order.entry_price
    worst_price = order.entry_price
    dynamic_stop = order.stop_price
    end_index = min(len(seconds) - 1, fill_index + max(1, order.max_hold_seconds) - 1)
    for index in range(fill_index, end_index + 1):
        bar = seconds[index]
        if order.side == "long":
            best_price = max(best_price, bar.high)
            worst_price = min(worst_price, bar.low)
            hit_stop = bar.low <= dynamic_stop
            hit_target = bar.high >= order.target_price
        else:
            best_price = min(best_price, bar.low)
            worst_price = max(worst_price, bar.high)
            hit_stop = bar.high >= dynamic_stop
            hit_target = bar.low <= order.target_price
        if hit_stop:
            reason = "trailing_stop" if stop_has_moved(order.side, dynamic_stop, order.stop_price) else "same_bar_stop" if index == fill_index else "stop_loss"
            trade = close_trade(order, seconds[fill_index], bar, profile, quantity, entry_fee, best_price, worst_price, dynamic_stop, reason)
            trade = annotate_post_stop_path(trade, order, seconds, exit_index=index, profile=profile)
            return trade, "same_bar_stop" if index == fill_index else "filled", fill_index
        if hit_target:
            return close_trade(order, seconds[fill_index], bar, profile, quantity, entry_fee, best_price, worst_price, order.target_price, "take_profit"), "filled", fill_index
        dynamic_stop = update_trailing_stop(order, profile, best_price, dynamic_stop)
    return close_trade(order, seconds[fill_index], seconds[end_index], profile, quantity, entry_fee, best_price, worst_price, seconds[end_index].close, "max_hold_exit"), "filled", fill_index


def simulate_grid_basket(
    seconds: list[BacktestBar],
    orders: list[GridOrder],
    profile: MicroGridProfile,
    *,
    base_notional_usdt: float,
    tick_stream: TickStream | None = None,
) -> tuple[MicroGridTrade | None, str, int | None]:
    valid_orders = [order for order in orders if base_notional_usdt * max(0.01, order.size_weight) > 0]
    if not valid_orders:
        return None, "rejected_sizing", None
    if tick_stream is not None and tick_stream.ticks:
        return simulate_grid_basket_on_ticks(seconds, valid_orders, profile, base_notional_usdt=base_notional_usdt, tick_stream=tick_stream)
    return simulate_grid_basket_on_seconds(seconds, valid_orders, profile, base_notional_usdt=base_notional_usdt)


def simulate_grid_basket_on_seconds(
    seconds: list[BacktestBar],
    orders: list[GridOrder],
    profile: MicroGridProfile,
    *,
    base_notional_usdt: float,
) -> tuple[MicroGridTrade | None, str, int | None]:
    if not seconds or not orders:
        return None, "expired", None
    signal_index = orders[0].signal_index
    wait_end_index = min(len(seconds) - 1, signal_index + max(1, profile.order_wait_seconds) - 1)
    end_index = min(len(seconds) - 1, signal_index + max(1, profile.order_wait_seconds) + max(order.max_hold_seconds for order in orders))
    fills: list[BasketFill] = []
    open_order_ids = {id(order) for order in orders}
    basket_order: GridOrder | None = None
    quantity = 0.0
    entry_fee = 0.0
    first_fill_ms: int | None = None
    first_fill_index: int | None = None
    dynamic_stop = 0.0
    best_price = 0.0
    worst_price = 0.0
    for index in range(signal_index, end_index + 1):
        bar = seconds[index]
        filled_this_bar = False
        if index <= wait_end_index:
            for order in orders:
                if id(order) not in open_order_ids:
                    continue
                if order.side == "long" and bar.low <= order.entry_price:
                    fills.append(BasketFill(order=order, fill_time_ms=bar.open_time))
                    open_order_ids.remove(id(order))
                    filled_this_bar = True
                elif order.side == "short" and bar.high >= order.entry_price:
                    fills.append(BasketFill(order=order, fill_time_ms=bar.open_time))
                    open_order_ids.remove(id(order))
                    filled_this_bar = True
        if not fills:
            continue
        if first_fill_ms is None:
            first_fill_ms = min(fill.fill_time_ms for fill in fills)
            first_fill_index = index
            end_index = min(len(seconds) - 1, index + max(1, max(order.max_hold_seconds for order in orders)) - 1)
        if len(fills) < max(1, int(profile.min_filled_grid_layers)):
            continue
        current_order = build_basket_order(fills, profile, base_notional_usdt=base_notional_usdt)
        if current_order is None:
            return None, "rejected_sizing", first_fill_index
        basket_order = current_order
        quantity = basket_quantity(fills, base_notional_usdt=base_notional_usdt)
        entry_fee = basket_notional(fills, base_notional_usdt=base_notional_usdt) * profile.maker_fee_bps / 10_000.0
        if filled_this_bar or dynamic_stop <= 0:
            dynamic_stop = basket_order.stop_price
            best_price = basket_order.entry_price
            worst_price = basket_order.entry_price
        if basket_order.side == "long":
            best_price = max(best_price, bar.high)
            worst_price = min(worst_price, bar.low)
            hit_stop = bar.low <= dynamic_stop
            hit_target = bar.high >= basket_order.target_price
        else:
            best_price = min(best_price, bar.low)
            worst_price = max(worst_price, bar.high)
            hit_stop = bar.high >= dynamic_stop
            hit_target = bar.low <= basket_order.target_price
        if hit_stop:
            reason = "trailing_stop" if stop_has_moved(basket_order.side, dynamic_stop, basket_order.stop_price) else "same_bar_stop" if index == first_fill_index else "stop_loss"
            trade = close_trade(basket_order, seconds[first_fill_index or index], bar, profile, quantity, entry_fee, best_price, worst_price, dynamic_stop, reason)
            trade = annotate_post_stop_path(trade, basket_order, seconds, exit_index=index, profile=profile)
            return trade, "same_bar_stop" if index == first_fill_index else "filled", first_fill_index
        if hit_target:
            return close_trade(basket_order, seconds[first_fill_index or index], bar, profile, quantity, entry_fee, best_price, worst_price, basket_order.target_price, "take_profit"), "filled", first_fill_index
        dynamic_stop = update_trailing_stop(basket_order, profile, best_price, dynamic_stop)
    if not fills or basket_order is None or first_fill_index is None:
        return None, "expired", None
    return close_trade(basket_order, seconds[first_fill_index], seconds[end_index], profile, quantity, entry_fee, best_price, worst_price, seconds[end_index].close, "max_hold_exit"), "filled", first_fill_index


def simulate_grid_basket_on_ticks(
    seconds: list[BacktestBar],
    orders: list[GridOrder],
    profile: MicroGridProfile,
    *,
    base_notional_usdt: float,
    tick_stream: TickStream,
) -> tuple[MicroGridTrade | None, str, int | None]:
    if not seconds or not orders:
        return None, "expired", None
    signal_ms = seconds[orders[0].signal_index].open_time
    wait_end_ms = signal_ms + max(1, profile.order_wait_seconds) * SECOND_MS - 1
    start = bisect_left(tick_stream.time_ms, signal_ms)
    open_orders = list(orders)
    fills: list[BasketFill] = []
    basket_order: GridOrder | None = None
    quantity = 0.0
    entry_fee = 0.0
    first_fill_ms: int | None = None
    fill_index: int | None = None
    dynamic_stop = 0.0
    best_price = 0.0
    worst_price = 0.0
    end_ms = wait_end_ms
    last_tick: AggTradeTick | None = None
    for position in range(start, len(tick_stream.ticks)):
        tick = tick_stream.ticks[position]
        if first_fill_ms is None and tick.time_ms > wait_end_ms:
            break
        if first_fill_ms is not None and tick.time_ms > end_ms:
            break
        last_tick = tick
        filled_this_tick = False
        if tick.time_ms <= wait_end_ms:
            for order in list(open_orders):
                if order.side == "long" and tick.price <= order.entry_price:
                    fills.append(BasketFill(order=order, fill_time_ms=tick.time_ms))
                    open_orders.remove(order)
                    filled_this_tick = True
                elif order.side == "short" and tick.price >= order.entry_price:
                    fills.append(BasketFill(order=order, fill_time_ms=tick.time_ms))
                    open_orders.remove(order)
                    filled_this_tick = True
        if not fills:
            continue
        if first_fill_ms is None:
            first_fill_ms = min(fill.fill_time_ms for fill in fills)
            fill_index = second_index_for_ms(seconds, first_fill_ms)
            end_ms = first_fill_ms + max(1, max(order.max_hold_seconds for order in orders)) * SECOND_MS
        if len(fills) < max(1, int(profile.min_filled_grid_layers)):
            continue
        current_order = build_basket_order(fills, profile, base_notional_usdt=base_notional_usdt)
        if current_order is None:
            return None, "rejected_sizing", fill_index
        basket_order = current_order
        quantity = basket_quantity(fills, base_notional_usdt=base_notional_usdt)
        entry_fee = basket_notional(fills, base_notional_usdt=base_notional_usdt) * profile.maker_fee_bps / 10_000.0
        if filled_this_tick or dynamic_stop <= 0:
            dynamic_stop = basket_order.stop_price
            best_price = basket_order.entry_price
            worst_price = basket_order.entry_price
        if basket_order.side == "long":
            best_price = max(best_price, tick.price)
            worst_price = min(worst_price, tick.price)
            hit_stop = tick.price <= dynamic_stop
            hit_target = tick.price >= basket_order.target_price
        else:
            best_price = min(best_price, tick.price)
            worst_price = max(worst_price, tick.price)
            hit_stop = tick.price >= dynamic_stop
            hit_target = tick.price <= basket_order.target_price
        if hit_stop:
            initial_stop = not stop_has_moved(basket_order.side, dynamic_stop, basket_order.stop_price)
            same_second = first_fill_ms is not None and tick.time_ms // SECOND_MS == first_fill_ms // SECOND_MS
            reason = "trailing_stop" if not initial_stop else "same_bar_stop" if same_second else "stop_loss"
            trade = close_trade_at_ms(
                basket_order,
                entry_time_ms=first_fill_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=dynamic_stop,
                exit_reason=reason,
            )
            trade = annotate_post_stop_path(trade, basket_order, seconds, exit_index=second_index_for_ms(seconds, tick.time_ms), profile=profile)
            return trade, "same_bar_stop" if same_second and reason == "same_bar_stop" else "filled", fill_index
        if hit_target:
            return close_trade_at_ms(
                basket_order,
                entry_time_ms=first_fill_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=basket_order.target_price,
                exit_reason="take_profit",
            ), "filled", fill_index
        dynamic_stop = update_trailing_stop(basket_order, profile, best_price, dynamic_stop)
    if not fills or basket_order is None or first_fill_ms is None or fill_index is None:
        return None, "expired", None
    if last_tick is None:
        return None, "expired", None
    reason = "max_hold_exit" if last_tick.time_ms >= end_ms else "data_end_exit"
    return close_trade_at_ms(
        basket_order,
        entry_time_ms=first_fill_ms,
        exit_time_ms=last_tick.time_ms,
        profile=profile,
        quantity=quantity,
        entry_fee=entry_fee,
        best_price=best_price,
        worst_price=worst_price,
        raw_exit=last_tick.price,
        exit_reason=reason,
    ), "filled", fill_index


def simulate_filled_basket_on_ticks(
    seconds: list[BacktestBar],
    fills: list[BasketFill],
    profile: MicroGridProfile,
    *,
    base_notional_usdt: float,
    tick_stream: TickStream,
) -> tuple[MicroGridTrade | None, str, int | None]:
    basket_order = build_basket_order(fills, profile, base_notional_usdt=base_notional_usdt)
    if basket_order is None:
        return None, "rejected_sizing", None
    first_fill_ms = min(fill.fill_time_ms for fill in fills)
    fill_index = second_index_for_ms(seconds, first_fill_ms)
    fill_pos = bisect_left(tick_stream.time_ms, first_fill_ms)
    quantity = basket_quantity(fills, base_notional_usdt=base_notional_usdt)
    entry_fee = basket_notional(fills, base_notional_usdt=base_notional_usdt) * profile.maker_fee_bps / 10_000.0
    best_price = basket_order.entry_price
    worst_price = basket_order.entry_price
    dynamic_stop = basket_order.stop_price
    end_ms = max(fill.fill_time_ms for fill in fills) + max(1, basket_order.max_hold_seconds) * SECOND_MS
    last_tick = tick_stream.ticks[fill_pos] if fill_pos < len(tick_stream.ticks) else None

    for tick in iter_ticks(tick_stream, fill_pos, end_ms=end_ms):
        last_tick = tick
        if tick.time_ms < first_fill_ms:
            continue
        if basket_order.side == "long":
            best_price = max(best_price, tick.price)
            worst_price = min(worst_price, tick.price)
            hit_stop = tick.price <= dynamic_stop
            hit_target = tick.price >= basket_order.target_price
        else:
            best_price = min(best_price, tick.price)
            worst_price = max(worst_price, tick.price)
            hit_stop = tick.price >= dynamic_stop
            hit_target = tick.price <= basket_order.target_price
        if hit_stop:
            initial_stop = not stop_has_moved(basket_order.side, dynamic_stop, basket_order.stop_price)
            same_second = tick.time_ms // SECOND_MS == first_fill_ms // SECOND_MS
            reason = "trailing_stop" if not initial_stop else "same_bar_stop" if same_second else "stop_loss"
            trade = close_trade_at_ms(
                basket_order,
                entry_time_ms=first_fill_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=dynamic_stop,
                exit_reason=reason,
            )
            trade = annotate_post_stop_path(trade, basket_order, seconds, exit_index=second_index_for_ms(seconds, tick.time_ms), profile=profile)
            return trade, "same_bar_stop" if same_second and reason == "same_bar_stop" else "filled", fill_index
        if hit_target:
            return close_trade_at_ms(
                basket_order,
                entry_time_ms=first_fill_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=basket_order.target_price,
                exit_reason="take_profit",
            ), "filled", fill_index
        dynamic_stop = update_trailing_stop(basket_order, profile, best_price, dynamic_stop)

    if last_tick is None:
        return None, "expired", None
    reason = "max_hold_exit" if last_tick.time_ms >= end_ms else "data_end_exit"
    return close_trade_at_ms(
        basket_order,
        entry_time_ms=first_fill_ms,
        exit_time_ms=last_tick.time_ms,
        profile=profile,
        quantity=quantity,
        entry_fee=entry_fee,
        best_price=best_price,
        worst_price=worst_price,
        raw_exit=last_tick.price,
        exit_reason=reason,
    ), "filled", fill_index


def simulate_filled_basket_on_seconds(
    seconds: list[BacktestBar],
    fills: list[BasketFill],
    profile: MicroGridProfile,
    *,
    base_notional_usdt: float,
) -> tuple[MicroGridTrade | None, str, int | None]:
    basket_order = build_basket_order(fills, profile, base_notional_usdt=base_notional_usdt)
    if basket_order is None:
        return None, "rejected_sizing", None
    first_fill_ms = min(fill.fill_time_ms for fill in fills)
    fill_index = second_index_for_ms(seconds, first_fill_ms)
    quantity = basket_quantity(fills, base_notional_usdt=base_notional_usdt)
    entry_fee = basket_notional(fills, base_notional_usdt=base_notional_usdt) * profile.maker_fee_bps / 10_000.0
    best_price = basket_order.entry_price
    worst_price = basket_order.entry_price
    dynamic_stop = basket_order.stop_price
    end_index = min(len(seconds) - 1, second_index_for_ms(seconds, max(fill.fill_time_ms for fill in fills)) + max(1, basket_order.max_hold_seconds) - 1)
    for index in range(fill_index, end_index + 1):
        bar = seconds[index]
        if basket_order.side == "long":
            best_price = max(best_price, bar.high)
            worst_price = min(worst_price, bar.low)
            hit_stop = bar.low <= dynamic_stop
            hit_target = bar.high >= basket_order.target_price
        else:
            best_price = min(best_price, bar.low)
            worst_price = max(worst_price, bar.high)
            hit_stop = bar.high >= dynamic_stop
            hit_target = bar.low <= basket_order.target_price
        if hit_stop:
            reason = "trailing_stop" if stop_has_moved(basket_order.side, dynamic_stop, basket_order.stop_price) else "same_bar_stop" if index == fill_index else "stop_loss"
            trade = close_trade(basket_order, seconds[fill_index], bar, profile, quantity, entry_fee, best_price, worst_price, dynamic_stop, reason)
            trade = annotate_post_stop_path(trade, basket_order, seconds, exit_index=index, profile=profile)
            return trade, "same_bar_stop" if index == fill_index else "filled", fill_index
        if hit_target:
            return close_trade(basket_order, seconds[fill_index], bar, profile, quantity, entry_fee, best_price, worst_price, basket_order.target_price, "take_profit"), "filled", fill_index
        dynamic_stop = update_trailing_stop(basket_order, profile, best_price, dynamic_stop)
    return close_trade(basket_order, seconds[fill_index], seconds[end_index], profile, quantity, entry_fee, best_price, worst_price, seconds[end_index].close, "max_hold_exit"), "filled", fill_index


def build_basket_order(fills: list[BasketFill], profile: MicroGridProfile, *, base_notional_usdt: float) -> GridOrder | None:
    if not fills:
        return None
    orders = [fill.order for fill in fills]
    side = orders[0].side
    if any(order.side != side for order in orders):
        return None
    total_notional = basket_notional(fills, base_notional_usdt=base_notional_usdt)
    total_quantity = basket_quantity(fills, base_notional_usdt=base_notional_usdt)
    if total_notional <= 0 or total_quantity <= 0:
        return None
    average_entry = total_notional / total_quantity
    target_move = weighted_average([abs(order.entry_price - order.target_price) for order in orders], [base_notional_usdt * max(0.01, order.size_weight) for order in orders])
    if side == "long":
        stop = min(order.stop_price for order in orders)
        target = average_entry + target_move
    else:
        stop = max(order.stop_price for order in orders)
        target = average_entry - target_move
    reason_codes = basket_reason_codes(fills, average_entry, stop, target)
    return GridOrder(
        symbol=orders[0].symbol,
        side=side,
        signal_index=orders[0].signal_index,
        signal_time=orders[0].signal_time,
        entry_price=average_entry,
        stop_price=stop,
        target_price=target,
        state=orders[0].state,
        reason_codes=reason_codes,
        max_hold_seconds=max(order.max_hold_seconds for order in orders),
        size_weight=sum(order.size_weight for order in orders),
    )


def basket_reason_codes(fills: list[BasketFill], average_entry: float, stop: float, target: float) -> list[str]:
    first_order = fills[0].order
    base_codes = [
        code
        for code in first_order.reason_codes
        if not code.startswith("grid_layer:")
        and not code.startswith("grid_layer_size:")
        and not code.startswith("entry_price:")
        and not code.startswith("target_price:")
        and not code.startswith("stop_price:")
    ]
    layers = [grid_layer_from_order(fill.order) for fill in fills]
    return [
        *base_codes,
        "execution_mode:dca_basket",
        f"basket_layers:{','.join(str(layer) for layer in layers)}",
        f"basket_fill_count:{len(fills)}",
        f"basket_size_weight:{round(sum(fill.order.size_weight for fill in fills), 6)}",
        f"basket_average_entry_price:{round(average_entry, 8)}",
        f"basket_target_price:{round(target, 8)}",
        f"basket_stop_price:{round(stop, 8)}",
    ]


def basket_notional(fills: list[BasketFill], *, base_notional_usdt: float) -> float:
    return sum(base_notional_usdt * max(0.01, fill.order.size_weight) for fill in fills)


def basket_quantity(fills: list[BasketFill], *, base_notional_usdt: float) -> float:
    return sum((base_notional_usdt * max(0.01, fill.order.size_weight)) / fill.order.entry_price for fill in fills if fill.order.entry_price > 0)


def weighted_average(values: list[float], weights: list[float]) -> float:
    denominator = sum(weight for weight in weights if weight > 0)
    if denominator <= 0:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights) if weight > 0) / denominator


def grid_layer_from_order(order: GridOrder) -> int:
    for code in order.reason_codes:
        if code.startswith("grid_layer:"):
            try:
                return int(code.split(":", 1)[1])
            except ValueError:
                return 0
    return 0


def filled_layer_count_from_trade(trade: MicroGridTrade) -> int:
    for code in trade.reason_codes:
        if code.startswith("basket_fill_count:"):
            try:
                return int(code.split(":", 1)[1])
            except ValueError:
                return 1
    return 1


def simulate_grid_order_on_ticks(
    seconds: list[BacktestBar],
    order: GridOrder,
    profile: MicroGridProfile,
    *,
    notional_usdt: float,
    tick_stream: TickStream,
) -> tuple[MicroGridTrade | None, str, int | None]:
    if not seconds:
        return None, "expired", None
    signal_ms = seconds[order.signal_index].open_time
    wait_end_ms = signal_ms + max(1, profile.order_wait_seconds) * SECOND_MS - 1
    fill_pos = find_fill_tick_position(tick_stream, order, start_ms=signal_ms, end_ms=wait_end_ms)
    if fill_pos is None:
        return None, "expired", None
    fill_tick = tick_stream.ticks[fill_pos]
    fill_index = second_index_for_ms(seconds, fill_tick.time_ms)
    if notional_usdt <= 0:
        return None, "rejected_sizing", fill_index

    quantity = notional_usdt / order.entry_price
    entry_fee = notional_usdt * profile.maker_fee_bps / 10_000.0
    best_price = order.entry_price
    worst_price = order.entry_price
    dynamic_stop = order.stop_price
    end_ms = fill_tick.time_ms + max(1, order.max_hold_seconds) * SECOND_MS
    last_tick = fill_tick

    for tick in iter_ticks(tick_stream, fill_pos, end_ms=end_ms):
        last_tick = tick
        if order.side == "long":
            best_price = max(best_price, tick.price)
            worst_price = min(worst_price, tick.price)
            hit_stop = tick.price <= dynamic_stop
            hit_target = tick.price >= order.target_price
        else:
            best_price = min(best_price, tick.price)
            worst_price = max(worst_price, tick.price)
            hit_stop = tick.price >= dynamic_stop
            hit_target = tick.price <= order.target_price

        if hit_stop:
            initial_stop = not stop_has_moved(order.side, dynamic_stop, order.stop_price)
            same_second = tick.time_ms // SECOND_MS == fill_tick.time_ms // SECOND_MS
            reason = "trailing_stop" if not initial_stop else "same_bar_stop" if same_second else "stop_loss"
            trade = close_trade_at_ms(
                order,
                entry_time_ms=fill_tick.time_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=dynamic_stop,
                exit_reason=reason,
            )
            trade = annotate_post_stop_path(
                trade,
                order,
                seconds,
                exit_index=second_index_for_ms(seconds, tick.time_ms),
                profile=profile,
            )
            return trade, "same_bar_stop" if same_second and reason == "same_bar_stop" else "filled", fill_index

        if hit_target:
            trade = close_trade_at_ms(
                order,
                entry_time_ms=fill_tick.time_ms,
                exit_time_ms=tick.time_ms,
                profile=profile,
                quantity=quantity,
                entry_fee=entry_fee,
                best_price=best_price,
                worst_price=worst_price,
                raw_exit=order.target_price,
                exit_reason="take_profit",
            )
            return trade, "filled", fill_index

        dynamic_stop = update_trailing_stop(order, profile, best_price, dynamic_stop)

    reason = "max_hold_exit" if last_tick.time_ms >= end_ms else "data_end_exit"
    trade = close_trade_at_ms(
        order,
        entry_time_ms=fill_tick.time_ms,
        exit_time_ms=last_tick.time_ms,
        profile=profile,
        quantity=quantity,
        entry_fee=entry_fee,
        best_price=best_price,
        worst_price=worst_price,
        raw_exit=last_tick.price,
        exit_reason=reason,
    )
    return trade, "filled", fill_index


def close_trade(
    order: GridOrder,
    entry_bar: BacktestBar,
    exit_bar: BacktestBar,
    profile: MicroGridProfile,
    quantity: float,
    entry_fee: float,
    best_price: float,
    worst_price: float,
    raw_exit: float,
    exit_reason: str,
) -> MicroGridTrade:
    return close_trade_at_ms(
        order,
        entry_time_ms=entry_bar.open_time,
        exit_time_ms=exit_bar.close_time,
        profile=profile,
        quantity=quantity,
        entry_fee=entry_fee,
        best_price=best_price,
        worst_price=worst_price,
        raw_exit=raw_exit,
        exit_reason=exit_reason,
    )


def close_trade_at_ms(
    order: GridOrder,
    *,
    entry_time_ms: int,
    exit_time_ms: int,
    profile: MicroGridProfile,
    quantity: float,
    entry_fee: float,
    best_price: float,
    worst_price: float,
    raw_exit: float,
    exit_reason: str,
) -> MicroGridTrade:
    slip_rate = profile.exit_slippage_bps / 10_000.0
    if order.side == "long":
        exit_fill = raw_exit * (1.0 - slip_rate)
        gross = quantity * (exit_fill - order.entry_price)
        slippage = quantity * max(raw_exit - exit_fill, 0.0)
        mfe = percent_delta(order.entry_price, best_price)
        mae = percent_delta(order.entry_price, worst_price)
    else:
        exit_fill = raw_exit * (1.0 + slip_rate)
        gross = quantity * (order.entry_price - exit_fill)
        slippage = quantity * max(exit_fill - raw_exit, 0.0)
        mfe = percent_delta(best_price, order.entry_price)
        mae = percent_delta(worst_price, order.entry_price)
    exit_fee = quantity * exit_fill * profile.taker_fee_bps / 10_000.0
    fees = entry_fee + exit_fee
    net = gross - fees
    risk_usdt = abs(order.entry_price - order.stop_price) * quantity
    return MicroGridTrade(
        symbol=order.symbol,
        side=order.side,
        signal_time=order.signal_time,
        entry_time=ms_to_iso(entry_time_ms),
        exit_time=ms_to_iso(exit_time_ms),
        entry_price=round(order.entry_price, 8),
        exit_price=round(exit_fill, 8),
        notional_usdt=round(quantity * order.entry_price, 8),
        initial_risk_usdt=round(risk_usdt, 8),
        gross_pnl_usdt=round(gross, 8),
        fees_usdt=round(fees, 8),
        slippage_usdt=round(slippage, 8),
        net_pnl_usdt=round(net, 8),
        hold_seconds=max(1, int((exit_time_ms - entry_time_ms) / SECOND_MS) + 1),
        mfe_percent=round(mfe, 8),
        mae_percent=round(mae, 8),
        realized_r=round(net / risk_usdt, 8) if risk_usdt > 0 else 0.0,
        exit_reason=exit_reason,
        reason_codes=[*order.reason_codes, f"exit_policy:{exit_reason}"],
    )


def replay_portfolio(
    candidate_trades: list[MicroGridTrade],
    *,
    profile: MicroGridProfile,
    initial_capital: float,
    max_open_positions: int,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
    max_margin_fraction: float = 1.0,
    max_leverage: float = 1.0,
    symbol_quality_filter_enabled: bool = False,
    symbol_quality_lookback_hours: float = 72.0,
    symbol_quality_min_samples: int = 3,
    symbol_quality_min_profit_factor: float = 0.75,
    symbol_quality_max_stop_rate: float = 0.65,
    symbol_quality_min_scale: float = 0.0,
) -> dict[str, Any]:
    equity = initial_capital
    accepted: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    cooldown_until_by_symbol: dict[str, int] = {}
    skip_counts = {
        "concurrency": 0,
        "symbol_cooldown": 0,
        "symbol_quality": 0,
        "trade_quality": 0,
        "sizing": 0,
    }
    max_concurrent_positions_observed = 0
    max_margin_used_usdt = 0.0
    max_margin_used_percent_of_equity = 0.0
    for trade in sorted(candidate_trades, key=lambda item: (parse_iso_ms(item.entry_time), item.symbol)):
        entry_ms = parse_iso_ms(trade.entry_time)
        exit_ms = parse_iso_ms(trade.exit_time)
        equity = close_due_positions(
            open_positions,
            accepted,
            equity=equity,
            current_ms=entry_ms,
        )
        if len(open_positions) >= max_open_positions:
            skip_counts["concurrency"] += 1
            continue
        if entry_ms < cooldown_until_by_symbol.get(trade.symbol, -1):
            skip_counts["symbol_cooldown"] += 1
            continue
        if equity <= 0:
            break
        if profile.max_symbol_losses_per_day > 0:
            symbol_day_loss_count = count_symbol_day_losses(accepted, trade.symbol, entry_ms)
            if symbol_day_loss_count >= profile.max_symbol_losses_per_day:
                skip_counts["symbol_cooldown"] += 1
                continue
        symbol_quality_scale, symbol_quality_reason = rolling_symbol_quality_scale(
            accepted,
            trade.symbol,
            entry_ms,
            enabled=symbol_quality_filter_enabled,
            lookback_hours=symbol_quality_lookback_hours,
            min_samples=symbol_quality_min_samples,
            min_profit_factor=symbol_quality_min_profit_factor,
            max_stop_rate=symbol_quality_max_stop_rate,
            min_scale=symbol_quality_min_scale,
        )
        if symbol_quality_scale <= 0:
            skip_counts["symbol_quality"] += 1
            continue
        trade_quality_scale, trade_quality_reasons = micro_trade_quality_scale_from_reason_codes(trade.reason_codes)
        if trade_quality_scale <= 0:
            skip_counts["trade_quality"] += 1
            continue
        margin_budget = equity * max(max_margin_fraction, 0.0)
        margin_used = portfolio_margin_used(open_positions)
        margin_available = max(0.0, margin_budget - margin_used)
        scale = position_scale(
            trade,
            equity=equity,
            risk_per_trade_fraction=risk_per_trade_fraction,
            max_notional_fraction=max_notional_fraction,
            max_margin_fraction=max_margin_fraction,
            max_leverage=max_leverage,
            available_margin_usdt=margin_available,
        )
        scale *= symbol_quality_scale
        scale *= trade_quality_scale
        if scale <= 0:
            skip_counts["sizing"] += 1
            continue
        record = scale_trade(trade, scale=scale, equity_before=equity, max_leverage=max_leverage)
        record["symbol_quality_scale"] = round(symbol_quality_scale, 8)
        record["symbol_quality_reason"] = symbol_quality_reason
        record["trade_quality_scale"] = round(trade_quality_scale, 8)
        record["trade_quality_reasons"] = list(trade_quality_reasons)
        record["entry_time_ms"] = entry_ms
        record["exit_time_ms"] = exit_ms
        record["margin_budget_before_entry_usdt"] = round(margin_budget, 8)
        record["margin_used_before_entry_usdt"] = round(margin_used, 8)
        record["margin_available_before_entry_usdt"] = round(margin_available, 8)
        open_positions.append(
            {
                "exit_ms": exit_ms,
                "symbol": trade.symbol,
                "record": record,
            }
        )
        margin_used_after = portfolio_margin_used(open_positions)
        max_concurrent_positions_observed = max(max_concurrent_positions_observed, len(open_positions))
        max_margin_used_usdt = max(max_margin_used_usdt, margin_used_after)
        max_margin_used_percent_of_equity = max(
            max_margin_used_percent_of_equity,
            margin_used_after / equity * 100.0 if equity > 0 else 0.0,
        )
        cooldown_until_by_symbol[trade.symbol] = exit_ms + profile.reentry_cooldown_seconds * SECOND_MS
    equity = close_due_positions(open_positions, accepted, equity=equity, current_ms=math.inf)
    summary = summarize_trade_dicts(accepted, initial_capital=initial_capital)
    summary["replay_skip_counts"] = skip_counts
    summary["event_replay_final_equity_usdt"] = round(equity, 8)
    summary["max_concurrent_positions_observed"] = max_concurrent_positions_observed
    summary["max_margin_used_usdt"] = round(max_margin_used_usdt, 8)
    summary["max_margin_used_percent_of_equity"] = round(max_margin_used_percent_of_equity, 8)
    return {"summary": summary, "trades": sorted(accepted, key=lambda item: (item["exit_time"], item["symbol"]))}


def close_due_positions(
    open_positions: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    *,
    equity: float,
    current_ms: float,
) -> float:
    due = sorted(
        [position for position in open_positions if position["exit_ms"] <= current_ms],
        key=lambda item: (item["exit_ms"], item["symbol"]),
    )
    for position in due:
        record = position["record"]
        equity += float(record["net_pnl_usdt"])
        record["equity_after_exit_usdt"] = round(equity, 8)
        accepted.append(record)
        open_positions.remove(position)
    return equity


def portfolio_margin_used(open_positions: list[dict[str, Any]]) -> float:
    return sum(float(position["record"].get("initial_margin_usdt") or 0.0) for position in open_positions)


def count_symbol_day_losses(accepted: list[dict[str, Any]], symbol: str, entry_ms: int) -> int:
    entry_day = ms_to_date(entry_ms)
    count = 0
    for trade in accepted:
        if trade.get("symbol") != symbol:
            continue
        if ms_to_date(parse_iso_ms(str(trade.get("exit_time")))) != entry_day:
            continue
        if float(trade.get("net_pnl_usdt") or 0.0) < 0:
            count += 1
    return count


def rolling_symbol_quality_scale(
    accepted: list[dict[str, Any]],
    symbol: str,
    entry_ms: int,
    *,
    enabled: bool,
    lookback_hours: float,
    min_samples: int,
    min_profit_factor: float,
    max_stop_rate: float,
    min_scale: float,
) -> tuple[float, str]:
    if not enabled:
        return 1.0, "disabled"
    lookback_ms = max(0.0, float(lookback_hours)) * 60.0 * 60.0 * 1000.0
    recent = [
        trade
        for trade in accepted
        if trade.get("symbol") == symbol and entry_ms - parse_iso_ms(str(trade.get("exit_time"))) <= lookback_ms
    ]
    min_samples = max(1, int(min_samples))
    if len(recent) < min_samples:
        return 1.0, f"warming_up:{len(recent)}/{min_samples}"

    gross_profit = sum(max(0.0, float(trade.get("net_pnl_usdt") or 0.0)) for trade in recent)
    gross_loss = sum(max(0.0, -float(trade.get("net_pnl_usdt") or 0.0)) for trade in recent)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf
    stop_count = sum(1 for trade in recent if str(trade.get("exit_reason")) in {"stop_loss", "same_bar_stop"})
    stop_rate = stop_count / len(recent)
    wins = sum(1 for trade in recent if float(trade.get("net_pnl_usdt") or 0.0) > 0)
    win_rate = wins / len(recent)

    bad_profit_factor = profit_factor < max(0.0, float(min_profit_factor))
    bad_stop_rate = stop_rate > clamp(float(max_stop_rate), 0.0, 1.0)
    if not bad_profit_factor and not bad_stop_rate:
        return 1.0, (
            f"healthy:n={len(recent)};pf={round(profit_factor, 4)};"
            f"stop_rate={round(stop_rate, 4)};win_rate={round(win_rate, 4)}"
        )

    scale = clamp(float(min_scale), 0.0, 1.0)
    reason = (
        f"degraded:n={len(recent)};pf={round(profit_factor, 4)};"
        f"stop_rate={round(stop_rate, 4)};win_rate={round(win_rate, 4)}"
    )
    return scale, reason


def position_scale(
    trade: MicroGridTrade,
    *,
    equity: float,
    risk_per_trade_fraction: float,
    max_notional_fraction: float,
    max_margin_fraction: float = 1.0,
    max_leverage: float = 1.0,
    available_margin_usdt: float | None = None,
) -> float:
    if equity <= 0 or trade.notional_usdt <= 0:
        return 0.0
    initial_risk_usdt = max(float(trade.initial_risk_usdt), 0.0)
    if initial_risk_usdt <= 0:
        return 0.0
    max_by_risk = equity * risk_per_trade_fraction / initial_risk_usdt
    max_by_notional = equity * max_notional_fraction / trade.notional_usdt
    effective_leverage = max(max_leverage, 1.0)
    margin_budget = equity * max(max_margin_fraction, 0.0) if available_margin_usdt is None else max(available_margin_usdt, 0.0)
    max_by_margin = margin_budget * effective_leverage / trade.notional_usdt
    max_by_pullback = pullback_trade_scale_cap(trade)
    return max(0.0, min(max_by_risk, max_by_notional, max_by_margin, max_by_pullback))


def scale_trade(trade: MicroGridTrade, *, scale: float, equity_before: float, max_leverage: float = 1.0) -> dict[str, Any]:
    payload = trade.to_dict()
    for key in ("notional_usdt", "initial_risk_usdt", "gross_pnl_usdt", "fees_usdt", "slippage_usdt", "net_pnl_usdt"):
        payload[key] = round(float(payload[key]) * scale, 8)
    payload["equity_before_entry_usdt"] = round(equity_before, 8)
    payload["equity_scale"] = round(scale, 8)
    payload["pullback_scale_cap"] = round(pullback_trade_scale_cap(trade), 8)
    effective_leverage = max(float(max_leverage), 1.0)
    payload["assumed_leverage"] = round(effective_leverage, 8)
    payload["initial_margin_usdt"] = round(float(payload["notional_usdt"]) / effective_leverage, 8)
    return payload


def pullback_trade_scale_cap(trade: MicroGridTrade) -> float:
    for code in trade.reason_codes:
        if code.startswith("pullback_size_multiplier:"):
            try:
                return max(0.01, float(code.split(":", 1)[1]))
            except ValueError:
                return math.inf
    return math.inf


def find_fill_index(seconds: list[BacktestBar], order: GridOrder, profile: MicroGridProfile) -> int | None:
    end_index = min(len(seconds) - 1, order.signal_index + max(1, profile.order_wait_seconds) - 1)
    for index in range(order.signal_index, end_index + 1):
        bar = seconds[index]
        if order.side == "long" and bar.low <= order.entry_price:
            return index
        if order.side == "short" and bar.high >= order.entry_price:
            return index
    return None


def find_fill_tick_position(
    tick_stream: TickStream,
    order: GridOrder,
    *,
    start_ms: int,
    end_ms: int,
) -> int | None:
    start = bisect_left(tick_stream.time_ms, start_ms)
    for position in range(start, len(tick_stream.ticks)):
        tick = tick_stream.ticks[position]
        if tick.time_ms > end_ms:
            break
        if order.side == "long" and tick.price <= order.entry_price:
            return position
        if order.side == "short" and tick.price >= order.entry_price:
            return position
    return None


def iter_ticks(tick_stream: TickStream, start_position: int, *, end_ms: int):
    for position in range(start_position, len(tick_stream.ticks)):
        tick = tick_stream.ticks[position]
        if tick.time_ms > end_ms:
            break
        yield tick


def second_index_for_ms(seconds: list[BacktestBar], value: int) -> int:
    if not seconds:
        return 0
    index = int((value - seconds[0].open_time) / SECOND_MS)
    return int(clamp(index, 0, len(seconds) - 1))


def update_trailing_stop(order: GridOrder, profile: MicroGridProfile, best_price: float, current_stop: float) -> float:
    risk = abs(order.entry_price - order.stop_price)
    if risk <= 0:
        return current_stop
    trailing_activate = order_float_code(order, "planner_trailing_activate_fraction", profile.trailing_activate_fraction)
    trailing_lock = order_float_code(order, "planner_trailing_lock_fraction", profile.trailing_lock_fraction)
    trailing_giveback = order_float_code(order, "planner_trailing_giveback_fraction", profile.trailing_giveback_fraction)
    if order.side == "long":
        favorable = best_price - order.entry_price
        if favorable < risk * trailing_activate:
            return current_stop
        lock = order.entry_price + risk * trailing_lock
        giveback = best_price - risk * trailing_giveback
        return max(current_stop, lock, giveback)
    favorable = order.entry_price - best_price
    if favorable < risk * trailing_activate:
        return current_stop
    lock = order.entry_price - risk * trailing_lock
    giveback = best_price + risk * trailing_giveback
    return min(current_stop, lock, giveback)


def order_float_code(order: GridOrder, key: str, default: float) -> float:
    prefix = f"{key}:"
    for code in order.reason_codes:
        if not code.startswith(prefix):
            continue
        try:
            return float(code.split(":", 1)[1])
        except ValueError:
            return default
    return default


def stop_has_moved(side: str, current_stop: float, initial_stop: float) -> bool:
    return current_stop > initial_stop if side == "long" else current_stop < initial_stop


def score_state(
    *,
    width_percent: float,
    cross_count: int,
    turns: int,
    edge_alternations: int,
    response_rate: float,
    path_efficiency: float,
    drift_to_width: float,
    cost_percent: float,
) -> float:
    cost_ratio = width_percent / cost_percent if cost_percent > 0 else 0.0
    return (
        cost_ratio * 0.42
        + cross_count * 0.42
        + turns * 0.28
        + edge_alternations * 0.9
        + response_rate * 4.0
        - path_efficiency * 4.5
        - drift_to_width * 3.2
    )


def summarize_trades(trades: list[MicroGridTrade], *, initial_capital: float) -> dict[str, Any]:
    return summarize_trade_dicts([trade.to_dict() for trade in trades], initial_capital=initial_capital)


def summarize_trade_dicts(trades: list[dict[str, Any]], *, initial_capital: float) -> dict[str, Any]:
    equity = initial_capital
    peak = initial_capital
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    max_drawdown = 0.0
    for trade in sorted(trades, key=lambda item: item["exit_time"]):
        pnl = float(trade["net_pnl_usdt"])
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)
    return {
        "initial_capital_usdt": round(initial_capital, 8),
        "final_capital_usdt": round(equity, 8),
        "net_pnl_usdt": round(equity - initial_capital, 8),
        "return_percent": round((equity / initial_capital - 1.0) * 100.0, 8) if initial_capital else 0.0,
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades), 8) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 8) if gross_loss else ("inf" if gross_profit else None),
        "expectancy_usdt": round((equity - initial_capital) / len(trades), 8) if trades else 0.0,
        "fees_usdt": round(sum(float(trade["fees_usdt"]) for trade in trades), 8),
        "slippage_usdt": round(sum(float(trade["slippage_usdt"]) for trade in trades), 8),
        "max_drawdown_usdt": round(max_drawdown, 8),
        "max_drawdown_percent_of_initial": round(max_drawdown / initial_capital * 100.0, 8) if initial_capital else 0.0,
        "exit_reason_counts": count_by(trades, "exit_reason"),
        "side_counts": count_by(trades, "side"),
        "symbol_counts": count_by(trades, "symbol"),
    }


def failure_summary(trades: list[dict[str, Any]], *, profile: MicroGridProfile) -> dict[str, Any]:
    losses = [trade for trade in trades if float(trade.get("net_pnl_usdt") or 0.0) < 0]
    buckets = {"wrong_wave_prediction": 0, "stop_or_level_too_tight": 0, "profit_not_locked": 0, "cost_drag": 0}
    cost = profile.round_trip_cost_percent
    for trade in losses:
        mfe = float(trade.get("mfe_percent") or 0.0)
        gross = float(trade.get("gross_pnl_usdt") or 0.0)
        reason = str(trade.get("exit_reason") or "")
        reason_codes = {str(code) for code in trade.get("reason_codes", [])}
        if gross >= 0:
            buckets["cost_drag"] += 1
        elif "post_stop_path:bad_entry_or_stop" in reason_codes:
            buckets["stop_or_level_too_tight"] += 1
        elif "post_stop_path:wrong_wave_prediction" in reason_codes:
            buckets["wrong_wave_prediction"] += 1
        elif mfe < max(cost, 0.04):
            buckets["wrong_wave_prediction"] += 1
        elif mfe >= cost * 2.5 and reason in {"stop_loss", "same_bar_stop"}:
            buckets["stop_or_level_too_tight"] += 1
        elif mfe >= cost * 2.5:
            buckets["profit_not_locked"] += 1
        else:
            buckets["stop_or_level_too_tight"] += 1
    return {
        "loss_count": len(losses),
        "bucket_counts": buckets,
        "loss_exit_reason_counts": count_by(losses, "exit_reason"),
        "loss_side_counts": count_by(losses, "side"),
        "loss_symbol_counts": count_by(losses, "symbol"),
    }


def annotate_post_stop_path(
    trade: MicroGridTrade,
    order: GridOrder,
    seconds: list[BacktestBar],
    *,
    exit_index: int,
    profile: MicroGridProfile,
) -> MicroGridTrade:
    if trade.exit_reason not in {"stop_loss", "same_bar_stop"}:
        return trade
    end_index = min(len(seconds) - 1, exit_index + max(1, profile.post_stop_lookahead_seconds))
    future = seconds[exit_index + 1 : end_index + 1]
    if not future:
        return replace(trade, reason_codes=[*trade.reason_codes, "post_stop_path:unknown_no_future"])
    if order.side == "long":
        recovered_to_target = any(bar.high >= order.target_price for bar in future)
        recovered_to_entry = any(bar.high >= order.entry_price for bar in future)
        continued_adverse = min(bar.low for bar in future) < order.stop_price
    else:
        recovered_to_target = any(bar.low <= order.target_price for bar in future)
        recovered_to_entry = any(bar.low <= order.entry_price for bar in future)
        continued_adverse = max(bar.high for bar in future) > order.stop_price
    if recovered_to_target or recovered_to_entry:
        code = "post_stop_path:bad_entry_or_stop"
    elif continued_adverse:
        code = "post_stop_path:wrong_wave_prediction"
    else:
        code = "post_stop_path:ambiguous"
    return replace(trade, reason_codes=[*trade.reason_codes, code])


def center_cross_count(values: list[float], *, center: float) -> int:
    states: list[int] = []
    for value in values:
        state = 1 if value > center else -1 if value < center else 0
        if state == 0:
            continue
        if not states or states[-1] != state:
            states.append(state)
    return sum(1 for previous, current in zip(states, states[1:]) if previous != current)


def turn_count(values: list[float], *, noise_percent: float) -> int:
    directions: list[int] = []
    for previous, current in zip(values, values[1:]):
        move = percent_delta(previous, current)
        if abs(move) < noise_percent:
            continue
        direction = 1 if move > 0 else -1
        if not directions or directions[-1] != direction:
            directions.append(direction)
    return sum(1 for previous, current in zip(directions, directions[1:]) if previous != current)


def pivot_extremes(window: list[BacktestBar], *, noise_percent: float) -> tuple[list[float], list[float]]:
    if not window:
        return [], []
    closes = [bar.close for bar in window]
    lows: list[float] = []
    highs: list[float] = []
    for index in range(1, len(window) - 1):
        previous_close = closes[index - 1]
        current_close = closes[index]
        next_close = closes[index + 1]
        low_price = min(window[index].low, current_close)
        high_price = max(window[index].high, current_close)
        low_rebound = max(percent_delta(low_price, previous_close), percent_delta(low_price, next_close))
        high_reject = max(percent_delta(previous_close, high_price), percent_delta(next_close, high_price))
        if current_close <= previous_close and current_close <= next_close and low_rebound >= noise_percent:
            lows.append(low_price)
        if current_close >= previous_close and current_close >= next_close and high_reject >= noise_percent:
            highs.append(high_price)
    if not lows:
        lows = [min(bar.low for bar in window)]
    if not highs:
        highs = [max(bar.high for bar in window)]
    return lows[-12:], highs[-12:]


def blended_level(raw_level: float, pivots: list[float], weight: float) -> float:
    if not pivots:
        return raw_level
    pivot_level = percentile(pivots, 50.0)
    bounded_weight = clamp(weight, 0.0, 1.0)
    return raw_level * (1.0 - bounded_weight) + pivot_level * bounded_weight


def edge_touch_stats(
    window: list[BacktestBar],
    lower: float,
    upper: float,
    profile: MicroGridProfile,
) -> tuple[int, int, int, float]:
    span = upper - lower
    if span <= 0:
        return 0, 0, 0, 0.0
    lower_zone = lower + span * clamp(profile.edge_zone_fraction, 0.01, 0.49)
    upper_zone = upper - span * clamp(profile.edge_zone_fraction, 0.01, 0.49)
    response_move = span * clamp(profile.edge_response_fraction, 0.01, 0.90)
    adverse_move = span * clamp(profile.edge_response_max_adverse_fraction, 0.0, 0.90)
    events: list[tuple[int, str]] = []
    for index, bar in enumerate(window):
        touches_lower = bar.low <= lower_zone
        touches_upper = bar.high >= upper_zone
        if not touches_lower and not touches_upper:
            continue
        if touches_lower and touches_upper:
            mid = (lower + upper) / 2.0
            side = "lower" if bar.close <= mid else "upper"
        else:
            side = "lower" if touches_lower else "upper"
        if not events or events[-1][1] != side:
            events.append((index, side))
    lower_touches = sum(1 for _, side in events if side == "lower")
    upper_touches = sum(1 for _, side in events if side == "upper")
    alternations = sum(1 for previous, current in zip(events, events[1:]) if previous[1] != current[1])
    responses = 0
    max_lookahead = max(1, int(profile.edge_response_seconds))
    for index, side in events:
        future = window[index + 1 : min(len(window), index + 1 + max_lookahead)]
        if not future:
            continue
        for bar in future:
            if side == "lower":
                if adverse_move > 0 and bar.low <= lower - adverse_move:
                    break
                if bar.high >= lower_zone + response_move:
                    responses += 1
                    break
            else:
                if adverse_move > 0 and bar.high >= upper + adverse_move:
                    break
                if bar.low <= upper_zone - response_move:
                    responses += 1
                    break
    response_rate = responses / len(events) if events else 0.0
    return lower_touches, upper_touches, alternations, response_rate


def fit_dynamic_wick_model(
    window: list[BacktestBar],
    lower: float,
    upper: float,
    profile: MicroGridProfile,
) -> dict[str, dict[str, float | int | str]]:
    span = upper - lower
    defaults = default_dynamic_wick_model(profile)
    if span <= 0 or not window:
        return defaults

    lower_zone = lower + span * clamp(profile.edge_zone_fraction, 0.01, 0.49)
    upper_zone = upper - span * clamp(profile.edge_zone_fraction, 0.01, 0.49)
    lookahead = max(1, int(profile.edge_response_seconds))
    replay_lookahead = max(
        lookahead,
        max(1, int(profile.order_wait_seconds))
        + max(1, int(profile.max_hold_seconds))
        + max(1, int(profile.post_stop_lookahead_seconds))
        + 2,
    )
    success_move = span * clamp(profile.wick_success_fraction, 0.01, 0.90)
    long_samples: list[dict[str, Any]] = []
    short_samples: list[dict[str, Any]] = []
    min_event_gap = max(1, int(profile.wick_event_gap_seconds))
    last_long_event_index = -min_event_gap
    last_short_event_index = -min_event_gap
    for index, bar in enumerate(window):
        response_end_index = min(len(window), index + 1 + lookahead)
        replay_end_index = min(len(window), index + 1 + replay_lookahead)
        response_path = window[index:response_end_index]
        future = window[index + 1 : response_end_index]
        replay_path = window[index:replay_end_index]
        if not response_path or not future or not replay_path:
            continue
        if bar.low <= lower_zone and index - last_long_event_index >= min_event_gap:
            last_long_event_index = index
            depth = (bar.low - lower) / span
            max_rebound = max(item.high for item in future) - bar.low
            adverse = max(0.0, lower - min(item.low for item in future))
            long_samples.append(
                {
                    "entry_edge_fraction": depth,
                    "target_span_fraction": max_rebound / span,
                    "stop_span_fraction": adverse / span,
                    "success": max_rebound >= success_move,
                    "path": replay_path,
                }
            )
        if bar.high >= upper_zone and index - last_short_event_index >= min_event_gap:
            last_short_event_index = index
            depth = (upper - bar.high) / span
            max_rebound = bar.high - min(item.low for item in future)
            adverse = max(0.0, max(item.high for item in future) - upper)
            short_samples.append(
                {
                    "entry_edge_fraction": depth,
                    "target_span_fraction": max_rebound / span,
                    "stop_span_fraction": adverse / span,
                    "success": max_rebound >= success_move,
                    "path": replay_path,
                }
            )
    return {
        "long": dynamic_wick_side_model("long", lower, upper, long_samples, profile, defaults["long"]),
        "short": dynamic_wick_side_model("short", lower, upper, short_samples, profile, defaults["short"]),
    }


def default_dynamic_wick_model(profile: MicroGridProfile) -> dict[str, dict[str, float | int | str]]:
    side = default_dynamic_wick_side(profile)
    return {"long": dict(side), "short": dict(side)}


def default_dynamic_wick_side(profile: MicroGridProfile) -> dict[str, float | int | str]:
    return {
        "entry_edge_fraction": clamp(profile.precision_entry_fraction, profile.wick_min_entry_fraction, profile.wick_max_entry_fraction),
        "stop_span_fraction": clamp(profile.stop_fraction, profile.wick_min_stop_fraction, profile.wick_max_stop_fraction),
        "target_span_fraction": clamp(profile.target_fraction, profile.wick_min_target_fraction, profile.wick_max_target_fraction),
        "sample_count": 0,
        "success_rate": 0.0,
        "model": "default",
        "fill_count": 0,
        "fill_rate": 0.0,
        "stop_rate": 0.0,
        "same_bar_stop_rate": 0.0,
        "win_rate": 0.0,
        "recovery_rate": 0.0,
        "stop_then_target_rate": 0.0,
        "true_wrong_rate": 0.0,
        "avg_net_percent": 0.0,
        "lower_confidence_net_percent": 0.0,
        "score": 0.0,
        "hold_seconds": int(profile.max_hold_seconds),
    }


def dynamic_wick_side_model(
    side: str,
    lower: float,
    upper: float,
    samples: list[dict[str, Any]],
    profile: MicroGridProfile,
    default: dict[str, float | int | str],
) -> dict[str, float | int | str]:
    if len(samples) < profile.wick_min_samples:
        return default
    success_rate = sum(1 for sample in samples if bool(sample["success"])) / len(samples)
    quantile_model = quantile_wick_side_model(side, lower, upper, samples, profile, default, success_rate=success_rate)
    if profile.wick_model_mode == "ev":
        ev_model = ev_wick_side_model(side, lower, upper, samples, profile, default, success_rate=success_rate)
        if str(ev_model.get("model")) != "ev":
            return quantile_model
        if not profile.wick_ev_walk_forward_enabled:
            ev_model["walk_forward_validated"] = None
            ev_model["walk_forward_skipped_disabled"] = True
            return ev_model
        # Walk-forward: fit EV model on the earlier 2/3 of events (in time
        # order) and validate on the most recent 1/3. This guards against the
        # in-sample overfit that came from fitting and evaluating the model on
        # the same samples. A model whose validation-set avg_net is not
        # positive is downgraded to the (still sample-aware) quantile model so
        # the leg does not trade a geometry that only worked historically.
        # Walk-forward only runs when the validation slice is itself large
        # enough to be meaningful; otherwise the tightened confidence-z alone
        # governs overfit control and the EV model is trusted.
        split = max(profile.wick_min_samples, int(len(samples) * 2 / 3))
        refit_model = ev_wick_side_model(side, lower, upper, samples[:split], profile, default, success_rate=success_rate)
        if str(refit_model.get("model")) == "ev":
            ev_model = refit_model
        validation_samples = samples[split:]
        if len(validation_samples) < profile.wick_min_samples:
            ev_model["walk_forward_validated"] = None
            ev_model["validation_sample_count"] = len(validation_samples)
            ev_model["walk_forward_skipped_low_samples"] = True
            return ev_model
        validated = _validate_wick_ev_model(side, lower, upper, ev_model, validation_samples, profile)
        if validated:
            ev_model["walk_forward_validated"] = True
            ev_model["validation_sample_count"] = len(validation_samples)
            return ev_model
        ev_model["model"] = "quantile_walk_forward_rejected"
        ev_model["walk_forward_validated"] = False
        ev_model["validation_sample_count"] = len(validation_samples)
        return quantile_model
    return quantile_model


def _validate_wick_ev_model(
    side: str,
    lower: float,
    upper: float,
    ev_model: dict[str, Any],
    validation_samples: list[dict[str, Any]],
    profile: MicroGridProfile,
) -> bool:
    """Replay the chosen entry/stop/target geometry on out-of-sample paths."""
    if not validation_samples:
        return False
    span = upper - lower
    if span <= 0:
        return False
    entry_fraction = float(ev_model.get("entry_edge_fraction", 0.0))
    stop_fraction = float(ev_model.get("stop_span_fraction", 0.0))
    target_fraction = float(ev_model.get("target_span_fraction", 0.0))
    entry_price = lower + span * entry_fraction if side == "long" else upper - span * entry_fraction
    stop_price = entry_price - span * stop_fraction if side == "long" else entry_price + span * stop_fraction
    target_price = entry_price + span * target_fraction if side == "long" else entry_price - span * target_fraction
    cost = profile.round_trip_cost_percent
    net_total = 0.0
    for sample in validation_samples:
        path = sample.get("path")
        if not path:
            continue
        net = _wick_path_net_percent(side, entry_price, stop_price, target_price, path, cost)
        net_total += net
    avg_net = net_total / max(1, len(validation_samples))
    return avg_net > 0.0


def _wick_path_net_percent(
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    path: list[Any],
    round_trip_cost_percent: float,
) -> float:
    """Simulate a single long/short edge-reversion outcome on a bar path."""
    if not path:
        return -round_trip_cost_percent
    for bar in path[1:]:
        high = getattr(bar, "high", None)
        low = getattr(bar, "low", None)
        if high is None or low is None:
            continue
        if side == "long":
            if low <= stop_price:
                return -abs((entry_price - stop_price) / entry_price) * 100.0 - round_trip_cost_percent
            if high >= target_price:
                return abs((target_price - entry_price) / entry_price) * 100.0 - round_trip_cost_percent
        else:
            if high >= stop_price:
                return -abs((stop_price - entry_price) / entry_price) * 100.0 - round_trip_cost_percent
            if low <= target_price:
                return abs((entry_price - target_price) / entry_price) * 100.0 - round_trip_cost_percent
    return -round_trip_cost_percent


def quantile_wick_side_model(
    side: str,
    lower: float,
    upper: float,
    samples: list[dict[str, Any]],
    profile: MicroGridProfile,
    default: dict[str, float | int | str],
    *,
    success_rate: float,
) -> dict[str, float | int | str]:
    if success_rate < profile.wick_min_success_rate:
        return {
            **default,
            "sample_count": len(samples),
            "success_rate": success_rate,
            "model": "default_low_success",
        }
    samples = samples[-max(1, int(profile.wick_ev_max_samples)) :]
    entry_values = [float(sample["entry_edge_fraction"]) for sample in samples]
    stop_values = [float(sample["stop_span_fraction"]) for sample in samples]
    target_values = [float(sample["target_span_fraction"]) for sample in samples if bool(sample["success"])]
    if not target_values:
        target_values = [float(sample["target_span_fraction"]) for sample in samples]
    entry = percentile(entry_values, profile.wick_entry_quantile)
    stop = percentile(stop_values, profile.wick_stop_quantile)
    target = percentile(target_values, profile.wick_target_quantile)
    span = upper - lower
    result: dict[str, float | int] = {}
    if span > 0:
        entry_price = lower + span * entry if side == "long" else upper - span * entry
        stop_price = entry_price - span * stop if side == "long" else entry_price + span * stop
        target_price = entry_price + span * target if side == "long" else entry_price - span * target
        result = evaluate_wick_candidate(
            side,
            samples,
            profile,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )
    return {
        "entry_edge_fraction": clamp(entry, profile.wick_min_entry_fraction, profile.wick_max_entry_fraction),
        "stop_span_fraction": clamp(stop, profile.wick_min_stop_fraction, profile.wick_max_stop_fraction),
        "target_span_fraction": clamp(target, profile.wick_min_target_fraction, profile.wick_max_target_fraction),
        "sample_count": len(samples),
        "success_rate": success_rate,
        "model": "quantile",
        "fill_count": int(result.get("fill_count", 0)),
        "fill_rate": float(result.get("fill_rate", 0.0)),
        "stop_rate": float(result.get("stop_rate", 0.0)),
        "same_bar_stop_rate": float(result.get("same_bar_stop_rate", 0.0)),
        "win_rate": float(result.get("win_rate", 0.0)),
        "recovery_rate": float(result.get("recovery_rate", 0.0)),
        "stop_then_target_rate": float(result.get("stop_then_target_rate", 0.0)),
        "true_wrong_rate": float(result.get("true_wrong_rate", 0.0)),
        "avg_net_percent": float(result.get("avg_net_percent", 0.0)),
        "lower_confidence_net_percent": float(result.get("lower_confidence_net_percent", 0.0)),
        "score": wick_candidate_score(result, profile, entry_fraction=entry) if result else success_rate,
        "hold_seconds": dynamic_hold_seconds(result, profile) if result else int(profile.max_hold_seconds),
    }


def ev_wick_side_model(
    side: str,
    lower: float,
    upper: float,
    samples: list[dict[str, Any]],
    profile: MicroGridProfile,
    default: dict[str, float | int | str],
    *,
    success_rate: float,
) -> dict[str, float | int | str]:
    span = upper - lower
    if span <= 0:
        return default
    samples = samples[-max(1, int(profile.wick_ev_max_samples)) :]
    best: dict[str, float | int | str] | None = None
    for entry_fraction in wick_entry_candidates(profile):
        if entry_fraction < profile.wick_ev_min_entry_edge_fraction:
            continue
        entry_price = lower + span * entry_fraction if side == "long" else upper - span * entry_fraction
        for stop_fraction in wick_stop_candidates(profile):
            stop_price = entry_price - span * stop_fraction if side == "long" else entry_price + span * stop_fraction
            for target_fraction in wick_target_candidates(profile):
                target_price = entry_price + span * target_fraction if side == "long" else entry_price - span * target_fraction
                result = evaluate_wick_candidate(
                    side,
                    samples,
                    profile,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                )
                if not candidate_passes_ev_filters(result, profile):
                    continue
                score = wick_candidate_score(result, profile, entry_fraction=entry_fraction)
                if best is None or score > float(best["score"]):
                    best = {
                        "entry_edge_fraction": entry_fraction,
                        "stop_span_fraction": stop_fraction,
                        "target_span_fraction": target_fraction,
                        "sample_count": len(samples),
                        "success_rate": success_rate,
                        "model": "ev",
                        "fill_count": int(result["fill_count"]),
                        "fill_rate": float(result["fill_rate"]),
                        "stop_rate": float(result["stop_rate"]),
                        "same_bar_stop_rate": float(result["same_bar_stop_rate"]),
                        "win_rate": float(result["win_rate"]),
                        "recovery_rate": float(result["recovery_rate"]),
                        "stop_then_target_rate": float(result["stop_then_target_rate"]),
                        "true_wrong_rate": float(result["true_wrong_rate"]),
                        "avg_net_percent": float(result["avg_net_percent"]),
                        "lower_confidence_net_percent": float(result["lower_confidence_net_percent"]),
                        "score": score,
                        "hold_seconds": dynamic_hold_seconds(result, profile),
                    }
    if best is None:
        return {
            **default,
            "sample_count": len(samples),
            "success_rate": success_rate,
            "model": "default_no_positive_ev",
        }
    return best


def wick_entry_candidates(profile: MicroGridProfile) -> list[float]:
    return bounded_unique_candidates(
        [
            profile.wick_min_entry_fraction,
            0.0,
            0.08,
            0.12,
            profile.wick_max_entry_fraction,
        ],
        lower=profile.wick_min_entry_fraction,
        upper=profile.wick_max_entry_fraction,
    )


def wick_stop_candidates(profile: MicroGridProfile) -> list[float]:
    return bounded_unique_candidates(
        [
            profile.wick_min_stop_fraction,
            0.20,
            profile.wick_max_stop_fraction,
        ],
        lower=profile.wick_min_stop_fraction,
        upper=profile.wick_max_stop_fraction,
    )


def wick_target_candidates(profile: MicroGridProfile) -> list[float]:
    return bounded_unique_candidates(
        [
            profile.wick_min_target_fraction,
            0.32,
            profile.wick_max_target_fraction,
        ],
        lower=profile.wick_min_target_fraction,
        upper=profile.wick_max_target_fraction,
    )


def bounded_unique_candidates(values: list[float], *, lower: float, upper: float) -> list[float]:
    bounded = [round(clamp(value, lower, upper), 8) for value in values if math.isfinite(value)]
    return sorted(set(bounded))


def evaluate_wick_candidate(
    side: str,
    samples: list[dict[str, Any]],
    profile: MicroGridProfile,
    *,
    entry_price: float,
    stop_price: float,
    target_price: float,
) -> dict[str, float | int]:
    fills = 0
    wins = 0
    stops = 0
    same_bar_stops = 0
    recoveries = 0
    stop_then_targets = 0
    true_wrongs = 0
    net_percent_sum = 0.0
    net_percents: list[float] = []
    hold_seconds: list[float] = []
    for sample in samples:
        path = [bar for bar in sample.get("path", []) if isinstance(bar, BacktestBar)]
        outcome = simulate_wick_candidate_path(
            side,
            path,
            profile,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )
        if outcome is None:
            continue
        fills += 1
        net_percent = float(outcome["net_percent"])
        net_percent_sum += net_percent
        net_percents.append(net_percent)
        hold_seconds.append(float(outcome["hold_seconds"]))
        if outcome["exit_reason"] == "take_profit":
            wins += 1
        elif outcome["exit_reason"] in {"stop_loss", "same_bar_stop"}:
            stops += 1
            if outcome["exit_reason"] == "same_bar_stop":
                same_bar_stops += 1
            if bool(outcome.get("recovered_to_entry")):
                recoveries += 1
            if bool(outcome.get("recovered_to_target")):
                stop_then_targets += 1
            if bool(outcome.get("true_wrong_direction")):
                true_wrongs += 1
    sample_count = len(samples)
    fill_rate = fills / sample_count if sample_count else 0.0
    win_rate = wins / fills if fills else 0.0
    stop_rate = stops / fills if fills else 0.0
    same_bar_stop_rate = same_bar_stops / fills if fills else 0.0
    recovery_rate = recoveries / stops if stops else 0.0
    stop_then_target_rate = stop_then_targets / stops if stops else 0.0
    true_wrong_rate = true_wrongs / stops if stops else 0.0
    avg_net_percent = net_percent_sum / fills if fills else 0.0
    expected_net_percent = net_percent_sum / sample_count if sample_count else 0.0
    net_std = sample_std(net_percents)
    net_stderr = net_std / math.sqrt(fills) if fills > 0 else 0.0
    lower_confidence_net_percent = avg_net_percent - max(0.0, profile.wick_ev_confidence_z) * net_stderr
    avg_hold_seconds = sum(hold_seconds) / len(hold_seconds) if hold_seconds else float(profile.max_hold_seconds)
    return {
        "sample_count": sample_count,
        "fill_count": fills,
        "fill_rate": fill_rate,
        "win_rate": win_rate,
        "stop_rate": stop_rate,
        "same_bar_stop_rate": same_bar_stop_rate,
        "recovery_rate": recovery_rate,
        "stop_then_target_rate": stop_then_target_rate,
        "true_wrong_rate": true_wrong_rate,
        "avg_net_percent": avg_net_percent,
        "expected_net_percent": expected_net_percent,
        "lower_confidence_net_percent": lower_confidence_net_percent,
        "avg_hold_seconds": avg_hold_seconds,
    }


def simulate_wick_candidate_path(
    side: str,
    path: list[BacktestBar],
    profile: MicroGridProfile,
    *,
    entry_price: float,
    stop_price: float,
    target_price: float,
) -> dict[str, float | str | bool] | None:
    if not path or entry_price <= 0:
        return None
    fill_index: int | None = None
    wait_last = min(len(path) - 1, max(1, profile.order_wait_seconds) - 1)
    for index in range(0, wait_last + 1):
        bar = path[index]
        if side == "long" and bar.low <= entry_price:
            fill_index = index
            break
        if side == "short" and bar.high >= entry_price:
            fill_index = index
            break
    if fill_index is None:
        return None

    end_index = min(len(path) - 1, fill_index + max(1, profile.max_hold_seconds) - 1)
    exit_price = path[end_index].close
    exit_reason = "max_hold_exit"
    exit_index = end_index
    for index in range(fill_index, end_index + 1):
        bar = path[index]
        if side == "long":
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
        if hit_stop:
            exit_price = stop_price
            exit_reason = "same_bar_stop" if index == fill_index else "stop_loss"
            exit_index = index
            break
        if hit_target:
            exit_price = target_price
            exit_reason = "take_profit"
            exit_index = index
            break
    if side == "long":
        gross_percent = percent_delta(entry_price, exit_price)
    else:
        gross_percent = percent_delta(exit_price, entry_price)
    recovered_to_entry = False
    recovered_to_target = False
    continued_adverse = False
    if exit_reason in {"stop_loss", "same_bar_stop"}:
        lookahead_end = min(len(path) - 1, exit_index + max(1, int(profile.post_stop_lookahead_seconds)))
        future = path[exit_index + 1 : lookahead_end + 1]
        if side == "long":
            recovered_to_entry = any(bar.high >= entry_price for bar in future)
            recovered_to_target = any(bar.high >= target_price for bar in future)
            continued_adverse = any(bar.low < stop_price for bar in future)
        else:
            recovered_to_entry = any(bar.low <= entry_price for bar in future)
            recovered_to_target = any(bar.low <= target_price for bar in future)
            continued_adverse = any(bar.high > stop_price for bar in future)
    return {
        "exit_reason": exit_reason,
        "net_percent": gross_percent - profile.round_trip_cost_percent,
        "hold_seconds": max(1, (end_index - fill_index + 1) if exit_reason == "max_hold_exit" else (exit_index - fill_index + 1)),
        "recovered_to_entry": recovered_to_entry,
        "recovered_to_target": recovered_to_target,
        "true_wrong_direction": continued_adverse and not recovered_to_entry and not recovered_to_target,
    }


def candidate_passes_ev_filters(result: dict[str, float | int], profile: MicroGridProfile) -> bool:
    return (
        int(result["fill_count"]) >= max(1, profile.wick_ev_min_fills)
        and float(result["fill_rate"]) >= profile.wick_ev_min_fill_rate
        and float(result["win_rate"]) >= profile.wick_ev_min_win_rate
        and float(result["stop_rate"]) <= profile.wick_ev_max_stop_rate
        and float(result["same_bar_stop_rate"]) <= profile.wick_ev_max_same_bar_stop_rate
        and float(result["avg_net_percent"]) >= profile.wick_ev_min_avg_net_percent
        and float(result["expected_net_percent"]) > 0.0
    )


def wick_candidate_score(result: dict[str, float | int], profile: MicroGridProfile, *, entry_fraction: float = 0.0) -> float:
    expected_net = float(result["expected_net_percent"])
    avg_net = float(result["avg_net_percent"])
    lower_confidence_net = float(result["lower_confidence_net_percent"])
    win_rate = float(result["win_rate"])
    stop_rate = float(result["stop_rate"])
    same_bar_stop_rate = float(result["same_bar_stop_rate"])
    cost = profile.round_trip_cost_percent
    edge_depth_bonus = max(entry_fraction, 0.0) * max(cost, 0.03) * 0.20
    return (
        lower_confidence_net
        + avg_net * 0.20
        + expected_net * 0.08
        + win_rate * cost * 0.20
        + edge_depth_bonus
        - stop_rate * cost * 0.70
        - same_bar_stop_rate * cost * 1.50
    )


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(0.0, variance))


def realized_vol_percent(window: list[BacktestBar]) -> float:
    returns = [
        percent_delta(previous.close, current.close)
        for previous, current in zip(window, window[1:])
        if previous.close > 0 and current.close > 0
    ]
    return sample_std(returns)


def dynamic_hold_seconds(result: dict[str, float | int], profile: MicroGridProfile) -> int:
    if not profile.dynamic_hold_enabled:
        return int(profile.max_hold_seconds)
    learned = float(result.get("avg_hold_seconds") or profile.max_hold_seconds) * max(0.5, profile.dynamic_hold_multiplier)
    return int(clamp(learned, max(1, profile.dynamic_hold_min_seconds), max(1, profile.max_hold_seconds)))


def edge_reversal_readiness(
    window: list[BacktestBar],
    lower: float,
    upper: float,
    profile: MicroGridProfile,
) -> tuple[bool, bool]:
    detail = edge_reversal_readiness_detail(window, lower, upper, profile)
    return bool(detail["long_ready"]), bool(detail["short_ready"])


def edge_reversal_readiness_detail(
    window: list[BacktestBar],
    lower: float,
    upper: float,
    profile: MicroGridProfile,
) -> dict[str, float | bool | str]:
    span = upper - lower
    default = {
        "long_ready": False,
        "short_ready": False,
        "long_reason": "invalid_window",
        "short_reason": "invalid_window",
        "long_reversal_fraction": 0.0,
        "short_reversal_fraction": 0.0,
        "long_continuation_fraction": 0.0,
        "short_continuation_fraction": 0.0,
        "taker_buy_ratio": 0.5,
    }
    if span <= 0 or not window:
        return default
    recent = window[-max(2, int(profile.reversal_check_seconds)) :]
    current = recent[-1].close
    lower_zone = lower + span * clamp(profile.edge_proximity_fraction, 0.01, 0.49)
    upper_zone = upper - span * clamp(profile.edge_proximity_fraction, 0.01, 0.49)
    recent_lows = [bar.low for bar in recent]
    recent_highs = [bar.high for bar in recent]
    recent_low = min(recent_lows)
    recent_high = max(recent_highs)
    low_index = max(index for index, value in enumerate(recent_lows) if value == recent_low)
    high_index = max(index for index, value in enumerate(recent_highs) if value == recent_high)
    low_age = len(recent) - 1 - low_index
    high_age = len(recent) - 1 - high_index
    bounce_fraction = (current - recent_low) / span
    rejection_fraction = (recent_high - current) / span
    recent_eff = path_efficiency(recent)
    min_bounce = clamp(profile.reversal_min_bounce_fraction, 0.0, 0.5)
    max_continuation = max(0.0, profile.reversal_max_continuation_fraction)
    min_age = max(0, int(profile.reversal_min_extreme_age_seconds))
    taker_buy_ratio = taker_buy_quote_ratio(recent)

    long_post = recent[low_index:]
    short_post = recent[high_index:]
    long_continuation = post_extreme_continuation_fraction("long", long_post, span)
    short_continuation = post_extreme_continuation_fraction("short", short_post, span)

    long_reason = "ready"
    if recent_low > lower_zone:
        long_reason = "no_lower_edge_touch"
    elif low_age < min_age:
        long_reason = "lower_extreme_too_fresh"
    elif bounce_fraction < min_bounce:
        long_reason = "insufficient_lower_bounce"
    elif long_continuation > max_continuation:
        long_reason = "lower_edge_still_breaking_down"
    elif recent_eff > profile.reversal_max_adverse_efficiency:
        long_reason = "entry_path_too_directional"
    elif profile.reversal_flow_filter_enabled and taker_buy_ratio < profile.reversal_min_long_taker_buy_ratio:
        long_reason = "long_flow_not_recovering"

    short_reason = "ready"
    if recent_high < upper_zone:
        short_reason = "no_upper_edge_touch"
    elif high_age < min_age:
        short_reason = "upper_extreme_too_fresh"
    elif rejection_fraction < min_bounce:
        short_reason = "insufficient_upper_rejection"
    elif short_continuation > max_continuation:
        short_reason = "upper_edge_still_breaking_up"
    elif recent_eff > profile.reversal_max_adverse_efficiency:
        short_reason = "entry_path_too_directional"
    elif profile.reversal_flow_filter_enabled and taker_buy_ratio > profile.reversal_max_short_taker_buy_ratio:
        short_reason = "short_flow_not_exhausted"

    return {
        "long_ready": long_reason == "ready",
        "short_ready": short_reason == "ready",
        "long_reason": long_reason,
        "short_reason": short_reason,
        "long_reversal_fraction": max(0.0, bounce_fraction),
        "short_reversal_fraction": max(0.0, rejection_fraction),
        "long_continuation_fraction": long_continuation,
        "short_continuation_fraction": short_continuation,
        "taker_buy_ratio": taker_buy_ratio,
    }


def post_extreme_continuation_fraction(side: str, post_extreme: list[BacktestBar], span: float) -> float:
    if span <= 0 or len(post_extreme) < 2:
        return 0.0
    closes = [bar.close for bar in post_extreme if bar.close > 0]
    if len(closes) < 2:
        return 0.0
    slope = linear_slope(closes)
    if side == "long":
        return max(0.0, -slope * max(1, len(closes) - 1) / span)
    return max(0.0, slope * max(1, len(closes) - 1) / span)


def taker_buy_quote_ratio(window: list[BacktestBar]) -> float:
    quote_volume = sum(max(0.0, float(bar.quote_volume or 0.0)) for bar in window)
    if quote_volume <= 0:
        return 0.5
    taker_buy = sum(max(0.0, float(bar.taker_buy_quote_volume or 0.0)) for bar in window)
    return clamp(taker_buy / quote_volume, 0.0, 1.0)


def path_efficiency(window: list[BacktestBar]) -> float:
    travel = sum(abs(current.close - previous.close) for previous, current in zip(window, window[1:]))
    displacement = abs(window[-1].close - window[0].open)
    return displacement / travel if travel > 0 else 0.0


def linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    n = len(values)
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    denom = sum((index - mean_x) ** 2 for index in range(n))
    if denom <= 0:
        return 0.0
    return sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values)) / denom


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(100.0, percent)) / 100.0 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def percent_delta(start: float, end: float) -> float:
    return ((end - start) / start) * 100.0 if start > 0 else 0.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def parse_iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def ms_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ms_to_date(value: int) -> date:
    return datetime.fromtimestamp(value / 1000, UTC).date()


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def empty_scan_diagnostics() -> dict[str, Any]:
    return {
        "evaluated_windows": 0,
        "cooldown_windows": 0,
        "passed_windows": 0,
        "passed_rate": 0.0,
        "rejection_counts": {},
    }


def empty_order_stats() -> dict[str, Any]:
    return {
        "orders_created": 0,
        "orders_filled": 0,
        "orders_expired": 0,
        "orders_same_bar_stop": 0,
        "orders_rejected_sizing": 0,
        "fill_rate": 0.0,
    }


def merge_order_stats(total: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key == "fill_rate":
            continue
        total[key] = total.get(key, 0) + value
    total["fill_rate"] = round(
        (total.get("orders_filled", 0) + total.get("orders_same_bar_stop", 0)) / total["orders_created"],
        8,
    ) if total.get("orders_created") else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
