"""Schemas and context packets for OpenAI trade decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.config import AppConfig


DECISION_SCHEMA_FIELDS = (
    "decision",
    "side",
    "confidence",
    "entry_price",
    "stop_price",
    "target_price",
    "notional_usdt",
    "hold_time_minutes",
    "reasons",
)


@dataclass(frozen=True)
class RiskLimits:
    account_capital_usdt: float
    max_leverage: float
    max_position_notional_usdt: float
    max_risk_per_trade_usdt: float
    max_daily_loss_usdt: float
    max_open_positions: int

    @classmethod
    def from_config(cls, config: AppConfig) -> "RiskLimits":
        return cls(
            account_capital_usdt=float(config.get("BFA_ACCOUNT_CAPITAL_USDT")),
            max_leverage=float(config.get("BFA_MAX_LEVERAGE")),
            max_position_notional_usdt=float(config.get("BFA_MAX_POSITION_NOTIONAL_USDT")),
            max_risk_per_trade_usdt=float(config.get("BFA_MAX_RISK_PER_TRADE_USDT")),
            max_daily_loss_usdt=float(config.get("BFA_MAX_DAILY_LOSS_USDT")),
            max_open_positions=int(config.get("BFA_MAX_OPEN_POSITIONS")),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "account_capital_usdt": self.account_capital_usdt,
            "max_leverage": self.max_leverage,
            "max_position_notional_usdt": self.max_position_notional_usdt,
            "max_position_margin_usdt": round(self.max_position_notional_usdt / self.max_leverage, 8),
            "max_risk_per_trade_usdt": self.max_risk_per_trade_usdt,
            "max_daily_loss_usdt": self.max_daily_loss_usdt,
            "max_open_positions": self.max_open_positions,
        }


@dataclass(frozen=True)
class AiDecisionContext:
    candidate: dict[str, Any]
    risk_limits: RiskLimits
    decided_at: str
    prompt_version: str = "bfa-ai-decision-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_version": self.prompt_version,
            "decided_at": self.decided_at,
            "candidate": dict(self.candidate),
            "risk_limits": self.risk_limits.to_dict(),
        }


@dataclass(frozen=True)
class AiTradeDecision:
    decision: str
    side: str
    confidence: float
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    notional_usdt: float | None
    hold_time_minutes: int | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "side": self.side,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "notional_usdt": self.notional_usdt,
            "hold_time_minutes": self.hold_time_minutes,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DecisionValidationResult:
    accepted: bool
    decision: AiTradeDecision | None
    validation_errors: list[str]
    validation_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "decision": self.decision.to_dict() if self.decision is not None else None,
            "validation_errors": list(self.validation_errors),
            "validation_warnings": list(self.validation_warnings),
        }


def context_from_candidate(
    candidate: Mapping[str, Any] | Any,
    *,
    risk_limits: RiskLimits,
    decided_at: str,
) -> AiDecisionContext:
    """Build a compact, reproducible context packet from a candidate payload."""

    candidate_payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
    return AiDecisionContext(
        candidate=_compact_candidate(candidate_payload),
        risk_limits=risk_limits,
        decided_at=decided_at,
    )


def decision_json_schema() -> dict[str, Any]:
    """Return the Responses API JSON schema format for a trade decision."""

    return {
        "type": "json_schema",
        "name": "bfa_trade_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string", "enum": ["trade", "pass"]},
                "side": {"type": "string", "enum": ["long", "short", "flat"]},
                "confidence": {"type": "number"},
                "entry_price": {"type": ["number", "null"]},
                "stop_price": {"type": ["number", "null"]},
                "target_price": {"type": ["number", "null"]},
                "notional_usdt": {"type": ["number", "null"]},
                "hold_time_minutes": {"type": ["integer", "null"]},
                "reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": list(DECISION_SCHEMA_FIELDS),
        },
    }


def _compact_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "symbol",
        "score",
        "narrative_score",
        "market_score",
        "reason_codes",
        "data_quality_notes",
        "source_event_ids",
        "market_event_ids",
        "generated_at",
        "features",
    )
    compact = {key: candidate[key] for key in allowed_keys if key in candidate}
    features = compact.get("features")
    if isinstance(features, Mapping):
        compact["features"] = {
            key: features[key]
            for key in (
                "mention_count",
                "source_count",
                "author_count",
                "engagement_score",
                "latest_narrative_at",
                "latest_market_at",
                "price_change_percent",
                "quote_volume",
                "open_interest",
                "open_interest_value",
                "taker_buy_sell_ratio",
                "funding_rate",
                "kline_range_percent",
                "reference_price",
                "quality_notes",
            )
            if key in features
        }
    return compact
