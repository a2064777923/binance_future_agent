"""Append-only manual loss incident intake."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from bfa.config import AppConfig
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore


VALID_SIDES = {"long", "short"}
VALID_STOP_LOSS_STATUSES = {"unknown", "none", "configured", "hit", "missed"}


@dataclass(frozen=True)
class ManualLossIncident:
    symbol: str
    side: str
    leverage: float
    entry_price: float
    occurred_at: str
    exit_price: float | None = None
    liquidation_price: float | None = None
    stop_loss_status: str = "unknown"
    trigger_reason: str = ""
    lessons: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_manual_loss_incident_v1",
            "symbol": self.symbol,
            "side": self.side,
            "leverage": self.leverage,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "liquidation_price": self.liquidation_price,
            "stop_loss_status": self.stop_loss_status,
            "trigger_reason": self.trigger_reason,
            "lessons": list(self.lessons),
            "notes": self.notes,
            "occurred_at": self.occurred_at,
        }


@dataclass(frozen=True)
class ManualLossRecordReport:
    status: str
    recorded: bool
    event_id: int | None
    incident: ManualLossIncident
    read_only_exchange: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_manual_loss_record_v1",
            "status": self.status,
            "recorded": self.recorded,
            "event_id": self.event_id,
            "incident": self.incident.to_dict(),
            "read_only_exchange": dict(self.read_only_exchange),
        }


def build_manual_loss_incident(
    *,
    symbol: str,
    side: str,
    leverage: float,
    entry_price: float,
    occurred_at: str | None = None,
    exit_price: float | None = None,
    liquidation_price: float | None = None,
    stop_loss_status: str = "unknown",
    trigger_reason: str = "",
    lessons: Sequence[str] | None = None,
    notes: str | None = None,
) -> ManualLossIncident:
    normalized_symbol = symbol.strip().upper()
    normalized_side = side.strip().lower()
    normalized_stop = stop_loss_status.strip().lower()
    if not normalized_symbol.endswith("USDT") or len(normalized_symbol) <= 4:
        raise ValueError("symbol must be a USDT futures symbol such as SOLUSDT")
    if normalized_side not in VALID_SIDES:
        raise ValueError("side must be long or short")
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if exit_price is None and liquidation_price is None:
        raise ValueError("exit_price or liquidation_price is required")
    if exit_price is not None and exit_price <= 0:
        raise ValueError("exit_price must be positive")
    if liquidation_price is not None and liquidation_price <= 0:
        raise ValueError("liquidation_price must be positive")
    if normalized_stop not in VALID_STOP_LOSS_STATUSES:
        raise ValueError("stop_loss_status must be unknown, none, configured, hit, or missed")
    cleaned_lessons = [str(item).strip() for item in lessons or [] if str(item).strip()]
    return ManualLossIncident(
        symbol=normalized_symbol,
        side=normalized_side,
        leverage=float(leverage),
        entry_price=float(entry_price),
        exit_price=float(exit_price) if exit_price is not None else None,
        liquidation_price=float(liquidation_price) if liquidation_price is not None else None,
        stop_loss_status=normalized_stop,
        trigger_reason=trigger_reason.strip(),
        lessons=cleaned_lessons,
        notes=notes.strip() if notes and notes.strip() else None,
        occurred_at=occurred_at or _now_iso(),
    )


def record_manual_loss_incident(
    config: AppConfig,
    *,
    db_path: str | None = None,
    incident: ManualLossIncident,
) -> ManualLossRecordReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    connection = connect(resolved_db_path)
    try:
        store = EventStore(connection)
        event_id = store.insert_artifact(
            "risk_state",
            occurred_at=incident.occurred_at,
            source="operator_manual_loss",
            symbol=incident.symbol,
            ref_id=f"manual_loss:{incident.symbol}:{incident.occurred_at}",
            event_type="manual_loss_incident",
            payload=incident.to_dict(),
        )
    finally:
        connection.close()
    return ManualLossRecordReport(
        status="manual_loss_recorded",
        recorded=True,
        event_id=event_id,
        incident=incident,
        read_only_exchange={
            "places_orders": False,
            "cancels_orders": False,
            "mutates_exchange_state": False,
            "changes_systemd_state": False,
            "writes_env_files": False,
        },
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
