"""Feature extraction for hot-coin candidate scoring."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_UP
from typing import Any, Mapping


@dataclass
class SymbolFeatures:
    symbol: str
    narrative_event_ids: list[int] = field(default_factory=list)
    market_event_ids: list[int] = field(default_factory=list)
    mention_count: int = 0
    sources: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)
    engagement_score: float = 0.0
    latest_narrative_at: str | None = None
    latest_market_at: str | None = None
    price_change_percent: float | None = None
    quote_volume: float | None = None
    open_interest: float | None = None
    open_interest_value: float | None = None
    taker_buy_sell_ratio: float | None = None
    taker_buy_sell_ratio_change: float | None = None
    funding_rate: float | None = None
    kline_range_percent: float | None = None
    kline_range_mean_percent: float | None = None
    kline_range_max_percent: float | None = None
    kline_momentum_percent: float | None = None
    kline_micro_momentum_percent: float | None = None
    kline_close_position_percent: float | None = None
    kline_quote_volume_change_percent: float | None = None
    reference_price: float | None = None
    min_qty: float | None = None
    step_size: float | None = None
    min_notional: float | None = None
    min_executable_notional: float | None = None
    quality_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "narrative_event_ids": list(self.narrative_event_ids),
            "market_event_ids": list(self.market_event_ids),
            "mention_count": self.mention_count,
            "source_count": len(self.sources),
            "author_count": len(self.authors),
            "engagement_score": self.engagement_score,
            "latest_narrative_at": self.latest_narrative_at,
            "latest_market_at": self.latest_market_at,
            "price_change_percent": self.price_change_percent,
            "quote_volume": self.quote_volume,
            "open_interest": self.open_interest,
            "open_interest_value": self.open_interest_value,
            "taker_buy_sell_ratio": self.taker_buy_sell_ratio,
            "taker_buy_sell_ratio_change": self.taker_buy_sell_ratio_change,
            "funding_rate": self.funding_rate,
            "kline_range_percent": self.kline_range_percent,
            "kline_range_mean_percent": self.kline_range_mean_percent,
            "kline_range_max_percent": self.kline_range_max_percent,
            "kline_momentum_percent": self.kline_momentum_percent,
            "kline_micro_momentum_percent": self.kline_micro_momentum_percent,
            "kline_close_position_percent": self.kline_close_position_percent,
            "kline_quote_volume_change_percent": self.kline_quote_volume_change_percent,
            "reference_price": self.reference_price,
            "min_qty": self.min_qty,
            "step_size": self.step_size,
            "min_notional": self.min_notional,
            "min_executable_notional": self.min_executable_notional,
            "quality_notes": list(self.quality_notes),
        }


def extract_features(replay_packet: Mapping[str, Any]) -> dict[str, SymbolFeatures]:
    features: dict[str, SymbolFeatures] = {}
    for record in replay_packet.get("records", []):
        if not isinstance(record, Mapping):
            continue
        event_type = str(record.get("event_type", ""))
        payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
        if event_type == "narrative":
            _apply_narrative(features, record, payload)
        elif event_type == "market_snapshot":
            _apply_market(features, record, payload)
    for item in features.values():
        _set_min_executable_notional(item)
        _add_missing_feature_notes(item)
    return features


def _apply_narrative(
    features: dict[str, SymbolFeatures],
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    symbols = payload.get("symbol_mentions") or ([record.get("symbol")] if record.get("symbol") else [])
    for symbol in [str(symbol).upper() for symbol in symbols if symbol]:
        item = features.setdefault(symbol, SymbolFeatures(symbol=symbol))
        item.mention_count += 1
        item.narrative_event_ids.append(int(record.get("id", 0)))
        if record.get("source"):
            item.sources.add(str(record["source"]))
        if payload.get("author"):
            item.authors.add(str(payload["author"]))
        item.engagement_score += _engagement_score(payload.get("engagement"))
        occurred_at = str(record.get("occurred_at") or payload.get("published_at") or "")
        item.latest_narrative_at = max(filter(None, [item.latest_narrative_at, occurred_at]), default=None)
        for flag in payload.get("quality_flags") or []:
            _note(item, f"narrative:{flag}")


def _apply_market(
    features: dict[str, SymbolFeatures],
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    symbol = str(record.get("symbol") or payload.get("symbol") or "").upper()
    if not symbol:
        return
    item = features.setdefault(symbol, SymbolFeatures(symbol=symbol))
    item.market_event_ids.append(int(record.get("id", 0)))
    item.latest_market_at = max(filter(None, [item.latest_market_at, str(record.get("occurred_at") or "")]), default=None)

    snapshot_payload = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else payload
    snapshot_type = str(payload.get("event_type") or record.get("ref_id") or "")
    if "ticker_24h" in snapshot_type:
        item.price_change_percent = _number(snapshot_payload.get("price_change_percent"))
        item.quote_volume = _number(snapshot_payload.get("quote_volume"))
    elif "open_interest_hist" in snapshot_type:
        item.open_interest_value = _number(snapshot_payload.get("sum_open_interest_value"))
    elif "open_interest" in snapshot_type:
        item.open_interest = _number(snapshot_payload.get("open_interest"))
    elif "taker_buy_sell_volume" in snapshot_type:
        _apply_taker_flow(item, snapshot_payload)
    elif "funding_rate" in snapshot_type:
        item.funding_rate = _number(snapshot_payload.get("funding_rate"))
    elif "kline" in snapshot_type:
        _apply_kline(item, snapshot_payload)
    elif "exchange_symbol" in snapshot_type:
        _apply_execution_filters(item, snapshot_payload)


def _apply_execution_filters(item: SymbolFeatures, payload: Mapping[str, Any]) -> None:
    filters = payload.get("filters")
    if not isinstance(filters, Mapping):
        return
    lot_filter = _mapping(filters.get("MARKET_LOT_SIZE")) or _mapping(filters.get("LOT_SIZE")) or {}
    notional_filter = _mapping(filters.get("MIN_NOTIONAL")) or _mapping(filters.get("NOTIONAL")) or {}
    item.min_qty = _number(lot_filter.get("minQty"))
    item.step_size = _number(lot_filter.get("stepSize"))
    item.min_notional = _number(notional_filter.get("notional") or notional_filter.get("minNotional"))


def _apply_taker_flow(item: SymbolFeatures, payload: Mapping[str, Any]) -> None:
    ratio = _number(payload.get("buy_sell_ratio"))
    if ratio is None:
        return
    previous = item.taker_buy_sell_ratio
    item.taker_buy_sell_ratio = ratio
    if previous is not None:
        item.taker_buy_sell_ratio_change = ratio - previous


def _apply_kline(item: SymbolFeatures, payload: Mapping[str, Any]) -> None:
    open_price = _number(payload.get("open"))
    high = _number(payload.get("high"))
    low = _number(payload.get("low"))
    close = _number(payload.get("close") or payload.get("open"))
    if close is None or close <= 0:
        return

    previous_close = item.reference_price
    previous_quote_volume = getattr(item, "_last_kline_quote_volume", None)
    previous_mean_range = getattr(item, "_kline_range_mean", None)
    previous_count = getattr(item, "_kline_count", 0)
    previous_max_range = getattr(item, "_kline_range_max", 0.0)
    first_open = getattr(item, "_first_kline_open", None)

    if first_open is None and open_price is not None and open_price > 0:
        first_open = open_price
        setattr(item, "_first_kline_open", first_open)

    range_percent = _kline_range(payload)
    if range_percent is not None:
        count = int(previous_count) + 1
        mean = (
            range_percent
            if previous_mean_range is None
            else (float(previous_mean_range) * int(previous_count) + range_percent) / count
        )
        item.kline_range_percent = range_percent
        item.kline_range_mean_percent = mean
        item.kline_range_max_percent = max(float(previous_max_range), range_percent)
        setattr(item, "_kline_count", count)
        setattr(item, "_kline_range_mean", mean)
        setattr(item, "_kline_range_max", item.kline_range_max_percent)

    if first_open is not None and first_open > 0:
        item.kline_momentum_percent = ((close - first_open) / first_open) * 100.0
    if previous_close is not None and previous_close > 0:
        item.kline_micro_momentum_percent = ((close - previous_close) / previous_close) * 100.0
    if high is not None and low is not None and high > low:
        item.kline_close_position_percent = ((close - low) / (high - low)) * 100.0

    quote_volume = _number(payload.get("quote_volume"))
    if quote_volume is not None:
        if previous_quote_volume is not None and previous_quote_volume > 0:
            item.kline_quote_volume_change_percent = ((quote_volume - previous_quote_volume) / previous_quote_volume) * 100.0
        setattr(item, "_last_kline_quote_volume", quote_volume)

    item.reference_price = close


def _set_min_executable_notional(item: SymbolFeatures) -> None:
    price = _decimal_or_none(item.reference_price)
    if price is None:
        return
    min_qty = _decimal_or_zero(item.min_qty)
    min_notional = _decimal_or_zero(item.min_notional)
    step_size = _decimal_or_zero(item.step_size)
    required_qty = min_qty
    if min_notional > 0:
        required_qty = max(required_qty, min_notional / price)
    if required_qty <= 0:
        return
    if step_size > 0:
        required_qty = _round_up(required_qty, step_size)
    item.min_executable_notional = float(required_qty * price)


def _add_missing_feature_notes(item: SymbolFeatures) -> None:
    checks = {
        "missing_narrative": item.mention_count <= 0,
        "missing_market_confirmation": not item.market_event_ids,
        "missing_price_momentum": item.price_change_percent is None,
        "missing_quote_volume": item.quote_volume is None,
        "missing_taker_flow": item.taker_buy_sell_ratio is None,
        "missing_funding": item.funding_rate is None,
        "missing_volatility_proxy": item.kline_range_percent is None,
        "missing_kline_momentum": item.kline_momentum_percent is None,
        "missing_reference_price": item.reference_price is None,
        "missing_min_executable_notional": item.min_executable_notional is None,
    }
    for note, missing in checks.items():
        if missing:
            _note(item, note)


def _engagement_score(value: Any) -> float:
    if not isinstance(value, Mapping):
        return 0.0
    weights = defaultdict(lambda: 1.0, {"likes": 1.0, "comments": 2.0, "shares": 3.0, "views": 0.01})
    total = 0.0
    for key, raw in value.items():
        total += weights[str(key)] * (_number(raw) or 0.0)
    return total


def _kline_range(payload: Mapping[str, Any]) -> float | None:
    high = _number(payload.get("high"))
    low = _number(payload.get("low"))
    close = _number(payload.get("close") or payload.get("open"))
    if high is None or low is None or not close:
        return None
    return ((high - low) / close) * 100


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None or value <= 0:
        return None
    return Decimal(str(value))


def _decimal_or_zero(value: float | None) -> Decimal:
    if value is None or value <= 0:
        return Decimal("0")
    return Decimal(str(value))


def _round_up(value: Decimal, increment: Decimal) -> Decimal:
    units = (value / increment).to_integral_value(rounding=ROUND_UP)
    return units * increment


def _note(item: SymbolFeatures, note: str) -> None:
    if note not in item.quality_notes:
        item.quality_notes.append(note)
