"""Read-only live activation status reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.execution.binance_client import BinanceFuturesSignedClient


@dataclass(frozen=True)
class LatestArtifact:
    table: str
    event_id: int | None
    occurred_at: str
    symbol: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class ProtectiveEvidence:
    complete: bool
    event_id: int | None = None
    symbol: str | None = None
    occurred_at: str | None = None
    status: str = "missing"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "event_id": self.event_id,
            "symbol": self.symbol,
            "occurred_at": self.occurred_at,
            "status": self.status,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class OpenAiBackoffStatus:
    active: bool
    retry_after: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "retry_after": self.retry_after,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LiveStatusReport:
    db_path: str
    runtime_dir: str
    counts: dict[str, int]
    latest: dict[str, LatestArtifact | None]
    openai_backoff: OpenAiBackoffStatus
    protective_evidence: ProtectiveEvidence
    lva05_complete: bool
    exchange_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "runtime_dir": self.runtime_dir,
            "counts": dict(self.counts),
            "latest": {
                key: value.to_dict() if value is not None else None
                for key, value in self.latest.items()
            },
            "openai_backoff": self.openai_backoff.to_dict(),
            "protective_evidence": self.protective_evidence.to_dict(),
            "exchange_evidence": dict(self.exchange_evidence),
            "lva05_complete": self.lva05_complete,
        }


def build_live_status_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    now_epoch: float | None = None,
    check_binance: bool = False,
) -> LiveStatusReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    runtime_dir = config.get("BFA_RUNTIME_DIR")
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        latest = {
            "candidate": _latest_artifact(connection, "candidates"),
            "ai_decision": _latest_artifact(connection, "ai_decisions"),
            "order_intent": _latest_artifact(connection, "order_intents"),
            "exchange_response": _latest_artifact(connection, "exchange_responses"),
        }
        counts = {
            "candidates": _count(connection, "candidates"),
            "ai_decisions": _count(connection, "ai_decisions"),
            "order_intents": _count(connection, "order_intents"),
            "exchange_responses": _count(connection, "exchange_responses"),
            "submitted_order_intents": _count_order_intents_by_status(connection, "submitted"),
        }
        protective = _protective_evidence(connection)
    finally:
        connection.close()

    backoff = _openai_backoff_status(Path(runtime_dir), now_epoch=now_epoch)
    exchange_evidence = _read_exchange_evidence(config) if check_binance else {}
    if exchange_evidence:
        protective = _merge_protective_evidence(protective, exchange_evidence)
    return LiveStatusReport(
        db_path=str(resolved_db_path),
        runtime_dir=str(runtime_dir),
        counts=counts,
        latest=latest,
        openai_backoff=backoff,
        protective_evidence=protective,
        exchange_evidence=exchange_evidence,
        lva05_complete=protective.complete,
    )


def _latest_artifact(connection: sqlite3.Connection, table: str) -> LatestArtifact | None:
    row = connection.execute(
        f"""
        SELECT event_id, occurred_at, symbol, payload_json
        FROM {table}
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return LatestArtifact(
        table=table,
        event_id=int(row["event_id"]) if row["event_id"] is not None else None,
        occurred_at=str(row["occurred_at"]),
        symbol=row["symbol"],
        payload=json.loads(str(row["payload_json"])),
    )


def _protective_evidence(connection: sqlite3.Connection) -> ProtectiveEvidence:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM exchange_responses
        ORDER BY occurred_at DESC, id DESC
        """
    ).fetchall()
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        if _has_entry_and_protective_orders(response):
            return ProtectiveEvidence(
                complete=True,
                event_id=int(row["event_id"]) if row["event_id"] is not None else None,
                symbol=row["symbol"],
                occurred_at=str(row["occurred_at"]),
                status="entry_with_stop_loss_and_take_profit",
                details=_protective_summary(response),
            )
        if response.get("kill_switch_activated") and (
            "emergency_close_order" in response or "emergency_close_error" in response
        ):
            return ProtectiveEvidence(
                complete=True,
                event_id=int(row["event_id"]) if row["event_id"] is not None else None,
                symbol=row["symbol"],
                occurred_at=str(row["occurred_at"]),
                status="protective_failure_fail_closed",
                details=_protective_summary(response),
            )
    return ProtectiveEvidence(complete=False)


def _read_exchange_evidence(config: AppConfig) -> dict[str, Any]:
    client = BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )
    account = client.account()
    positions = client.position_risk()
    open_orders = client.open_orders()
    return {
        "account": {
            "can_trade": account.get("canTrade"),
            "total_wallet_balance": account.get("totalWalletBalance"),
            "available_balance": account.get("availableBalance"),
        },
        "positions": [p for p in positions if _float(p.get("positionAmt")) != 0.0],
        "open_orders": open_orders,
    }


def _merge_protective_evidence(
    evidence: ProtectiveEvidence,
    exchange_evidence: dict[str, Any],
) -> ProtectiveEvidence:
    positions = exchange_evidence.get("positions") or []
    open_orders = exchange_evidence.get("open_orders") or []
    if not positions and not open_orders:
        return evidence
    details = dict(evidence.details)
    details.update(
        {
            "exchange_positions": len(positions),
            "exchange_open_orders": len(open_orders),
        }
    )
    return ProtectiveEvidence(
        complete=evidence.complete,
        event_id=evidence.event_id,
        symbol=evidence.symbol,
        occurred_at=evidence.occurred_at,
        status=evidence.status,
        details=details,
    )


def _has_entry_and_protective_orders(response: dict[str, Any]) -> bool:
    return all(
        isinstance(response.get(key), dict)
        for key in ("entry_order", "stop_loss_order", "take_profit_order")
    )


def _protective_summary(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "has_entry_order": isinstance(response.get("entry_order"), dict),
        "has_stop_loss_order": isinstance(response.get("stop_loss_order"), dict),
        "has_take_profit_order": isinstance(response.get("take_profit_order"), dict),
        "kill_switch_activated": bool(response.get("kill_switch_activated")),
        "has_emergency_close_order": isinstance(response.get("emergency_close_order"), dict),
        "has_emergency_close_error": isinstance(response.get("emergency_close_error"), dict),
    }


def _openai_backoff_status(runtime_dir: Path, *, now_epoch: float | None) -> OpenAiBackoffStatus:
    path = runtime_dir / "openai_backoff.json"
    if not path.exists():
        return OpenAiBackoffStatus(active=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        retry_after_epoch = float(payload.get("retry_after_epoch", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return OpenAiBackoffStatus(active=False, reason="unreadable_backoff_file")
    active = (time.time() if now_epoch is None else now_epoch) < retry_after_epoch
    return OpenAiBackoffStatus(
        active=active,
        retry_after=str(payload.get("retry_after") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _count_order_intents_by_status(connection: sqlite3.Connection, status: str) -> int:
    rows = connection.execute("SELECT payload_json FROM order_intents").fetchall()
    count = 0
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if payload.get("status") == status:
            count += 1
    return count


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
