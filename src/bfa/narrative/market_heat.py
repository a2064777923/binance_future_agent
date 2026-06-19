"""Market-derived fallback narrative records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from bfa.market.models import NormalizedMarketSnapshot
from bfa.narrative.models import NormalizedNarrativeRecord


@dataclass
class _HeatMetrics:
    symbol: str
    price_change_percent: float | None = None
    quote_volume: float | None = None
    open_interest: float | None = None
    open_interest_value: float | None = None
    taker_buy_sell_ratio: float | None = None
    funding_rate: float | None = None
    kline_range_percent: float | None = None


@dataclass(frozen=True)
class _HeatCandidate:
    metrics: _HeatMetrics
    score: float
    reasons: list[str]


class MarketHeatNarrativeCollector:
    """Translate strong public-market evidence into explicit fallback narratives."""

    def __init__(
        self,
        snapshots: Iterable[NormalizedMarketSnapshot],
        *,
        known_symbols: Iterable[str],
        collected_at: str,
        min_quote_volume: float,
        min_price_change_percent: float,
        min_taker_buy_sell_ratio: float,
        min_open_interest_value: float,
        max_kline_range_percent: float,
        max_records: int,
    ) -> None:
        self.snapshots = list(snapshots)
        self.known_symbols = {symbol.upper() for symbol in known_symbols}
        self.collected_at = collected_at
        self.min_quote_volume = min_quote_volume
        self.min_price_change_percent = min_price_change_percent
        self.min_taker_buy_sell_ratio = min_taker_buy_sell_ratio
        self.min_open_interest_value = min_open_interest_value
        self.max_kline_range_percent = max_kline_range_percent
        self.max_records = max_records

    def collect(self) -> list[NormalizedNarrativeRecord]:
        metrics = self._metrics_by_symbol()
        candidates = [
            candidate
            for item in metrics.values()
            if (candidate := self._candidate_from_metrics(item)) is not None
        ]
        candidates.sort(key=lambda item: (-item.score, item.metrics.symbol))
        return [self._record(candidate) for candidate in candidates[: self.max_records]]

    def _metrics_by_symbol(self) -> dict[str, _HeatMetrics]:
        by_symbol: dict[str, _HeatMetrics] = {}
        for snapshot in self.snapshots:
            symbol = snapshot.symbol.upper()
            if self.known_symbols and symbol not in self.known_symbols:
                continue
            item = by_symbol.setdefault(symbol, _HeatMetrics(symbol=symbol))
            payload = snapshot.payload
            if snapshot.event_type == "ticker_24h":
                item.price_change_percent = _number(payload.get("price_change_percent"))
                item.quote_volume = _number(payload.get("quote_volume"))
            elif snapshot.event_type == "kline":
                item.kline_range_percent = _kline_range(payload)
            elif snapshot.event_type == "funding_rate":
                item.funding_rate = _number(payload.get("funding_rate"))
            elif snapshot.event_type == "open_interest":
                item.open_interest = _number(payload.get("open_interest"))
            elif snapshot.event_type == "open_interest_hist":
                item.open_interest_value = _number(payload.get("sum_open_interest_value"))
            elif snapshot.event_type == "taker_buy_sell_volume":
                item.taker_buy_sell_ratio = _number(payload.get("buy_sell_ratio"))
        return by_symbol

    def _candidate_from_metrics(self, item: _HeatMetrics) -> _HeatCandidate | None:
        if (item.quote_volume or 0.0) < self.min_quote_volume:
            return None
        if item.price_change_percent is None or item.price_change_percent < self.min_price_change_percent:
            return None
        if item.kline_range_percent is None or item.kline_range_percent > self.max_kline_range_percent:
            return None

        reasons = ["liquidity_ok", "positive_price_change", "volatility_checked"]
        confirmation_score = 0.0
        if item.taker_buy_sell_ratio is not None and item.taker_buy_sell_ratio >= self.min_taker_buy_sell_ratio:
            reasons.append("taker_buy_bias")
            confirmation_score += min((item.taker_buy_sell_ratio - 1.0) * 10.0, 10.0)
        if item.open_interest_value is not None and item.open_interest_value >= self.min_open_interest_value:
            reasons.append("open_interest_value")
            confirmation_score += min(item.open_interest_value / 1_000_000.0, 15.0)
        elif item.open_interest is not None:
            reasons.append("open_interest")
            confirmation_score += min(item.open_interest / 100_000.0, 10.0)
        if confirmation_score <= 0.0:
            return None
        if item.funding_rate is not None:
            reasons.append("funding_observed")

        score = round(
            min(item.quote_volume / 1_000_000.0, 20.0)
            + min(item.price_change_percent * 2.0, 40.0)
            + confirmation_score
            + max(5.0 - item.kline_range_percent / 5.0, 0.0),
            4,
        )
        return _HeatCandidate(metrics=item, score=score, reasons=reasons)

    def _record(self, candidate: _HeatCandidate) -> NormalizedNarrativeRecord:
        metrics = candidate.metrics
        text = (
            f"{metrics.symbol} market heat from Binance USD-M public metrics: "
            f"24h price change {_fmt(metrics.price_change_percent)}%, "
            f"quote volume {_fmt(metrics.quote_volume)} USDT, "
            f"taker buy/sell ratio {_fmt(metrics.taker_buy_sell_ratio)}, "
            f"open interest value {_fmt(metrics.open_interest_value)} USDT, "
            f"funding rate {_fmt(metrics.funding_rate)}, "
            f"5m range {_fmt(metrics.kline_range_percent)}%."
        )
        return NormalizedNarrativeRecord(
            source="market_heat",
            source_id=f"market_heat:{metrics.symbol}:{self.collected_at}",
            author="binance_usdm_metrics",
            symbol_mentions=[metrics.symbol],
            text=text,
            url=None,
            published_at=self.collected_at,
            collected_at=self.collected_at,
            engagement={"heat_score": candidate.score},
            raw={
                "metrics": _metrics_payload(metrics),
                "reason_codes": list(candidate.reasons),
                "thresholds": {
                    "min_quote_volume": self.min_quote_volume,
                    "min_price_change_percent": self.min_price_change_percent,
                    "min_taker_buy_sell_ratio": self.min_taker_buy_sell_ratio,
                    "min_open_interest_value": self.min_open_interest_value,
                    "max_kline_range_percent": self.max_kline_range_percent,
                },
            },
            quality_flags=["market_derived"],
        )


def _metrics_payload(metrics: _HeatMetrics) -> dict[str, float | str | None]:
    return {
        "symbol": metrics.symbol,
        "price_change_percent": metrics.price_change_percent,
        "quote_volume": metrics.quote_volume,
        "open_interest": metrics.open_interest,
        "open_interest_value": metrics.open_interest_value,
        "taker_buy_sell_ratio": metrics.taker_buy_sell_ratio,
        "funding_rate": metrics.funding_rate,
        "kline_range_percent": metrics.kline_range_percent,
    }


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _kline_range(payload: Mapping[str, Any]) -> float | None:
    high = _number(payload.get("high"))
    low = _number(payload.get("low"))
    close = _number(payload.get("close") or payload.get("open"))
    if high is None or low is None or not close:
        return None
    return ((high - low) / close) * 100


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6g}"
