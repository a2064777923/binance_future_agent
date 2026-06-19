"""Execution result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    notional_usdt: float
    entry_price: float
    stop_price: float
    target_price: float
    leverage: int
    mode: str
    decided_at: str
    order_type: str = "MARKET"
    reduce_only: bool = False
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "notional_usdt": self.notional_usdt,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "leverage": self.leverage,
            "mode": self.mode,
            "decided_at": self.decided_at,
            "order_type": self.order_type,
            "reduce_only": self.reduce_only,
            "reason_codes": list(self.reason_codes),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RiskState:
    active_positions: int = 0
    daily_realized_pnl_usdt: float = 0.0
    cooldown_until: str | None = None

    @property
    def daily_loss_usdt(self) -> float:
        return abs(min(self.daily_realized_pnl_usdt, 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_positions": self.active_positions,
            "daily_realized_pnl_usdt": self.daily_realized_pnl_usdt,
            "daily_loss_usdt": self.daily_loss_usdt,
            "cooldown_until": self.cooldown_until,
        }


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason_codes: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    submitted: bool
    intent: OrderIntent | None
    risk: RiskDecision
    exchange_response: dict[str, Any] | None = None
    persisted: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "submitted": self.submitted,
            "intent": self.intent.to_dict() if self.intent is not None else None,
            "risk": self.risk.to_dict(),
            "exchange_response": dict(self.exchange_response) if self.exchange_response else None,
            "persisted": dict(self.persisted),
        }
