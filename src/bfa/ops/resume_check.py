"""Read-only gate for deciding whether live automation can be resumed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.ops.live_status import LiveStatusReport, build_live_status_report


@dataclass(frozen=True)
class ResumeCheckReport:
    status: str
    resume_allowed: bool
    reasons: list[str] = field(default_factory=list)
    account: dict[str, Any] = field(default_factory=dict)
    position_count: int = 0
    open_order_count: int = 0
    open_algo_order_count: int = 0
    lva05_complete: bool = False
    openai_backoff_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "resume_allowed": self.resume_allowed,
            "reasons": list(self.reasons),
            "account": dict(self.account),
            "position_count": self.position_count,
            "open_order_count": self.open_order_count,
            "open_algo_order_count": self.open_algo_order_count,
            "lva05_complete": self.lva05_complete,
            "openai_backoff_active": self.openai_backoff_active,
        }


def build_resume_check_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    live_status_report: LiveStatusReport | None = None,
) -> ResumeCheckReport:
    report = live_status_report or build_live_status_report(
        config,
        db_path=db_path,
        check_binance=check_binance,
    )
    return resume_check_from_live_status(report)


def resume_check_from_live_status(report: LiveStatusReport) -> ResumeCheckReport:
    payload = report.to_dict()
    exchange = _mapping(payload.get("exchange_evidence"))
    has_exchange_evidence = bool(exchange)
    positions = _list(exchange.get("positions"))
    open_orders = _list(exchange.get("open_orders"))
    open_algo_orders = _list(exchange.get("open_algo_orders"))
    account = _mapping(exchange.get("account"))
    protective = _mapping(payload.get("protective_evidence"))
    backoff = _mapping(payload.get("openai_backoff"))

    reasons: list[str] = []
    backoff_active = bool(backoff.get("active"))
    if backoff_active:
        reasons.append("ai_backoff_active")
    if not has_exchange_evidence:
        return ResumeCheckReport(
            status="keep_paused",
            resume_allowed=False,
            reasons=[*reasons, "exchange_evidence_missing"],
            account={},
            position_count=0,
            open_order_count=0,
            open_algo_order_count=0,
            lva05_complete=bool(payload.get("lva05_complete")),
            openai_backoff_active=backoff_active,
        )

    if positions:
        reasons.append("active_position_present")
        if open_algo_orders and bool(protective.get("complete")):
            return ResumeCheckReport(
                status="keep_paused",
                resume_allowed=False,
                reasons=[*reasons, "position_has_algo_protection"],
                account=dict(account),
                position_count=len(positions),
                open_order_count=len(open_orders),
                open_algo_order_count=len(open_algo_orders),
                lva05_complete=bool(payload.get("lva05_complete")),
                openai_backoff_active=backoff_active,
            )
        return ResumeCheckReport(
            status="urgent_attention",
            resume_allowed=False,
            reasons=[*reasons, "active_position_without_confirmed_algo_protection"],
            account=dict(account),
            position_count=len(positions),
            open_order_count=len(open_orders),
            open_algo_order_count=len(open_algo_orders),
            lva05_complete=bool(payload.get("lva05_complete")),
            openai_backoff_active=backoff_active,
        )

    if open_orders or open_algo_orders:
        reasons.append("open_orders_without_position")
        return ResumeCheckReport(
            status="urgent_attention",
            resume_allowed=False,
            reasons=reasons,
            account=dict(account),
            position_count=0,
            open_order_count=len(open_orders),
            open_algo_order_count=len(open_algo_orders),
            lva05_complete=bool(payload.get("lva05_complete")),
            openai_backoff_active=backoff_active,
        )

    if backoff_active:
        return ResumeCheckReport(
            status="keep_paused",
            resume_allowed=False,
            reasons=reasons,
            account=dict(account),
            position_count=0,
            open_order_count=0,
            open_algo_order_count=0,
            lva05_complete=bool(payload.get("lva05_complete")),
            openai_backoff_active=True,
        )

    return ResumeCheckReport(
        status="resume_allowed",
        resume_allowed=True,
        reasons=["no_active_position_or_open_orders"],
        account=dict(account),
        position_count=0,
        open_order_count=0,
        open_algo_order_count=0,
        lva05_complete=bool(payload.get("lva05_complete")),
        openai_backoff_active=False,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
