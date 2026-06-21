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

    @property
    def estimated_initial_margin_usdt(self) -> float:
        if self.leverage <= 0:
            return self.notional_usdt
        return self.notional_usdt / self.leverage

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "notional_usdt": self.notional_usdt,
            "estimated_initial_margin_usdt": self.estimated_initial_margin_usdt,
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
    active_exposures: list[dict[str, Any]] = field(default_factory=list)
    manual_exposures: list[dict[str, Any]] = field(default_factory=list)
    account_available_balance_usdt: float | None = None
    account_total_wallet_balance_usdt: float | None = None
    daily_realized_pnl_usdt: float = 0.0
    cooldown_until: str | None = None

    @property
    def daily_loss_usdt(self) -> float:
        return abs(min(self.daily_realized_pnl_usdt, 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_positions": self.active_positions,
            "active_exposures": [dict(item) for item in self.active_exposures],
            "manual_exposures": [dict(item) for item in self.manual_exposures],
            "active_notional_usdt": self.active_notional_usdt,
            "active_initial_margin_usdt": self.active_initial_margin_usdt,
            "manual_initial_margin_usdt": self.manual_initial_margin_usdt,
            "total_initial_margin_usdt": self.total_initial_margin_usdt,
            "account_available_balance_usdt": self.account_available_balance_usdt,
            "account_total_wallet_balance_usdt": self.account_total_wallet_balance_usdt,
            "daily_realized_pnl_usdt": self.daily_realized_pnl_usdt,
            "daily_loss_usdt": self.daily_loss_usdt,
            "cooldown_until": self.cooldown_until,
        }

    @property
    def active_notional_usdt(self) -> float:
        return sum(_float_or_zero(item.get("notional_usdt")) for item in self.active_exposures)

    @property
    def active_initial_margin_usdt(self) -> float:
        return sum(_exposure_margin(item) for item in self.active_exposures)

    @property
    def manual_initial_margin_usdt(self) -> float:
        return sum(_exposure_margin(item) for item in self.manual_exposures)

    @property
    def total_initial_margin_usdt(self) -> float:
        return self.active_initial_margin_usdt + self.manual_initial_margin_usdt


def _exposure_margin(item: dict[str, Any]) -> float:
    margin = _float_or_none(item.get("initial_margin_usdt"))
    if margin is not None:
        return margin
    notional = _float_or_zero(item.get("notional_usdt"))
    leverage = _float_or_zero(item.get("leverage"))
    if leverage <= 0:
        return 0.0
    return notional / leverage


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


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
