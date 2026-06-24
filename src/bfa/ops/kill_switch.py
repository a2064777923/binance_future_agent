"""Controlled kill-switch clearance after exchange-side protection checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
import time

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient


class KillSwitchSignedClient(Protocol):
    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...

    def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class PositionProtectionCheck:
    symbol: str
    position_side: str
    position_amt: float
    has_stop_loss: bool
    has_take_profit: bool
    matching_algo_order_count: int

    @property
    def protected(self) -> bool:
        return self.has_stop_loss and self.has_take_profit

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_side": self.position_side,
            "position_amt": self.position_amt,
            "has_stop_loss": self.has_stop_loss,
            "has_take_profit": self.has_take_profit,
            "matching_algo_order_count": self.matching_algo_order_count,
            "protected": self.protected,
        }


@dataclass(frozen=True)
class KillSwitchClearanceReport:
    kill_switch_path: str
    kill_switch_active: bool
    eligible: bool
    executed: bool
    reason_codes: list[str] = field(default_factory=list)
    position_checks: list[PositionProtectionCheck] = field(default_factory=list)
    archived_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_kill_switch_clearance_v1",
            "kill_switch_path": self.kill_switch_path,
            "kill_switch_active": self.kill_switch_active,
            "eligible": self.eligible,
            "executed": self.executed,
            "reason_codes": list(self.reason_codes),
            "position_checks": [check.to_dict() for check in self.position_checks],
            "archived_path": self.archived_path,
        }


def build_kill_switch_clearance_report(
    config: AppConfig,
    *,
    signed_client: KillSwitchSignedClient | None = None,
    execute: bool = False,
    now_epoch: float | None = None,
) -> KillSwitchClearanceReport:
    path = Path(config.get("BFA_KILL_SWITCH_FILE"))
    active = path.exists()
    reasons: list[str] = []
    if not active:
        reasons.append("kill_switch_inactive")

    client = signed_client or BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )
    position_checks = _position_protection_checks(client)
    unprotected = [check for check in position_checks if not check.protected]
    if unprotected:
        reasons.append("unprotected_open_positions")
    if active and not unprotected:
        reasons.append("all_open_positions_protected")

    eligible = active and not unprotected
    archived_path = None
    executed = False
    if execute and eligible:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now_epoch or time.time()))
        archived = path.with_name(f"{path.name}.cleared-{stamp}")
        path.replace(archived)
        archived_path = str(archived)
        executed = True
    elif execute and not eligible:
        reasons.append("clearance_not_eligible")

    return KillSwitchClearanceReport(
        kill_switch_path=str(path),
        kill_switch_active=active,
        eligible=eligible,
        executed=executed,
        reason_codes=_dedupe(reasons),
        position_checks=position_checks,
        archived_path=archived_path,
    )


def _position_protection_checks(client: KillSwitchSignedClient) -> list[PositionProtectionCheck]:
    positions = [row for row in client.position_risk() if _float(row.get("positionAmt")) != 0.0]
    algo_orders = client.open_algo_orders()
    checks: list[PositionProtectionCheck] = []
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        amount = _float(position.get("positionAmt"))
        position_side = _position_side(position, amount)
        closing_side = "SELL" if amount > 0 else "BUY"
        matching = [
            order
            for order in algo_orders
            if str(order.get("symbol") or "").upper() == symbol
            and str(order.get("positionSide") or position_side).upper() == position_side
            and str(order.get("side") or "").upper() == closing_side
            and _close_position_order(order)
        ]
        checks.append(
            PositionProtectionCheck(
                symbol=symbol,
                position_side=position_side,
                position_amt=amount,
                has_stop_loss=any(str(order.get("orderType") or "").upper() == "STOP_MARKET" for order in matching),
                has_take_profit=any(
                    str(order.get("orderType") or "").upper() == "TAKE_PROFIT_MARKET" for order in matching
                ),
                matching_algo_order_count=len(matching),
            )
        )
    return checks


def _position_side(position: dict[str, Any], amount: float) -> str:
    raw = str(position.get("positionSide") or "").upper()
    if raw in {"LONG", "SHORT"}:
        return raw
    return "LONG" if amount > 0 else "SHORT"


def _close_position_order(order: dict[str, Any]) -> bool:
    raw = order.get("closePosition")
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
