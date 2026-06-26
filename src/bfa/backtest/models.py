"""Backtest data models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class BacktestBar:
    symbol: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    taker_buy_quote_volume: float | None = None

    @classmethod
    def from_binance_kline(cls, symbol: str, row: Iterable[Any]) -> "BacktestBar":
        values = list(row)
        if len(values) < 8:
            raise ValueError("Binance kline row must contain at least 8 fields")
        taker_buy_quote_volume = values[10] if len(values) > 10 else None
        return cls(
            symbol=symbol.upper(),
            open_time=int(values[0]),
            open=float(values[1]),
            high=float(values[2]),
            low=float(values[3]),
            close=float(values[4]),
            volume=float(values[5]),
            close_time=int(values[6]),
            quote_volume=float(values[7]),
            taker_buy_quote_volume=_optional_float(taker_buy_quote_volume),
        )

    @property
    def open_time_iso(self) -> str:
        return _ms_to_iso(self.open_time)

    @property
    def close_time_iso(self) -> str:
        return _ms_to_iso(self.close_time)

    @property
    def range_percent(self) -> float:
        if self.close <= 0:
            return 0.0
        return ((self.high - self.low) / self.close) * 100.0

    @property
    def taker_buy_sell_ratio(self) -> float | None:
        if self.taker_buy_quote_volume is None:
            return None
        sell_quote = self.quote_volume - self.taker_buy_quote_volume
        if sell_quote <= 0:
            return None
        return self.taker_buy_quote_volume / sell_quote

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "open_time": self.open_time,
            "open_time_iso": self.open_time_iso,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_time": self.close_time,
            "close_time_iso": self.close_time_iso,
            "quote_volume": self.quote_volume,
            "taker_buy_quote_volume": self.taker_buy_quote_volume,
            "taker_buy_sell_ratio": self.taker_buy_sell_ratio,
            "range_percent": self.range_percent,
        }


@dataclass(frozen=True)
class BacktestConfig:
    name: str = "balanced"
    strategy_type: str = "hot_momentum"
    account_capital_usdt: float = 100.0
    max_leverage: float = 3.0
    max_position_notional_usdt: float = 20.0
    max_risk_per_trade_usdt: float = 1.0
    max_daily_loss_usdt: float = 3.0
    max_open_positions: int = 2
    taker_fee_rate: float = 0.0004
    slippage_bps: float = 5.0
    lookback_bars: int = 3
    min_momentum_percent: float = 0.8
    min_quote_volume_usdt: float = 1_000_000.0
    min_taker_buy_sell_ratio: float = 1.02
    max_signal_bar_range_percent: float = 8.0
    stop_loss_percent: float = 1.5
    take_profit_percent: float = 2.4
    max_hold_bars: int = 6
    cooldown_bars: int = 2
    trailing_stop_enabled: bool = False
    trailing_activate_r: float = 0.8
    trailing_lock_r: float = 0.2
    trailing_giveback_r: float = 0.55
    simulation_min_executable_notional_usdt: float = 5.0
    setup_profile: dict[str, Any] = field(default_factory=dict)

    def with_overrides(self, **overrides: Any) -> "BacktestConfig":
        return replace(self, **overrides)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "strategy_type": self.strategy_type,
            "account_capital_usdt": self.account_capital_usdt,
            "max_leverage": self.max_leverage,
            "max_position_notional_usdt": self.max_position_notional_usdt,
            "max_position_margin_usdt": self.max_position_notional_usdt / self.max_leverage,
            "max_risk_per_trade_usdt": self.max_risk_per_trade_usdt,
            "max_daily_loss_usdt": self.max_daily_loss_usdt,
            "max_open_positions": self.max_open_positions,
            "taker_fee_rate": self.taker_fee_rate,
            "slippage_bps": self.slippage_bps,
            "lookback_bars": self.lookback_bars,
            "min_momentum_percent": self.min_momentum_percent,
            "min_quote_volume_usdt": self.min_quote_volume_usdt,
            "min_taker_buy_sell_ratio": self.min_taker_buy_sell_ratio,
            "max_signal_bar_range_percent": self.max_signal_bar_range_percent,
            "stop_loss_percent": self.stop_loss_percent,
            "take_profit_percent": self.take_profit_percent,
            "max_hold_bars": self.max_hold_bars,
            "cooldown_bars": self.cooldown_bars,
            "trailing_stop_enabled": self.trailing_stop_enabled,
            "trailing_activate_r": self.trailing_activate_r,
            "trailing_lock_r": self.trailing_lock_r,
            "trailing_giveback_r": self.trailing_giveback_r,
            "simulation_min_executable_notional_usdt": self.simulation_min_executable_notional_usdt,
            "setup_profile": dict(self.setup_profile),
        }


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    notional_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    slippage_usdt: float
    net_pnl_usdt: float
    exit_reason: str
    mfe_percent: float = 0.0
    mae_percent: float = 0.0
    reason_codes: list[str] = field(default_factory=list)

    @property
    def won(self) -> bool:
        return self.net_pnl_usdt > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "notional_usdt": self.notional_usdt,
            "gross_pnl_usdt": self.gross_pnl_usdt,
            "fees_usdt": self.fees_usdt,
            "slippage_usdt": self.slippage_usdt,
            "net_pnl_usdt": self.net_pnl_usdt,
            "exit_reason": self.exit_reason,
            "mfe_percent": self.mfe_percent,
            "mae_percent": self.mae_percent,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    start_time: str | None
    end_time: str | None
    symbols: list[str]
    initial_capital_usdt: float
    trades: list[BacktestTrade]
    rejected_signals: int = 0
    skipped_daily_loss_signals: int = 0
    skipped_concurrency_signals: int = 0

    @property
    def net_pnl_usdt(self) -> float:
        return sum(trade.net_pnl_usdt for trade in self.trades)

    @property
    def final_capital_usdt(self) -> float:
        return self.initial_capital_usdt + self.net_pnl_usdt

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for trade in self.trades if trade.net_pnl_usdt > 0)

    @property
    def losses(self) -> int:
        return sum(1 for trade in self.trades if trade.net_pnl_usdt < 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trade_count if self.trade_count else 0.0

    @property
    def expectancy_usdt(self) -> float:
        return self.net_pnl_usdt / self.trade_count if self.trade_count else 0.0

    @property
    def fees_usdt(self) -> float:
        return sum(trade.fees_usdt for trade in self.trades)

    @property
    def slippage_usdt(self) -> float:
        return sum(trade.slippage_usdt for trade in self.trades)

    @property
    def max_drawdown_usdt(self) -> float:
        peak = self.initial_capital_usdt
        equity = self.initial_capital_usdt
        drawdown = 0.0
        for trade in sorted(self.trades, key=lambda item: item.exit_time):
            equity += trade.net_pnl_usdt
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return abs(drawdown)

    @property
    def profit_factor(self) -> float | None:
        gross_profit = sum(trade.net_pnl_usdt for trade in self.trades if trade.net_pnl_usdt > 0)
        gross_loss = abs(sum(trade.net_pnl_usdt for trade in self.trades if trade.net_pnl_usdt < 0))
        if gross_loss == 0:
            return None if gross_profit == 0 else float("inf")
        return gross_profit / gross_loss

    def summary(self) -> dict[str, Any]:
        profit_factor = self.profit_factor
        return {
            "config_name": self.config.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "symbols": list(self.symbols),
            "initial_capital_usdt": round(self.initial_capital_usdt, 8),
            "final_capital_usdt": round(self.final_capital_usdt, 8),
            "net_pnl_usdt": round(self.net_pnl_usdt, 8),
            "return_percent": round((self.net_pnl_usdt / self.initial_capital_usdt) * 100.0, 8)
            if self.initial_capital_usdt
            else 0.0,
            "trade_count": self.trade_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 8),
            "expectancy_usdt": round(self.expectancy_usdt, 8),
            "fees_usdt": round(self.fees_usdt, 8),
            "slippage_usdt": round(self.slippage_usdt, 8),
            "max_drawdown_usdt": round(self.max_drawdown_usdt, 8),
            "profit_factor": _round_optional(profit_factor),
            "rejected_signals": self.rejected_signals,
            "skipped_daily_loss_signals": self.skipped_daily_loss_signals,
            "skipped_concurrency_signals": self.skipped_concurrency_signals,
        }

    def to_dict(self, *, include_trades: bool = True) -> dict[str, Any]:
        payload = {
            "schema": "bfa_backtest_result_v1",
            "summary": self.summary(),
            "config": self.config.to_dict(),
        }
        if include_trades:
            payload["trades"] = [trade.to_dict() for trade in self.trades]
        return payload


def built_in_variants() -> dict[str, BacktestConfig]:
    base = BacktestConfig()
    return {
        "strict": base.with_overrides(
            name="strict",
            min_momentum_percent=1.6,
            min_taker_buy_sell_ratio=1.08,
            max_signal_bar_range_percent=6.0,
            stop_loss_percent=1.2,
            take_profit_percent=2.0,
            max_hold_bars=4,
        ),
        "balanced": base,
        "aggressive": base.with_overrides(
            name="aggressive",
            min_momentum_percent=0.4,
            min_taker_buy_sell_ratio=1.0,
            max_signal_bar_range_percent=12.0,
            stop_loss_percent=2.0,
            take_profit_percent=3.2,
            max_hold_bars=8,
        ),
        "quant_setup": base.with_overrides(
            name="quant_setup",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=10.0,
            max_position_notional_usdt=25.0,
            max_risk_per_trade_usdt=0.6,
            max_daily_loss_usdt=2.0,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=1_000_000.0,
            cooldown_bars=1,
        ),
        "quant_setup_selective": base.with_overrides(
            name="quant_setup_selective",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=10.0,
            max_position_notional_usdt=18.0,
            max_risk_per_trade_usdt=0.45,
            max_daily_loss_usdt=1.5,
            max_open_positions=1,
            lookback_bars=12,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=4,
            max_hold_bars=4,
            setup_profile={
                "name": "selective",
                "min_edge": 28.0,
                "min_confidence": 0.68,
                "min_risk_reward": 1.45,
                "max_stop_distance_percent": 2.6,
                "min_indicator_sample_size": 8,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "max_notional_fraction": 0.65,
                "stop_distance_multiplier": 0.85,
                "target_distance_multiplier": 1.08,
            },
        ),
        "quant_setup_scalp": base.with_overrides(
            name="quant_setup_scalp",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=10.0,
            max_position_notional_usdt=15.0,
            max_risk_per_trade_usdt=0.35,
            max_daily_loss_usdt=1.2,
            max_open_positions=1,
            lookback_bars=6,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=6,
            max_hold_bars=3,
            setup_profile={
                "name": "scalp",
                "min_edge": 32.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.3,
                "max_stop_distance_percent": 1.8,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "max_notional_fraction": 0.5,
                "stop_distance_multiplier": 0.7,
                "target_distance_multiplier": 0.95,
            },
        ),
        "quant_setup_selective_guarded": base.with_overrides(
            name="quant_setup_selective_guarded",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=10.0,
            max_position_notional_usdt=16.0,
            max_risk_per_trade_usdt=0.35,
            max_daily_loss_usdt=1.2,
            max_open_positions=1,
            lookback_bars=12,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=5,
            max_hold_bars=4,
            setup_profile={
                "name": "selective_guarded",
                "min_edge": 32.0,
                "min_confidence": 0.72,
                "min_risk_reward": 1.6,
                "max_stop_distance_percent": 2.2,
                "min_indicator_sample_size": 8,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "max_notional_fraction": 0.55,
                "stop_distance_multiplier": 0.78,
                "target_distance_multiplier": 1.12,
                "disabled_sides": ("short",),
                "excluded_symbols": ("BICOUSDT", "BEATUSDT", "SLXUSDT"),
            },
        ),
        "quant_setup_loss_recalibrated": base.with_overrides(
            name="quant_setup_loss_recalibrated",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=10.0,
            max_position_notional_usdt=14.0,
            max_risk_per_trade_usdt=0.3,
            max_daily_loss_usdt=1.0,
            max_open_positions=1,
            lookback_bars=14,
            min_quote_volume_usdt=10_000_000.0,
            cooldown_bars=6,
            max_hold_bars=3,
            setup_profile={
                "name": "loss_recalibrated",
                "min_edge": 38.0,
                "min_confidence": 0.74,
                "min_risk_reward": 1.75,
                "max_stop_distance_percent": 1.9,
                "min_indicator_sample_size": 10,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "require_open_interest": True,
                "min_quote_volume_usdt": 10_000_000.0,
                "min_abs_momentum_percent": 0.8,
                "min_volume_impulse_percent": 10.0,
                "max_notional_fraction": 0.45,
                "stop_distance_multiplier": 0.72,
                "target_distance_multiplier": 1.18,
                "disabled_sides": ("short",),
                "excluded_symbols": (
                    "BTWUSDT",
                    "GUAUSDT",
                    "HEIUSDT",
                    "SLXUSDT",
                    "SANDUSDT",
                    "BICOUSDT",
                    "BEATUSDT",
                    "XLMUSDT",
                ),
                "blocked_setup_reasons": ("crowding_risk",),
                "blocked_factor_reasons": (
                    "taker_flow_acceleration",
                    "volume_neutral",
                    "rsi_bearish_momentum",
                    "close_near_range_low",
                ),
                "blocked_factor_names": (
                    "taker_flow",
                    "volume_impulse",
                    "rsi_regime",
                    "momentum",
                    "trend_structure",
                ),
            },
        ),
        "quant_setup_high_frequency_guarded": base.with_overrides(
            name="quant_setup_high_frequency_guarded",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=24.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.0,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=10_000_000.0,
            cooldown_bars=1,
            max_hold_bars=3,
            trailing_stop_enabled=True,
            trailing_activate_r=0.75,
            trailing_lock_r=0.18,
            trailing_giveback_r=0.45,
            setup_profile={
                "name": "high_frequency_guarded",
                "min_edge": 30.0,
                "min_confidence": 0.68,
                "min_risk_reward": 1.25,
                "max_stop_distance_percent": 1.6,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 10_000_000.0,
                "min_abs_momentum_percent": 0.55,
                "min_volume_impulse_percent": 4.0,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.68,
                "target_distance_multiplier": 0.9,
                "require_directional_confluence": True,
                "min_directional_confluence": 5,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.05,
                "min_rsi_for_long": 42.0,
                "max_rsi_for_short": 58.0,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_high_frequency_flow_guarded": base.with_overrides(
            name="quant_setup_high_frequency_flow_guarded",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=24.0,
            max_risk_per_trade_usdt=0.34,
            max_daily_loss_usdt=0.75,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=1,
            max_hold_bars=3,
            trailing_stop_enabled=True,
            trailing_activate_r=0.55,
            trailing_lock_r=0.12,
            trailing_giveback_r=0.3,
            setup_profile={
                "name": "high_frequency_flow_guarded",
                "min_edge": 22.0,
                "min_confidence": 0.6,
                "min_risk_reward": 1.25,
                "max_stop_distance_percent": 1.9,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.3,
                "min_volume_impulse_percent": 5.0,
                "min_directional_taker_flow_edge": 0.04,
                "max_notional_fraction": 0.68,
                "stop_distance_multiplier": 0.78,
                "target_distance_multiplier": 1.0,
                "require_directional_confluence": True,
                "min_directional_confluence": 5,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.03,
                "min_rsi_for_long": 45.0,
                "max_rsi_for_short": 55.0,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_live_action_flow": base.with_overrides(
            name="quant_setup_live_action_flow",
            strategy_type="quant_setup",
            account_capital_usdt=100.0,
            max_leverage=30.0,
            max_position_notional_usdt=120.0,
            max_risk_per_trade_usdt=0.65,
            max_daily_loss_usdt=3.0,
            max_open_positions=4,
            lookback_bars=6,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=1,
            max_hold_bars=144,
            trailing_stop_enabled=True,
            trailing_activate_r=1.0,
            trailing_lock_r=0.25,
            trailing_giveback_r=0.65,
            setup_profile={
                "name": "live_action_flow",
                "min_edge": 14.0,
                "min_confidence": 0.54,
                "min_risk_reward": 2.0,
                "max_stop_distance_percent": 2.6,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 5_000_000.0,
                "min_abs_momentum_percent": 0.12,
                "min_volume_impulse_percent": None,
                "min_directional_taker_flow_edge": 0.0,
                "max_notional_fraction": 0.86,
                "stop_distance_multiplier": 0.82,
                "target_distance_multiplier": 1.8,
                "require_directional_confluence": False,
                "min_directional_confluence": 3,
                "block_adverse_trend_vwap": False,
                "block_hot_micro_reversal": False,
                "block_volume_fade": False,
                "block_trend_edge_exhaustion": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.12,
                "min_rsi_for_long": 34.0,
                "max_rsi_for_short": 66.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.12,
                "limit_entry_min_offset_percent": 0.02,
                "limit_entry_max_offset_percent": 0.42,
                "limit_entry_max_wait_seconds": 75,
                "trend_near_structure_entry_enabled": True,
                "trend_near_structure_zone_percent": 18.0,
                "trend_near_structure_rebound_zone_percent": 42.0,
                "trend_near_structure_min_gap_percent": 0.18,
                "trend_near_structure_max_offset_percent": 1.65,
                "trend_near_structure_breakout_min_volume_change_percent": 80.0,
                "trend_near_structure_breakout_min_momentum_percent": 1.2,
                "trend_near_structure_breakout_min_taker_edge": 0.12,
                "min_post_cost_edge_ratio": 1.6,
                "fee_bps": 2.0,
                "slippage_bps": 2.0,
                "require_mtf_alignment": False,
                "min_mtf_alignment_score": 0,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.0,
                "adaptive_stop_realized_volatility_multiplier": 1.35,
                "adaptive_target_volatility_multiplier": 1.7,
                "time_exit_only_when_not_profitable": True,
                "time_exit_use_config_max_hold_only": True,
                "early_exit_enabled": True,
                "early_exit_min_seconds": 1800,
                "early_exit_min_favorable_r": 0.75,
                "early_exit_max_adverse_r": 0.45,
                "early_exit_min_adverse_votes": 3,
                "early_exit_flow_edge": 0.18,
                "regime_router_enforced": True,
                "require_entry_quality": True,
                "min_entry_quality_score": 4,
                "require_limit_entry_quality": True,
                "min_limit_entry_quality_score": 3,
                "allow_counter_signal": False,
                "min_counter_signal_score": 5,
                "enable_orderly_range": False,
                "min_orderly_range_score": 5,
                "orderly_range_min_width_percent": 0.28,
                "orderly_range_max_width_percent": 3.4,
                "orderly_range_max_trend_abs_percent": 0.42,
                "orderly_range_max_volume_cv": 0.62,
                "orderly_range_min_touch_count": 2,
                "orderly_range_max_path_efficiency": 0.55,
                "orderly_range_low_zone_percent": 28.0,
                "orderly_range_high_zone_percent": 72.0,
                "orderly_range_min_edge_alternations": 1,
                "orderly_range_min_mid_cross_count": 0,
                "orderly_range_min_width_cost_ratio": 1.8,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_ml_trend": base.with_overrides(
            name="quant_setup_ml_trend",
            strategy_type="quant_setup",
            # aligned with the real live account caps
            account_capital_usdt=100.0,
            max_leverage=30.0,
            max_position_notional_usdt=600.0,
            max_risk_per_trade_usdt=4.0,
            max_daily_loss_usdt=10.0,
            max_open_positions=5,
            lookback_bars=6,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=1,
            max_hold_bars=144,
            trailing_stop_enabled=True,
            trailing_activate_r=1.0,
            trailing_lock_r=0.25,
            trailing_giveback_r=0.65,
            setup_profile={
                "name": "ml_trend",
                # ML filter replaces the boolean-gate stack
                "use_ml_trend_filter": True,
                "ml_trend_model_path": "data/research/trend_filter_v1.txt",
                "ml_trend_threshold": 0.55,
                # keep the geometry repair from Phase 71
                "min_edge": 6.0,
                "min_confidence": 0.0,
                "min_risk_reward": 1.5,
                "max_stop_distance_percent": 2.6,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": False,  # ML supersedes
                "require_rsi_not_extreme": False,
                "min_quote_volume_usdt": 5_000_000.0,
                "min_abs_momentum_percent": 0.08,
                "max_notional_fraction": 0.86,
                "stop_distance_multiplier": 0.82,
                "target_distance_multiplier": 1.8,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.12,
                "limit_entry_min_offset_percent": 0.02,
                "limit_entry_max_offset_percent": 0.42,
                "limit_entry_max_wait_seconds": 75,
                "min_post_cost_edge_ratio": 1.2,
                "fee_bps": 2.0,
                "slippage_bps": 2.0,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.0,
                "adaptive_stop_realized_volatility_multiplier": 1.35,
                "adaptive_target_volatility_multiplier": 1.7,
                "time_exit_only_when_not_profitable": True,
                "time_exit_use_config_max_hold_only": True,
                "regime_router_enforced": True,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_ldc": base.with_overrides(
            name="quant_setup_ldc",
            strategy_type="quant_setup",
            account_capital_usdt=100.0,
            max_leverage=30.0,
            max_position_notional_usdt=600.0,
            max_risk_per_trade_usdt=4.0,
            max_daily_loss_usdt=10.0,
            max_open_positions=5,
            lookback_bars=6,
            min_quote_volume_usdt=5_000_000.0,
            cooldown_bars=1,
            max_hold_bars=144,
            trailing_stop_enabled=True,
            trailing_activate_r=1.0,
            trailing_lock_r=0.25,
            trailing_giveback_r=0.65,
            setup_profile={
                "name": "ldc",
                # LDC confidence modifier (flag default off in the dataclass;
                # this variant turns it on). Artifact path points at the
                # offline-built reference dataset. Enable live by setting
                # BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_ldc ONLY after the
                # offline report shows lift > 1.0 (see train_ldc_classifier.py).
                "use_ldc_confidence_modifier": True,
                "ldc_artifact_path": "data/research/ldc/ldc_reference.npz",
                "ldc_blend_strength": 0.06,
                "ldc_blend_mode": "linear",
                "ldc_min_voters": 3,
                "ldc_confidence_ceiling": 0.95,
                # keep the geometry repair from Phase 71
                "min_edge": 6.0,
                "min_confidence": 0.0,
                "min_risk_reward": 1.5,
                "max_stop_distance_percent": 2.6,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": False,
                "require_rsi_not_extreme": False,
                "min_quote_volume_usdt": 5_000_000.0,
                "min_abs_momentum_percent": 0.08,
                "max_notional_fraction": 0.86,
                "stop_distance_multiplier": 0.82,
                "target_distance_multiplier": 1.8,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.12,
                "limit_entry_min_offset_percent": 0.02,
                "limit_entry_max_offset_percent": 0.42,
                "limit_entry_max_wait_seconds": 75,
                "min_post_cost_edge_ratio": 1.2,
                "fee_bps": 2.0,
                "slippage_bps": 2.0,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.0,
                "adaptive_stop_realized_volatility_multiplier": 1.35,
                "adaptive_target_volatility_multiplier": 1.7,
                "time_exit_only_when_not_profitable": True,
                "time_exit_use_config_max_hold_only": True,
                "regime_router_enforced": True,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_limit_mtf_cost_guarded": base.with_overrides(
            name="quant_setup_limit_mtf_cost_guarded",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=1,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.32,
            trailing_lock_r=0.08,
            trailing_giveback_r=0.18,
            setup_profile={
                "name": "limit_mtf_cost_guarded",
                "min_edge": 34.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.4,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.95,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.18,
                "limit_entry_min_offset_percent": 0.04,
                "limit_entry_max_offset_percent": 0.48,
                "limit_entry_max_wait_seconds": 180,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.1,
                "adaptive_stop_realized_volatility_multiplier": 1.6,
                "adaptive_target_volatility_multiplier": 1.9,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_signal_quality_range_counter": base.with_overrides(
            name="quant_setup_signal_quality_range_counter",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=1,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.32,
            trailing_lock_r=0.08,
            trailing_giveback_r=0.18,
            setup_profile={
                "name": "signal_quality_range_counter",
                "min_edge": 34.0,
                "min_confidence": 0.69,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.4,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.95,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.18,
                "limit_entry_min_offset_percent": 0.04,
                "limit_entry_max_offset_percent": 0.48,
                "limit_entry_max_wait_seconds": 180,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.1,
                "adaptive_stop_realized_volatility_multiplier": 1.6,
                "adaptive_target_volatility_multiplier": 1.9,
                "require_entry_quality": True,
                "min_entry_quality_score": 6,
                "allow_counter_signal": True,
                "min_counter_signal_score": 6,
                "enable_orderly_range": True,
                "min_orderly_range_score": 6,
                "orderly_range_min_width_percent": 0.35,
                "orderly_range_max_width_percent": 2.2,
                "orderly_range_max_trend_abs_percent": 0.22,
                "orderly_range_max_volume_cv": 0.45,
                "orderly_range_min_touch_count": 2,
                "orderly_range_max_path_efficiency": 0.42,
                "orderly_range_low_zone_percent": 24.0,
                "orderly_range_high_zone_percent": 76.0,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_signal_quality_range_refined": base.with_overrides(
            name="quant_setup_signal_quality_range_refined",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=9,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=2,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.24,
            trailing_lock_r=0.06,
            trailing_giveback_r=0.14,
            setup_profile={
                "name": "signal_quality_range_refined",
                "min_edge": 36.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.2,
                "min_indicator_sample_size": 6,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.9,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.16,
                "limit_entry_min_offset_percent": 0.06,
                "limit_entry_max_offset_percent": 0.58,
                "limit_entry_max_wait_seconds": 90,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.05,
                "adaptive_stop_realized_volatility_multiplier": 1.45,
                "adaptive_target_volatility_multiplier": 1.8,
                "require_entry_quality": True,
                "min_entry_quality_score": 6,
                "allow_counter_signal": True,
                "min_counter_signal_score": 7,
                "enable_orderly_range": True,
                "min_orderly_range_score": 10,
                "orderly_range_min_width_percent": 0.75,
                "orderly_range_max_width_percent": 2.6,
                "orderly_range_max_trend_abs_percent": 0.18,
                "orderly_range_max_volume_cv": 0.32,
                "orderly_range_min_touch_count": 2,
                "orderly_range_max_path_efficiency": 0.28,
                "orderly_range_low_zone_percent": 20.0,
                "orderly_range_high_zone_percent": 80.0,
                "orderly_range_min_edge_alternations": 2,
                "orderly_range_min_mid_cross_count": 1,
                "orderly_range_min_width_cost_ratio": 5.0,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_orderly_range_only_refined": base.with_overrides(
            name="quant_setup_orderly_range_only_refined",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=9,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=2,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.24,
            trailing_lock_r=0.06,
            trailing_giveback_r=0.14,
            setup_profile={
                "name": "orderly_range_only_refined",
                "min_edge": 36.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.2,
                "min_indicator_sample_size": 6,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.9,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.16,
                "limit_entry_min_offset_percent": 0.06,
                "limit_entry_max_offset_percent": 0.58,
                "limit_entry_max_wait_seconds": 90,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.05,
                "adaptive_stop_realized_volatility_multiplier": 1.45,
                "adaptive_target_volatility_multiplier": 1.8,
                "require_entry_quality": True,
                "min_entry_quality_score": 6,
                "allow_counter_signal": False,
                "min_counter_signal_score": 7,
                "enable_orderly_range": True,
                "min_orderly_range_score": 10,
                "orderly_range_min_width_percent": 0.75,
                "orderly_range_max_width_percent": 2.6,
                "orderly_range_max_trend_abs_percent": 0.18,
                "orderly_range_max_volume_cv": 0.32,
                "orderly_range_min_touch_count": 2,
                "orderly_range_max_path_efficiency": 0.28,
                "orderly_range_low_zone_percent": 20.0,
                "orderly_range_high_zone_percent": 80.0,
                "orderly_range_min_edge_alternations": 2,
                "orderly_range_min_mid_cross_count": 1,
                "orderly_range_min_width_cost_ratio": 5.0,
                "blocked_setup_reasons": (
                    "crowding_risk",
                    "signal_mode:trend_follow",
                    "signal_mode:counter_signal",
                ),
            },
        ),
        "quant_setup_limit_mtf_cost_no_time_exit": base.with_overrides(
            name="quant_setup_limit_mtf_cost_no_time_exit",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=1,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.32,
            trailing_lock_r=0.08,
            trailing_giveback_r=0.18,
            setup_profile={
                "name": "limit_mtf_cost_no_time_exit",
                "min_edge": 34.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.4,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.95,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.18,
                "limit_entry_min_offset_percent": 0.04,
                "limit_entry_max_offset_percent": 0.48,
                "limit_entry_max_wait_seconds": 180,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.1,
                "adaptive_stop_realized_volatility_multiplier": 1.6,
                "adaptive_target_volatility_multiplier": 1.9,
                "time_exit_enabled": False,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_limit_mtf_cost_early_exit": base.with_overrides(
            name="quant_setup_limit_mtf_cost_early_exit",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=27.0,
            max_risk_per_trade_usdt=0.36,
            max_daily_loss_usdt=1.2,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=8_000_000.0,
            cooldown_bars=1,
            max_hold_bars=2,
            trailing_stop_enabled=True,
            trailing_activate_r=0.32,
            trailing_lock_r=0.08,
            trailing_giveback_r=0.18,
            setup_profile={
                "name": "limit_mtf_cost_early_exit",
                "min_edge": 34.0,
                "min_confidence": 0.7,
                "min_risk_reward": 1.35,
                "max_stop_distance_percent": 2.4,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 8_000_000.0,
                "min_abs_momentum_percent": 0.4,
                "min_volume_impulse_percent": 8.0,
                "min_directional_taker_flow_edge": 0.05,
                "max_notional_fraction": 0.72,
                "stop_distance_multiplier": 0.95,
                "target_distance_multiplier": 1.05,
                "require_directional_confluence": True,
                "min_directional_confluence": 6,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.04,
                "min_rsi_for_long": 44.0,
                "max_rsi_for_short": 56.0,
                "entry_order_type": "limit",
                "limit_entry_retrace_fraction": 0.18,
                "limit_entry_min_offset_percent": 0.04,
                "limit_entry_max_offset_percent": 0.48,
                "limit_entry_max_wait_seconds": 180,
                "min_post_cost_edge_ratio": 5.0,
                "fee_bps": 4.0,
                "slippage_bps": 3.0,
                "require_mtf_alignment": True,
                "min_mtf_alignment_score": 5,
                "adaptive_stop_enabled": True,
                "adaptive_stop_atr_multiplier": 1.1,
                "adaptive_stop_realized_volatility_multiplier": 1.6,
                "adaptive_target_volatility_multiplier": 1.9,
                "early_exit_enabled": True,
                "early_exit_min_seconds": 90,
                "early_exit_min_favorable_r": 0.25,
                "early_exit_max_adverse_r": 0.2,
                "early_exit_min_adverse_votes": 2,
                "early_exit_flow_edge": 0.02,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
        "quant_setup_hf_profit_guarded": base.with_overrides(
            name="quant_setup_hf_profit_guarded",
            strategy_type="quant_setup",
            account_capital_usdt=30.0,
            max_leverage=12.0,
            max_position_notional_usdt=24.0,
            max_risk_per_trade_usdt=0.38,
            max_daily_loss_usdt=0.95,
            max_open_positions=2,
            lookback_bars=6,
            min_quote_volume_usdt=10_000_000.0,
            cooldown_bars=1,
            max_hold_bars=4,
            trailing_stop_enabled=True,
            trailing_activate_r=0.5,
            trailing_lock_r=0.14,
            trailing_giveback_r=0.26,
            setup_profile={
                "name": "hf_profit_guarded",
                "min_edge": 24.0,
                "min_confidence": 0.62,
                "min_risk_reward": 1.18,
                "max_stop_distance_percent": 1.45,
                "min_indicator_sample_size": 5,
                "require_trend_alignment": True,
                "require_rsi_not_extreme": True,
                "min_quote_volume_usdt": 10_000_000.0,
                "min_abs_momentum_percent": 0.35,
                "min_volume_impulse_percent": 1.5,
                "max_volatility_percent": 4.0,
                "max_notional_fraction": 0.7,
                "stop_distance_multiplier": 0.62,
                "target_distance_multiplier": 0.9,
                "require_directional_confluence": True,
                "min_directional_confluence": 5,
                "block_adverse_trend_vwap": True,
                "block_hot_micro_reversal": True,
                "block_volume_fade": True,
                "block_spike_reversal_conflict": True,
                "max_adverse_micro_momentum_percent": 0.05,
                "min_rsi_for_long": 42.0,
                "max_rsi_for_short": 58.0,
                "blocked_setup_reasons": ("crowding_risk",),
            },
        ),
    }


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _ms_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round_optional(value: float | None) -> float | str | None:
    if value is None:
        return None
    if value == float("inf"):
        return "inf"
    return round(value, 8)
