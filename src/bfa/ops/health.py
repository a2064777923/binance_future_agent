"""Server-side health checks for isolated deployments."""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from bfa.ai.providers import build_ai_client
from bfa.config import AppConfig, RuntimeMode, validate_config
from bfa.event_store.migrations import connect, migrate
from bfa.market.binance_rest import BinanceFuturesRestClient


class MarketHealthClient(Protocol):
    def exchange_info(self) -> Any:
        ...


class OpenAIHealthClient(Protocol):
    def create_decision(self, context, *, instructions, schema) -> Any:
        ...


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    mode: str | None
    checks: list[HealthCheck] = field(default_factory=list)
    redacted_config: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "checks": [check.to_dict() for check in self.checks],
            "redacted_config": dict(self.redacted_config),
        }


def run_health_checks(
    config: AppConfig,
    *,
    db_path: str | None = None,
    create_dirs: bool = False,
    check_binance: bool = False,
    check_openai: bool = False,
    market_client: MarketHealthClient | None = None,
    ai_client: OpenAIHealthClient | None = None,
) -> HealthReport:
    validation = validate_config(config)
    checks: list[HealthCheck] = [
        HealthCheck(
            name="config",
            status="passed" if validation.valid else "failed",
            detail="valid" if validation.valid else "; ".join(validation.errors),
        )
    ]

    checks.extend(_directory_checks(config, create_dirs=create_dirs))
    checks.append(_kill_switch_check(config))
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    checks.append(_database_check(resolved_db_path, create_dirs=create_dirs))
    checks.append(_risk_state_check(resolved_db_path))
    checks.append(_binance_check(config, check_binance=check_binance, market_client=market_client))
    checks.append(_openai_check(config, check_openai=check_openai, ai_client=ai_client))

    failed = any(check.status == "failed" for check in checks)
    return HealthReport(
        ok=not failed,
        mode=validation.mode.value if validation.mode is not None else None,
        checks=checks,
        redacted_config=validation.redacted,
    )


def _directory_checks(config: AppConfig, *, create_dirs: bool) -> list[HealthCheck]:
    checks = []
    for name, raw_path in (
        ("runtime_dir", config.get("BFA_RUNTIME_DIR")),
        ("log_dir", config.get("BFA_LOG_DIR")),
        ("square_export_dir", config.get("SQUARE_EXPORT_DIR")),
    ):
        checks.append(_directory_check(name, raw_path, create_dirs=create_dirs))
    return checks


def _directory_check(name: str, raw_path: str, *, create_dirs: bool) -> HealthCheck:
    path = Path(raw_path)
    if create_dirs:
        path.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return HealthCheck(name, "failed", f"missing directory: {path}")
    if not path.is_dir():
        return HealthCheck(name, "failed", f"not a directory: {path}")
    return HealthCheck(name, "passed", str(path))


def _kill_switch_check(config: AppConfig) -> HealthCheck:
    raw_path = config.get("BFA_KILL_SWITCH_FILE")
    if not raw_path:
        return HealthCheck("kill_switch", "failed", "BFA_KILL_SWITCH_FILE is empty")
    path = Path(raw_path)
    if not path.parent.exists():
        return HealthCheck("kill_switch", "failed", f"missing parent directory: {path.parent}")
    active = path.exists()
    if config.get("BFA_MODE") == RuntimeMode.LIVE.value and active:
        return HealthCheck("kill_switch", "failed", f"active kill switch: {path}")
    return HealthCheck("kill_switch", "passed", "active" if active else "inactive")


def _database_check(raw_path: str, *, create_dirs: bool) -> HealthCheck:
    path = Path(raw_path)
    if create_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.exists():
        return HealthCheck("database", "failed", f"missing parent directory: {path.parent}")
    try:
        connection = connect(path)
        try:
            migrate(connection)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return HealthCheck("database", "failed", str(exc))
    return HealthCheck("database", "passed", str(path))


def _risk_state_check(raw_path: str) -> HealthCheck:
    path = Path(raw_path)
    if not path.exists():
        return HealthCheck("risk_state", "failed", f"database missing: {path}")
    try:
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'risk_state'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return HealthCheck("risk_state", "failed", str(exc))
    if row is None:
        return HealthCheck("risk_state", "failed", "risk_state table missing")
    return HealthCheck("risk_state", "passed", "risk_state table ready")


def _binance_check(
    config: AppConfig,
    *,
    check_binance: bool,
    market_client: MarketHealthClient | None,
) -> HealthCheck:
    if not check_binance:
        return HealthCheck("binance_public", "skipped", "network check disabled")
    client = market_client or BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))
    try:
        client.exchange_info()
    except Exception as exc:  # pragma: no cover - exact network exceptions vary.
        return HealthCheck("binance_public", "failed", str(exc))
    return HealthCheck("binance_public", "passed", "exchangeInfo reachable")


def _openai_check(
    config: AppConfig,
    *,
    check_openai: bool,
    ai_client: OpenAIHealthClient | None,
) -> HealthCheck:
    if not check_openai:
        return HealthCheck("openai", "skipped", "network check disabled")
    if config.get("BFA_OPENAI_ENABLED").lower() not in {"1", "true", "yes", "on"}:
        return HealthCheck("openai", "skipped", "BFA_OPENAI_ENABLED is false")
    client = ai_client or build_ai_client(config, max_output_tokens=20)
    try:
        client.create_decision(
            {"health_check": True},
            instructions="Return a JSON object with ok=true.",
            schema=_health_schema(),
        )
    except Exception as exc:  # pragma: no cover - exact network exceptions vary.
        return HealthCheck("openai", "failed", str(exc))
    provider = config.get("BFA_AI_PROVIDER", "openai")
    return HealthCheck("openai", "passed", f"{provider} AI API reachable")


def _health_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "bfa_health_check",
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    }
