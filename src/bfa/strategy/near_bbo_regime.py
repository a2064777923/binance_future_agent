"""Incremental 1m context for public near-BBO scalping research.

Five/15-minute indicators are used as a regime filter, never as a promise that
the next tick will reverse. Trade ingestion is O(1) on the normal ordered path;
classification scans only the small bounded minute deque.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

from bfa.strategy.regime import CHOP, RANGE, TREND, classify_regime


BREAKOUT = "BREAKOUT"
WARMUP = "WARMUP"


@dataclass(frozen=True)
class NearBboRegimeConfig:
    history_minutes: int = 16
    min_bars: int = 15
    fast_ema_span: int = 5
    slow_ema_span: int = 15
    breakout_min_move_percent: float = 0.25
    breakout_min_strength: float = 4.0

    def __post_init__(self) -> None:
        if self.history_minutes < 3:
            raise ValueError("history_minutes must be at least three")
        if not 3 <= self.min_bars <= self.history_minutes:
            raise ValueError("min_bars must be between three and history_minutes")
        if not 2 <= self.fast_ema_span <= self.slow_ema_span:
            raise ValueError("EMA spans must satisfy 2 <= fast <= slow")
        if self.slow_ema_span > self.history_minutes:
            raise ValueError("slow_ema_span cannot exceed history_minutes")
        if self.min_bars < self.slow_ema_span:
            raise ValueError("min_bars cannot be below slow_ema_span")
        if self.breakout_min_move_percent <= 0 or self.breakout_min_strength <= 0:
            raise ValueError("breakout controls must be positive")


@dataclass
class _MinuteBar:
    open_time_ms: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    quote_volume: float = 0.0
    taker_buy_quote: float = 0.0
    trade_count: int = 0

    def update(self, *, price: float, quantity: float, taker_buy: bool) -> None:
        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        self.close_price = price
        quote = price * quantity
        self.quote_volume += quote
        if taker_buy:
            self.taker_buy_quote += quote
        self.trade_count += 1

    def update_summary(
        self,
        *,
        last_price: float,
        high_price: float,
        low_price: float,
        quote_volume: float,
        taker_buy_quote: float,
        trade_count: int,
    ) -> None:
        """Merge an ordered aggregate without replaying every raw trade.

        The live path still uses :meth:`update` for individual events.  Historical
        replay can safely use this method because regime features only consume
        minute OHLC, quote volume, taker-buy volume, and event count.
        """

        if trade_count <= 0:
            return
        self.high_price = max(self.high_price, high_price)
        self.low_price = min(self.low_price, low_price)
        self.close_price = last_price
        self.quote_volume += max(0.0, quote_volume)
        self.taker_buy_quote += max(0.0, min(taker_buy_quote, quote_volume))
        self.trade_count += int(trade_count)


@dataclass(frozen=True)
class NearBboRegimeSnapshot:
    label: str
    direction: str | None
    confidence: float
    bar_count: int
    fast_ema: float
    slow_ema: float
    ema_spread_percent: float
    momentum_percent: float
    micro_momentum_percent: float
    realized_volatility_percent: float
    path_efficiency: float
    edge_alternation_count: int
    drift_to_width: float
    range_width_percent: float
    range_position: float
    breakout_strength: float
    feature_payload: dict[str, float | int | str]


class NearBboRegimeTracker:
    """Aggregate public trades into a bounded minute context."""

    def __init__(self, config: NearBboRegimeConfig | None = None) -> None:
        self.config = config or NearBboRegimeConfig()
        self._bars: deque[_MinuteBar] = deque(maxlen=self.config.history_minutes)

    @property
    def bar_count(self) -> int:
        return len(self._bars)

    def ingest_trade(
        self,
        *,
        event_time_ms: int,
        price: float,
        quantity: float,
        taker_buy: bool,
    ) -> bool:
        if event_time_ms < 0 or price <= 0 or quantity <= 0:
            return False
        minute_ms = event_time_ms // 60_000 * 60_000
        bar = self._bar_for_minute(minute_ms, float(price))
        bar.update(price=float(price), quantity=float(quantity), taker_buy=bool(taker_buy))
        return True

    def ingest_trade_summary(
        self,
        *,
        event_time_ms: int,
        first_price: float,
        last_price: float,
        high_price: float,
        low_price: float,
        quote_volume: float,
        taker_buy_quote: float,
        trade_count: int,
    ) -> bool:
        """Ingest one ordered second/minute aggregate in O(1).

        This is intentionally a separate API for deterministic historical
        replay.  It preserves the fields consumed by the regime classifier while
        avoiding one Python call per aggTrade.  The normal live collector should
        continue using :meth:`ingest_trade`.
        """

        if event_time_ms < 0 or min(first_price, last_price, high_price, low_price) <= 0:
            return False
        if high_price < max(first_price, last_price) or low_price > min(first_price, last_price):
            return False
        if quote_volume <= 0 or taker_buy_quote < 0 or trade_count <= 0:
            return False
        minute_ms = event_time_ms // 60_000 * 60_000
        bar = self._bar_for_minute(minute_ms, float(first_price))
        bar.update_summary(
            last_price=float(last_price),
            high_price=float(high_price),
            low_price=float(low_price),
            quote_volume=float(quote_volume),
            taker_buy_quote=float(taker_buy_quote),
            trade_count=int(trade_count),
        )
        return True

    def snapshot(self, *, now_ms: int) -> NearBboRegimeSnapshot:
        bars = [bar for bar in self._bars if bar.open_time_ms <= now_ms]
        if len(bars) < self.config.min_bars:
            return self._warmup_snapshot(len(bars))

        closes = [bar.close_price for bar in bars]
        mean_price = sum(closes) / len(closes)
        high_price = max(bar.high_price for bar in bars)
        low_price = min(bar.low_price for bar in bars)
        width = max(high_price - low_price, 0.0)
        range_width_percent = width / mean_price * 100.0 if mean_price > 0 else 0.0
        range_position = (closes[-1] - low_price) / width if width > 0 else 0.5
        moves = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
        path_length = sum(abs(value) for value in moves)
        path_efficiency = abs(closes[-1] - closes[0]) / path_length if path_length > 0 else 0.0
        drift_to_width = abs(closes[-1] - closes[0]) / width if width > 0 else 0.0
        edge_alternations = _edge_alternations(closes, low_price=low_price, width=width)
        fast_ema = _ema(closes, self.config.fast_ema_span)
        slow_ema = _ema(closes, self.config.slow_ema_span)
        ema_spread_percent = (fast_ema - slow_ema) / slow_ema * 100.0 if slow_ema > 0 else 0.0
        momentum_percent = _percent_change(closes[0], closes[-1])
        micro_start = closes[max(0, len(closes) - min(3, self.config.fast_ema_span))]
        micro_momentum_percent = _percent_change(micro_start, closes[-1])
        returns = [_percent_change(closes[index - 1], closes[index]) for index in range(1, len(closes))]
        realized_volatility = math.sqrt(sum(value * value for value in returns) / len(returns)) if returns else 0.0
        last_return = returns[-1] if returns else 0.0
        baseline = returns[:-1]
        baseline_rms = (
            math.sqrt(sum(value * value for value in baseline) / len(baseline))
            if baseline
            else 0.0
        )
        breakout_strength = abs(last_return) / max(baseline_rms, 1e-6)
        volume_change = _recent_volume_change_percent(bars)
        range_max_percent = max(
            (bar.high_price - bar.low_price) / bar.close_price * 100.0
            if bar.close_price > 0
            else 0.0
            for bar in bars
        )
        payload: dict[str, float | int | str] = {
            "range_path_efficiency": path_efficiency,
            "range_edge_alternation_count": edge_alternations,
            "range_width_percent": range_width_percent,
            "range_stable_width_percent": range_width_percent,
            "range_drift_to_width": drift_to_width,
            "ema_spread_percent": ema_spread_percent,
            "kline_momentum_percent": momentum_percent,
            "kline_micro_momentum_percent": micro_momentum_percent,
            "realized_volatility_percent": realized_volatility,
            "kline_close_position_percent": range_position * 100.0,
            "kline_quote_volume_change_percent": volume_change,
            "kline_range_max_percent": range_max_percent,
        }

        direction = _direction(ema_spread_percent, momentum_percent)
        breakout = (
            abs(last_return) >= self.config.breakout_min_move_percent
            and breakout_strength >= self.config.breakout_min_strength
        )
        if breakout:
            label = BREAKOUT
            confidence = min(0.99, 0.70 + min(breakout_strength / 20.0, 0.29))
            direction = "long" if last_return > 0 else "short"
        else:
            decision = classify_regime(payload, strategy_leg="trend", shadow_only=True)
            label = decision.label
            confidence = decision.confidence
            if label != TREND:
                direction = None
        payload.update(
            {
                "near_bbo_regime": label,
                "near_bbo_regime_direction": direction or "none",
                "near_bbo_regime_confidence": confidence,
                "near_bbo_range_position": range_position,
                "near_bbo_breakout_strength": breakout_strength,
            }
        )
        return NearBboRegimeSnapshot(
            label=label,
            direction=direction,
            confidence=round(confidence, 6),
            bar_count=len(bars),
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            ema_spread_percent=ema_spread_percent,
            momentum_percent=momentum_percent,
            micro_momentum_percent=micro_momentum_percent,
            realized_volatility_percent=realized_volatility,
            path_efficiency=path_efficiency,
            edge_alternation_count=edge_alternations,
            drift_to_width=drift_to_width,
            range_width_percent=range_width_percent,
            range_position=max(0.0, min(1.0, range_position)),
            breakout_strength=breakout_strength,
            feature_payload=payload,
        )

    def _bar_for_minute(self, minute_ms: int, price: float) -> _MinuteBar:
        if self._bars and self._bars[-1].open_time_ms == minute_ms:
            return self._bars[-1]
        if not self._bars or self._bars[-1].open_time_ms < minute_ms:
            bar = _MinuteBar(minute_ms, price, price, price, price)
            self._bars.append(bar)
            return bar
        for bar in reversed(self._bars):
            if bar.open_time_ms == minute_ms:
                return bar
            if bar.open_time_ms < minute_ms:
                break
        # Late events older than retained context are irrelevant; do not grow
        # or reorder the hot-path deque for them.
        return _DetachedMinuteBar(minute_ms, price, price, price, price)

    @staticmethod
    def _warmup_snapshot(bar_count: int) -> NearBboRegimeSnapshot:
        return NearBboRegimeSnapshot(
            label=WARMUP,
            direction=None,
            confidence=0.0,
            bar_count=bar_count,
            fast_ema=0.0,
            slow_ema=0.0,
            ema_spread_percent=0.0,
            momentum_percent=0.0,
            micro_momentum_percent=0.0,
            realized_volatility_percent=0.0,
            path_efficiency=0.0,
            edge_alternation_count=0,
            drift_to_width=0.0,
            range_width_percent=0.0,
            range_position=0.5,
            breakout_strength=0.0,
            feature_payload={"near_bbo_regime": WARMUP, "near_bbo_regime_bar_count": bar_count},
        )


class _DetachedMinuteBar(_MinuteBar):
    """Discard updates for late events outside retained minute context."""


def _ema(values: list[float], span: int) -> float:
    selected = values[-max(1, int(span)) :]
    alpha = 2.0 / (max(1, int(span)) + 1.0)
    result = selected[0]
    for value in selected[1:]:
        result += alpha * (value - result)
    return result


def _edge_alternations(closes: list[float], *, low_price: float, width: float) -> int:
    if width <= 0:
        return 0
    last_zone: str | None = None
    count = 0
    for close in closes:
        position = (close - low_price) / width
        zone = "low" if position <= 0.30 else "high" if position >= 0.70 else None
        if zone is None:
            continue
        if last_zone is not None and zone != last_zone:
            count += 1
        last_zone = zone
    return count


def _recent_volume_change_percent(bars: list[_MinuteBar]) -> float:
    if len(bars) < 6:
        return 0.0
    recent = sum(bar.quote_volume for bar in bars[-3:]) / 3.0
    previous = sum(bar.quote_volume for bar in bars[-6:-3]) / 3.0
    return (recent - previous) / previous * 100.0 if previous > 0 else 0.0


def _percent_change(start: float, end: float) -> float:
    return (end - start) / start * 100.0 if start > 0 else 0.0


def _direction(ema_spread_percent: float, momentum_percent: float) -> str | None:
    value = ema_spread_percent if abs(ema_spread_percent) > 1e-9 else momentum_percent
    if value > 0:
        return "long"
    if value < 0:
        return "short"
    return None


__all__ = [
    "BREAKOUT",
    "CHOP",
    "RANGE",
    "TREND",
    "WARMUP",
    "NearBboRegimeConfig",
    "NearBboRegimeSnapshot",
    "NearBboRegimeTracker",
]
