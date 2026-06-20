"""Small dependency-free market indicator helpers for setup generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class KlinePoint:
    open: float
    high: float
    low: float
    close: float
    quote_volume: float | None = None
    taker_buy_sell_ratio: float | None = None


@dataclass(frozen=True)
class IndicatorSnapshot:
    sample_size: int
    reference_price: float | None
    support_price: float | None
    resistance_price: float | None
    vwap: float | None
    atr_percent: float | None
    realized_volatility_percent: float | None
    ema_fast: float | None
    ema_slow: float | None
    ema_spread_percent: float | None
    rsi: float | None
    close_position_percent: float | None
    volume_change_percent: float | None
    momentum_percent: float | None
    micro_momentum_percent: float | None

    def to_features(self) -> dict[str, float | int | None]:
        return {
            "indicator_sample_size": self.sample_size,
            "support_price": self.support_price,
            "resistance_price": self.resistance_price,
            "vwap": self.vwap,
            "atr_percent": self.atr_percent,
            "realized_volatility_percent": self.realized_volatility_percent,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_spread_percent": self.ema_spread_percent,
            "rsi": self.rsi,
            "kline_close_position_percent": self.close_position_percent,
            "kline_quote_volume_change_percent": self.volume_change_percent,
            "kline_momentum_percent": self.momentum_percent,
            "kline_micro_momentum_percent": self.micro_momentum_percent,
            "reference_price": self.reference_price,
        }


def point_from_mapping(payload: Mapping[str, Any]) -> KlinePoint | None:
    high = _positive_float(payload.get("high"))
    low = _positive_float(payload.get("low"))
    close = _positive_float(payload.get("close") or payload.get("open"))
    open_price = _positive_float(payload.get("open")) or close
    if open_price is None or high is None or low is None or close is None:
        return None
    return KlinePoint(
        open=open_price,
        high=high,
        low=low,
        close=close,
        quote_volume=_positive_float(payload.get("quote_volume")),
        taker_buy_sell_ratio=_positive_float(payload.get("taker_buy_sell_ratio")),
    )


def compute_indicator_snapshot(points: Iterable[KlinePoint]) -> IndicatorSnapshot:
    series = list(points)
    if not series:
        return IndicatorSnapshot(
            sample_size=0,
            reference_price=None,
            support_price=None,
            resistance_price=None,
            vwap=None,
            atr_percent=None,
            realized_volatility_percent=None,
            ema_fast=None,
            ema_slow=None,
            ema_spread_percent=None,
            rsi=None,
            close_position_percent=None,
            volume_change_percent=None,
            momentum_percent=None,
            micro_momentum_percent=None,
        )

    closes = [point.close for point in series]
    reference = closes[-1]
    support = min(point.low for point in series)
    resistance = max(point.high for point in series)
    fast_period = min(5, len(closes))
    slow_period = min(12, len(closes))
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)
    ema_spread = _percent_delta(ema_slow, ema_fast) if ema_fast is not None and ema_slow is not None else None

    return IndicatorSnapshot(
        sample_size=len(series),
        reference_price=reference,
        support_price=support,
        resistance_price=resistance,
        vwap=_vwap(series),
        atr_percent=_atr_percent(series),
        realized_volatility_percent=_realized_volatility_percent(closes),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        ema_spread_percent=ema_spread,
        rsi=_rsi(closes),
        close_position_percent=_close_position_percent(series[-1]),
        volume_change_percent=_volume_change_percent(series),
        momentum_percent=_percent_delta(series[0].open, reference),
        micro_momentum_percent=_percent_delta(closes[-2], reference) if len(closes) >= 2 else None,
    )


def _ema(values: list[float], period: int) -> float | None:
    if not values or period <= 0:
        return None
    alpha = 2.0 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = value * alpha + ema * (1.0 - alpha)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < 2:
        return None
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    selected = changes[-period:]
    gains = [max(change, 0.0) for change in selected]
    losses = [abs(min(change, 0.0)) for change in selected]
    avg_gain = sum(gains) / len(selected)
    avg_loss = sum(losses) / len(selected)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_percent(points: list[KlinePoint], period: int = 14) -> float | None:
    if not points:
        return None
    true_ranges: list[float] = []
    previous_close: float | None = None
    for point in points:
        if previous_close is None:
            true_range = point.high - point.low
        else:
            true_range = max(
                point.high - point.low,
                abs(point.high - previous_close),
                abs(point.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = point.close
    selected = true_ranges[-period:]
    reference = points[-1].close
    if reference <= 0:
        return None
    return (sum(selected) / len(selected)) / reference * 100.0


def _realized_volatility_percent(closes: list[float]) -> float | None:
    if len(closes) < 3:
        return None
    returns = [
        _percent_delta(closes[index - 1], closes[index])
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return variance ** 0.5


def _vwap(points: list[KlinePoint]) -> float | None:
    weighted = 0.0
    total_volume = 0.0
    for point in points:
        if point.quote_volume is None or point.quote_volume <= 0:
            continue
        typical = (point.high + point.low + point.close) / 3.0
        weighted += typical * point.quote_volume
        total_volume += point.quote_volume
    if total_volume <= 0:
        return None
    return weighted / total_volume


def _close_position_percent(point: KlinePoint) -> float | None:
    if point.high <= point.low:
        return None
    return ((point.close - point.low) / (point.high - point.low)) * 100.0


def _volume_change_percent(points: list[KlinePoint]) -> float | None:
    volumes = [point.quote_volume for point in points if point.quote_volume is not None and point.quote_volume > 0]
    if len(volumes) < 2:
        return None
    previous = volumes[-2]
    if previous <= 0:
        return None
    return ((volumes[-1] - previous) / previous) * 100.0


def _percent_delta(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return ((end - start) / start) * 100.0


def _positive_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
