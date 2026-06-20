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
