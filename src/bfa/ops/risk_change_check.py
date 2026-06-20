"""Read-only gate for deciding whether live risk limits may be changed."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.ops.live_status import LiveStatusReport, build_live_status_report


@dataclass(frozen=True)
class SubmittedIntentWithoutOutcome:
    event_id: int
    occurred_at: str
    symbol: str
    side: str | None = None
    quantity: float | None = None
    leverage: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "leverage": self.leverage,
        }


@dataclass(frozen=True)
class RiskChangeCheckReport:
    status: str
    risk_change_allowed: bool
    reasons: list[str] = field(default_factory=list)
    account: dict[str, Any] = field(default_factory=dict)
    position_count: int = 0
    open_order_count: int = 0
    open_algo_order_count: int = 0
    openai_backoff_active: bool = False
    target_leverage: int | None = None
    current_max_leverage: float | None = None
    unreconciled_submitted_intents: list[SubmittedIntentWithoutOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "risk_change_allowed": self.risk_change_allowed,
            "reasons": list(self.reasons),
            "account": dict(self.account),
            "position_count": self.position_count,
            "open_order_count": self.open_order_count,
            "open_algo_order_count": self.open_algo_order_count,
            "openai_backoff_active": self.openai_backoff_active,
            "target_leverage": self.target_leverage,
            "current_max_leverage": self.current_max_leverage,
            "unreconciled_submitted_intents": [
                item.to_dict() for item in self.unreconciled_submitted_intents
            ],
        }


def build_risk_change_check_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    target_leverage: int | None = None,
    live_status_report: LiveStatusReport | None = None,
) -> RiskChangeCheckReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    live_status = live_status_report or build_live_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
    )
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        unreconciled = unreconciled_submitted_intents(connection)
    finally:
        connection.close()
    return risk_change_check_from_live_status(
        live_status,
        unreconciled_submitted_intents=unreconciled,
        target_leverage=target_leverage,
        current_max_leverage=_float_or_none(config.get("BFA_MAX_LEVERAGE")),
    )


def risk_change_check_from_live_status(
    report: LiveStatusReport,
    *,
    unreconciled_submitted_intents: list[SubmittedIntentWithoutOutcome] | None = None,
    target_leverage: int | None = None,
    current_max_leverage: float | None = None,
) -> RiskChangeCheckReport:
    payload = report.to_dict()
    exchange = _mapping(payload.get("exchange_evidence"))
    has_exchange_evidence = bool(exchange)
    positions = _list(exchange.get("positions"))
    open_orders = _list(exchange.get("open_orders"))
    open_algo_orders = _list(exchange.get("open_algo_orders"))
    account = _mapping(exchange.get("account"))
    protective = _mapping(payload.get("protective_evidence"))
    backoff = _mapping(payload.get("openai_backoff"))
    unreconciled = list(unreconciled_submitted_intents or [])

    reasons: list[str] = []
    status = "risk_change_allowed"
    backoff_active = bool(backoff.get("active"))

    if not has_exchange_evidence:
        reasons.append("exchange_evidence_missing")
        status = "keep_current_profile"
    if backoff_active:
        reasons.append("ai_backoff_active")
        status = "keep_current_profile"
    if positions:
        reasons.append("active_position_present")
        if open_algo_orders and bool(protective.get("complete")):
            reasons.append("position_has_algo_protection")
            status = "keep_current_profile"
        else:
            reasons.append("active_position_without_confirmed_algo_protection")
            status = "urgent_attention"
    elif open_orders or open_algo_orders:
        reasons.append("open_orders_without_position")
        status = "urgent_attention"
    if unreconciled:
        reasons.append("submitted_intents_missing_outcomes")
        if status == "risk_change_allowed":
            status = "keep_current_profile"

    allowed = not reasons
    if allowed:
        reasons = ["exchange_clear_and_outcomes_reconciled"]

    return RiskChangeCheckReport(
        status=status,
        risk_change_allowed=allowed,
        reasons=reasons,
        account=dict(account),
        position_count=len(positions),
        open_order_count=len(open_orders),
        open_algo_order_count=len(open_algo_orders),
        openai_backoff_active=backoff_active,
        target_leverage=target_leverage,
        current_max_leverage=current_max_leverage,
        unreconciled_submitted_intents=unreconciled,
    )


def unreconciled_submitted_intents(connection: sqlite3.Connection) -> list[SubmittedIntentWithoutOutcome]:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        ORDER BY occurred_at ASC, id ASC
        """
    ).fetchall()
    missing: list[SubmittedIntentWithoutOutcome] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if payload.get("status") != "submitted":
            continue
        event_id = int(row["event_id"])
        if _has_outcome_for_event(connection, event_id):
            continue
        intent = payload.get("intent")
        intent_payload = intent if isinstance(intent, Mapping) else {}
        missing.append(
            SubmittedIntentWithoutOutcome(
                event_id=event_id,
                occurred_at=str(row["occurred_at"]),
                symbol=str(row["symbol"] or intent_payload.get("symbol", "")).upper(),
                side=_optional_str(intent_payload.get("side")),
                quantity=_float_or_none(intent_payload.get("quantity")),
                leverage=_int_or_none(intent_payload.get("leverage")),
            )
        )
    return missing


def _has_outcome_for_event(connection: sqlite3.Connection, event_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM outcomes
        WHERE ref_id LIKE ?
        LIMIT 1
        """,
        (f"outcome:{event_id}:%",),
    ).fetchone()
    return row is not None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


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
