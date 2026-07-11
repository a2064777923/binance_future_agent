"""Pure second-bar context and pending-limit quality diagnostics."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def second_quality_context(
    items: Sequence[Any],
    *,
    max_rows: int = 90,
) -> dict[str, Any]:
    rows = [_second_context_row(item) for item in items[-max(5, int(max_rows)) :]]
    rows = [row for row in rows if row is not None]
    if len(rows) < 5:
        return {}
    rows.sort(key=lambda row: row["open_time"])
    closes = [row["close"] for row in rows]
    fractions: dict[str, float] = {}
    returns: dict[str, float] = {}
    for window in (5, 15, 30):
        sample = rows[-window:]
        if len(sample) < min(window, 5):
            continue
        first = sample[0]["close"]
        last = sample[-1]["close"]
        returns[str(window)] = round((last - first) / first * 100.0, 8) if first > 0 else 0.0
        quote_volume = sum(row["quote_volume"] for row in sample)
        if quote_volume > 0:
            fractions[str(window)] = round(
                sum(row["taker_buy_quote_volume"] for row in sample) / quote_volume,
                8,
            )
    recent_volume = _mean([row["quote_volume"] for row in rows[-10:]])
    prior_volume = _mean([row["quote_volume"] for row in rows[-30:-10]])
    volume_expansion = (
        recent_volume / prior_volume
        if recent_volume is not None and prior_volume is not None and prior_volume > 0
        else None
    )
    vwap_rows = rows[-30:]
    base_volume = sum(row["volume"] for row in vwap_rows)
    second_vwap = (
        sum(row["close"] * row["volume"] for row in vwap_rows) / base_volume
        if base_volume > 0
        else _mean([row["close"] for row in vwap_rows])
    )
    return {
        "reference_price": closes[-1],
        "second_taker_buy_fractions": fractions,
        "second_returns_percent": returns,
        "second_volume_expansion_ratio": round(volume_expansion, 8)
        if volume_expansion is not None
        else None,
        "second_vwap": round(second_vwap, 8) if second_vwap is not None else None,
        "second_closes": [round(value, 8) for value in closes[-5:]],
        "second_context_sample_count": len(rows),
    }


def second_quality_diagnostics(
    context: Mapping[str, Any],
    *,
    side: str,
    adverse_taker_buy_fraction: float = 0.35,
    price_acceptance_return_percent: float = 0.03,
    adverse_min_windows: int = 2,
    volume_expansion_ratio: float = 1.5,
) -> dict[str, Any]:
    fractions = context.get("second_taker_buy_fractions")
    returns = context.get("second_returns_percent")
    if not isinstance(fractions, Mapping) or not isinstance(returns, Mapping):
        return {"available": False}
    buy = side.upper() == "BUY"
    flow_limit = max(float(adverse_taker_buy_fraction), 0.0)
    return_limit = max(float(price_acceptance_return_percent), 0.0)
    adverse_windows = 0
    absorption_windows = 0
    parsed_returns: list[float] = []
    for window in sorted(set(fractions) & set(returns), key=lambda value: _positive_int(value, 0)):
        fraction = _float_or_none(fractions.get(window))
        window_return = _float_or_none(returns.get(window))
        if fraction is None or window_return is None:
            continue
        parsed_returns.append(window_return)
        flow_adverse = fraction <= flow_limit if buy else fraction >= 1.0 - flow_limit
        return_adverse = window_return <= -return_limit if buy else window_return >= return_limit
        if flow_adverse and return_adverse:
            adverse_windows += 1
        elif return_adverse:
            absorption_windows += 1
    volume_ratio = _float_or_none(context.get("second_volume_expansion_ratio"))
    closes = context.get("second_closes")
    vwap = _float_or_none(context.get("second_vwap"))
    parsed_closes = [
        value
        for value in (_float_or_none(item) for item in closes or [])
        if value is not None and value > 0
    ]
    accepted_by_vwap = False
    if vwap is not None and len(parsed_closes) >= 3:
        tail = parsed_closes[-3:]
        accepted_by_vwap = all(value < vwap for value in tail) if buy else all(value > vwap for value in tail)
    accepted_by_return = any(
        value <= -return_limit if buy else value >= return_limit
        for value in parsed_returns
    )
    min_windows = max(1, int(adverse_min_windows))
    min_volume_ratio = max(float(volume_expansion_ratio), 0.0)
    return {
        "available": True,
        "adverse_flow_window_count": adverse_windows,
        "adverse_flow_persistent": adverse_windows >= min_windows,
        "absorption_window_count": absorption_windows,
        "absorption_persistent": absorption_windows >= min_windows,
        "volume_expansion_ratio": volume_ratio,
        "volume_expanding": volume_ratio is not None and volume_ratio >= min_volume_ratio,
        "price_acceptance": accepted_by_vwap and accepted_by_return,
    }


def _second_context_row(item: Any) -> dict[str, float] | None:
    open_time = _value(item, "open_time")
    close = _positive_float(_value(item, "close"))
    parsed_open_time = _int_or_none(open_time)
    if parsed_open_time is None or close is None:
        return None
    return {
        "open_time": float(parsed_open_time),
        "close": close,
        "volume": max(_float_or_default(_value(item, "volume"), 0.0), 0.0),
        "quote_volume": max(_float_or_default(_value(item, "quote_volume"), 0.0), 0.0),
        "taker_buy_quote_volume": max(
            _float_or_default(_value(item, "taker_buy_quote_volume"), 0.0),
            0.0,
        ),
    }


def _value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _positive_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, default: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else default
