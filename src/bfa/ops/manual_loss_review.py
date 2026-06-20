"""Read-only review of manual loss incidents against deterministic guards."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.strategy.paper_guard import (
    ForwardPaperGuard,
    ForwardPaperGuardConfig,
    build_forward_paper_guard,
    guard_config_from_app,
)


BLOCKING_STOP_STATUSES = {"none", "missed", "unknown"}


@dataclass(frozen=True)
class ManualLossReviewItem:
    event_id: int
    occurred_at: str
    symbol: str
    side: str
    leverage: float
    entry_price: float
    exit_price: float | None
    liquidation_price: float | None
    stop_loss_status: str
    trigger_reason: str
    lessons: list[str]
    guard_outcome: str
    risk_checks: list[dict[str, Any]] = field(default_factory=list)
    paper_guard_checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "leverage": self.leverage,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "liquidation_price": self.liquidation_price,
            "stop_loss_status": self.stop_loss_status,
            "trigger_reason": self.trigger_reason,
            "lessons": list(self.lessons),
            "guard_outcome": self.guard_outcome,
            "risk_checks": [dict(item) for item in self.risk_checks],
            "paper_guard_checks": [dict(item) for item in self.paper_guard_checks],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ManualLossReviewReport:
    status: str
    reasons: list[str]
    incident_count: int
    summary: dict[str, Any]
    items: list[ManualLossReviewItem] = field(default_factory=list)
    paper_guard: dict[str, Any] = field(default_factory=dict)
    read_only_exchange: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_manual_loss_review_v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "incident_count": self.incident_count,
            "summary": dict(self.summary),
            "items": [item.to_dict() for item in self.items],
            "paper_guard": dict(self.paper_guard),
            "read_only_exchange": dict(self.read_only_exchange),
        }


def build_manual_loss_review_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    include_paper_guard: bool = True,
    guard_config: ForwardPaperGuardConfig | None = None,
) -> ManualLossReviewReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        incidents = _load_manual_loss_incidents(connection)
        paper_guard = (
            build_forward_paper_guard(connection, guard_config or guard_config_from_app(config))
            if include_paper_guard
            else None
        )
    finally:
        connection.close()

    items = [
        _review_incident(
            incident,
            max_leverage=_float_or_zero(config.get("BFA_MAX_LEVERAGE")),
            paper_guard=paper_guard,
        )
        for incident in incidents
    ]
    status = "review_ready" if items else "no_manual_loss_incidents"
    reasons = ["manual_loss_review_ready"] if items else ["manual_loss_incidents_missing"]
    return ManualLossReviewReport(
        status=status,
        reasons=reasons,
        incident_count=len(items),
        summary=_summary(items),
        items=items,
        paper_guard=paper_guard.to_dict() if paper_guard else {"status": "skipped"},
        read_only_exchange={
            "places_orders": False,
            "cancels_orders": False,
            "mutates_exchange_state": False,
            "changes_systemd_state": False,
            "writes_env_files": False,
        },
    )


def _load_manual_loss_incidents(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM risk_state
        WHERE json_extract(payload_json, '$.schema') = 'bfa_manual_loss_incident_v1'
           OR source = 'operator_manual_loss'
           OR ref_id LIKE 'manual_loss:%'
        ORDER BY occurred_at ASC, id ASC
        """
    ).fetchall()
    incidents: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        payload["event_id"] = int(row["event_id"] or 0)
        payload["occurred_at"] = str(payload.get("occurred_at") or row["occurred_at"])
        payload["symbol"] = str(payload.get("symbol") or row["symbol"] or "").upper()
        incidents.append(payload)
    return incidents


def _review_incident(
    incident: Mapping[str, Any],
    *,
    max_leverage: float,
    paper_guard: ForwardPaperGuard | None,
) -> ManualLossReviewItem:
    symbol = str(incident.get("symbol") or "").upper()
    side = str(incident.get("side") or "").lower()
    leverage = _float_or_zero(incident.get("leverage"))
    entry_price = _float_or_zero(incident.get("entry_price"))
    exit_price = _float_or_none(incident.get("exit_price"))
    liquidation_price = _float_or_none(incident.get("liquidation_price"))
    stop_loss_status = str(incident.get("stop_loss_status") or "unknown").lower()
    trigger_reason = str(incident.get("trigger_reason") or "")
    lessons = [str(item) for item in _list(incident.get("lessons")) if str(item)]
    risk_checks = _risk_checks(
        leverage=leverage,
        max_leverage=max_leverage,
        entry_price=entry_price,
        liquidation_price=liquidation_price,
        stop_loss_status=stop_loss_status,
    )
    paper_checks = _paper_guard_checks(symbol=symbol, side=side, paper_guard=paper_guard)
    warnings = _warnings(entry_price=entry_price, liquidation_price=liquidation_price)
    guard_outcome = _guard_outcome(risk_checks, paper_checks, warnings)
    return ManualLossReviewItem(
        event_id=_int_or_zero(incident.get("event_id")),
        occurred_at=str(incident.get("occurred_at") or ""),
        symbol=symbol,
        side=side,
        leverage=leverage,
        entry_price=entry_price,
        exit_price=exit_price,
        liquidation_price=liquidation_price,
        stop_loss_status=stop_loss_status,
        trigger_reason=trigger_reason,
        lessons=lessons,
        guard_outcome=guard_outcome,
        risk_checks=risk_checks,
        paper_guard_checks=paper_checks,
        warnings=warnings,
    )


def _risk_checks(
    *,
    leverage: float,
    max_leverage: float,
    entry_price: float,
    liquidation_price: float | None,
    stop_loss_status: str,
) -> list[dict[str, Any]]:
    checks = [
        {
            "rule": "max_leverage",
            "status": "blocked" if max_leverage > 0 and leverage > max_leverage else "passed",
            "observed": leverage,
            "limit": max_leverage,
        },
        {
            "rule": "protective_stop_required",
            "status": "blocked" if stop_loss_status in BLOCKING_STOP_STATUSES else "passed",
            "observed": stop_loss_status,
        },
    ]
    liquidation_distance = _liquidation_distance_percent(entry_price, liquidation_price)
    if liquidation_distance is not None:
        checks.append(
            {
                "rule": "liquidation_distance_warning",
                "status": "warning" if liquidation_distance <= 2.0 else "passed",
                "observed_percent": liquidation_distance,
                "warning_threshold_percent": 2.0,
            }
        )
    return checks


def _paper_guard_checks(
    *,
    symbol: str,
    side: str,
    paper_guard: ForwardPaperGuard | None,
) -> list[dict[str, Any]]:
    if paper_guard is None:
        return [{"rule": "forward_paper_guard", "status": "skipped"}]
    checks = [
        {
            "rule": "forward_paper_symbol_block",
            "status": "blocked" if paper_guard.blocks_symbol(symbol) else "passed",
            "observed": symbol,
        },
        {
            "rule": "forward_paper_side_block",
            "status": "blocked" if side in paper_guard.side_blocks else "passed",
            "observed": side,
        },
    ]
    return checks


def _warnings(*, entry_price: float, liquidation_price: float | None) -> list[str]:
    distance = _liquidation_distance_percent(entry_price, liquidation_price)
    if distance is not None and distance <= 2.0:
        return ["liquidation_distance_within_2_percent"]
    return []


def _guard_outcome(
    risk_checks: list[dict[str, Any]],
    paper_checks: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    if any(check.get("status") == "blocked" for check in risk_checks):
        return "would_block_by_risk_guard"
    if any(check.get("status") == "blocked" for check in paper_checks):
        return "would_block_by_paper_guard"
    if warnings or any(check.get("status") == "warning" for check in risk_checks):
        return "would_warn_or_reduce"
    return "not_caught_by_current_guards"


def _summary(items: list[ManualLossReviewItem]) -> dict[str, Any]:
    outcomes = [item.guard_outcome for item in items]
    return {
        "would_block_by_risk_guard": outcomes.count("would_block_by_risk_guard"),
        "would_block_by_paper_guard": outcomes.count("would_block_by_paper_guard"),
        "would_warn_or_reduce": outcomes.count("would_warn_or_reduce"),
        "not_caught_by_current_guards": outcomes.count("not_caught_by_current_guards"),
    }


def _liquidation_distance_percent(entry_price: float, liquidation_price: float | None) -> float | None:
    if entry_price <= 0 or liquidation_price is None or liquidation_price <= 0:
        return None
    return round(abs(entry_price - liquidation_price) / entry_price * 100.0, 8)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
