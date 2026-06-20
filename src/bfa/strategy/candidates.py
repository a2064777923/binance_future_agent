"""Deterministic hot-coin candidate scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.strategy.features import SymbolFeatures, extract_features


@dataclass(frozen=True)
class StrategyConfig:
    allowed_symbols: list[str]
    generated_at: str
    top_n: int = 5
    min_quote_volume: float = 1_000_000.0
    max_kline_range_percent: float = 20.0
    require_market_confirmation: bool = True
    max_position_notional_usdt: float | None = None
    paper_guard: Any | None = None


@dataclass(frozen=True)
class CandidateSignal:
    symbol: str
    score: float
    narrative_score: float
    market_score: float
    reason_codes: list[str]
    data_quality_notes: list[str]
    source_event_ids: list[int]
    market_event_ids: list[int]
    generated_at: str
    features: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "narrative_score": self.narrative_score,
            "market_score": self.market_score,
            "reason_codes": list(self.reason_codes),
            "data_quality_notes": list(self.data_quality_notes),
            "source_event_ids": list(self.source_event_ids),
            "market_event_ids": list(self.market_event_ids),
            "generated_at": self.generated_at,
            "features": dict(self.features),
        }


@dataclass(frozen=True)
class RejectedCandidate:
    symbol: str
    reason_codes: list[str]
    data_quality_notes: list[str]
    features: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reason_codes": list(self.reason_codes),
            "data_quality_notes": list(self.data_quality_notes),
            "features": dict(self.features),
        }


@dataclass(frozen=True)
class CandidateGenerationResult:
    candidates: list[CandidateSignal]
    rejected: list[RejectedCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "rejected": [rejected.to_dict() for rejected in self.rejected],
        }


def generate_candidates(
    replay_packet: Mapping[str, Any],
    config: StrategyConfig,
) -> CandidateGenerationResult:
    features = extract_features(replay_packet)
    allowed = {symbol.upper() for symbol in config.allowed_symbols}
    candidates: list[CandidateSignal] = []
    rejected: list[RejectedCandidate] = []

    for symbol in sorted(features):
        item = features[symbol]
        reject_reasons = _reject_reasons(item, allowed, config)
        if reject_reasons:
            rejected.append(
                RejectedCandidate(
                    symbol=symbol,
                    reason_codes=reject_reasons,
                    data_quality_notes=list(item.quality_notes),
                    features=item.to_dict(),
                )
            )
            continue
        candidates.append(_score_candidate(item, config))

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.symbol))
    return CandidateGenerationResult(
        candidates=candidates[: config.top_n],
        rejected=rejected,
    )


def _reject_reasons(
    item: SymbolFeatures,
    allowed_symbols: set[str],
    config: StrategyConfig,
) -> list[str]:
    reasons: list[str] = []
    if item.symbol not in allowed_symbols:
        reasons.append("symbol_not_allowed")
    if item.mention_count <= 0:
        reasons.append("no_narrative_evidence")
    if config.require_market_confirmation and not item.market_event_ids:
        reasons.append("missing_market_confirmation")
    if (item.quote_volume or 0.0) < config.min_quote_volume:
        reasons.append("insufficient_liquidity")
    if item.kline_range_percent is not None and item.kline_range_percent > config.max_kline_range_percent:
        reasons.append("excessive_volatility")
    if (
        config.max_position_notional_usdt is not None
        and item.min_executable_notional is not None
        and item.min_executable_notional > config.max_position_notional_usdt
    ):
        reasons.append("min_executable_notional_exceeds_cap")
    if config.paper_guard is not None and config.paper_guard.blocks_symbol(item.symbol):
        reasons.extend(config.paper_guard.symbol_reasons(item.symbol))
    return reasons


def _score_candidate(item: SymbolFeatures, config: StrategyConfig) -> CandidateSignal:
    narrative_score = (
        item.mention_count * 12.0
        + len(item.sources) * 8.0
        + len(item.authors) * 4.0
        + min(item.engagement_score / 10.0, 20.0)
    )
    market_score = 0.0
    reason_codes: list[str] = []
    if item.price_change_percent is not None:
        market_score += max(min(item.price_change_percent, 20.0), -10.0) * 2.0
        if item.price_change_percent > 3:
            reason_codes.append("price_momentum")
    if item.quote_volume is not None:
        market_score += min(item.quote_volume / 1_000_000.0, 20.0)
        if item.quote_volume >= config.min_quote_volume:
            reason_codes.append("liquidity_ok")
    if item.open_interest_value is not None:
        market_score += min(item.open_interest_value / 1_000_000.0, 15.0)
        reason_codes.append("open_interest_value")
    elif item.open_interest is not None:
        market_score += min(item.open_interest / 100_000.0, 10.0)
        reason_codes.append("open_interest")
    if item.taker_buy_sell_ratio is not None:
        market_score += max(min((item.taker_buy_sell_ratio - 1.0) * 10.0, 10.0), -5.0)
        if item.taker_buy_sell_ratio > 1.05:
            reason_codes.append("taker_buy_bias")
    if item.funding_rate is not None:
        market_score += max(2.0 - abs(item.funding_rate) * 1000.0, -5.0)
        reason_codes.append("funding_observed")
    if item.kline_range_percent is not None:
        market_score += max(5.0 - item.kline_range_percent / 5.0, -5.0)
        reason_codes.append("volatility_checked")
    if (
        config.max_position_notional_usdt is not None
        and item.min_executable_notional is not None
        and item.min_executable_notional <= config.max_position_notional_usdt
    ):
        reason_codes.append("pilot_tradable")

    if item.mention_count > 0:
        reason_codes.append("narrative_heat")
    if len(item.sources) > 1:
        reason_codes.append("source_diversity")

    quality_penalty = len(item.quality_notes) * 2.0
    total_score = round(max(narrative_score + market_score - quality_penalty, 0.0), 4)
    return CandidateSignal(
        symbol=item.symbol,
        score=total_score,
        narrative_score=round(narrative_score, 4),
        market_score=round(market_score, 4),
        reason_codes=_dedupe(reason_codes),
        data_quality_notes=list(item.quality_notes),
        source_event_ids=list(item.narrative_event_ids),
        market_event_ids=list(item.market_event_ids),
        generated_at=config.generated_at,
        features=item.to_dict(),
    )


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
