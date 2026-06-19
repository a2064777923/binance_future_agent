"""Runtime configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
from typing import Mapping

from bfa.redaction import redact_object


class RuntimeMode(StrEnum):
    DRY_RUN = "dry_run"
    TESTNET = "testnet"
    LIVE = "live"


DEFAULTS = {
    "BFA_MODE": RuntimeMode.DRY_RUN.value,
    "BFA_OPENAI_ENABLED": "false",
    "BFA_ACCOUNT_CAPITAL_USDT": "100",
    "BFA_MAX_LEVERAGE": "3",
    "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
    "BFA_MAX_RISK_PER_TRADE_USDT": "1",
    "BFA_MAX_DAILY_LOSS_USDT": "3",
    "BFA_MAX_OPEN_POSITIONS": "2",
    "BFA_REQUIRE_PROTECTIVE_ORDERS": "true",
    "BFA_KILL_SWITCH_FILE": "/opt/binance-futures-agent/runtime/KILL_SWITCH",
    "BFA_MARKET_SYMBOLS": "BTCUSDT,ETHUSDT,SOLUSDT",
    "BFA_DB_PATH": "/opt/binance-futures-agent/data/agent.sqlite",
    "BFA_LOG_DIR": "/opt/binance-futures-agent/logs",
    "BFA_RUNTIME_DIR": "/opt/binance-futures-agent/runtime",
    "SQUARE_COLLECTOR_MODE": "manual",
    "SQUARE_COOKIE_FILE": "",
    "SQUARE_EXPORT_DIR": "/opt/binance-futures-agent/runtime/square_exports",
    "RSS_FEED_URLS": "",
    "X_BEARER_TOKEN": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHANNELS": "",
    "BINANCE_API_KEY": "",
    "BINANCE_API_SECRET": "",
    "BINANCE_FUTURES_BASE_URL": "https://fapi.binance.com",
    "BINANCE_FUTURES_WS_BASE_URL": "wss://fstream.binance.com",
    "BINANCE_USE_TESTNET": "false",
    "OPENAI_API_KEY": "",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-5.4",
    "OPENAI_TIMEOUT_SECONDS": "5",
    "OPENAI_MAX_OUTPUT_TOKENS": "400",
    "OPENAI_RETRY_AFTER_SECONDS": "300",
}

NUMERIC_FIELDS = (
    "BFA_ACCOUNT_CAPITAL_USDT",
    "BFA_MAX_LEVERAGE",
    "BFA_MAX_POSITION_NOTIONAL_USDT",
    "BFA_MAX_RISK_PER_TRADE_USDT",
    "BFA_MAX_DAILY_LOSS_USDT",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_RETRY_AFTER_SECONDS",
)
INTEGER_FIELDS = ("BFA_MAX_OPEN_POSITIONS", "OPENAI_MAX_OUTPUT_TOKENS")


@dataclass(frozen=True)
class AppConfig:
    values: dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_list(self, key: str) -> list[str]:
        return _split_csv_symbols(self.get(key))


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    mode: RuntimeMode | None
    errors: list[str]
    warnings: list[str]
    redacted: dict[str, object]


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    env_file: str | Path | None = None,
) -> AppConfig:
    """Load runtime config from defaults, an optional env file, and a mapping."""

    values = dict(DEFAULTS)
    if env_file is not None:
        values.update(_known_config_values(_read_env_file(Path(env_file))))
    values.update(_known_config_values(os.environ if env is None else env))
    return AppConfig(values={key: str(value) for key, value in values.items()})


def validate_config(config: AppConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    mode = _parse_mode(config.get("BFA_MODE"), errors)

    for field in NUMERIC_FIELDS:
        _positive_number(config.get(field), field, errors)
    for field in INTEGER_FIELDS:
        _positive_integer(config.get(field), field, errors)

    openai_enabled = _truthy(config.get("BFA_OPENAI_ENABLED"))
    if openai_enabled and not config.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is required when BFA_OPENAI_ENABLED=true")

    if mode in (RuntimeMode.TESTNET, RuntimeMode.LIVE):
        _required(config, "BINANCE_API_KEY", mode.value, errors)
        _required(config, "BINANCE_API_SECRET", mode.value, errors)

    if mode is RuntimeMode.LIVE:
        if not config.get("BFA_KILL_SWITCH_FILE"):
            errors.append("BFA_KILL_SWITCH_FILE is required for live mode")
        if not _truthy(config.get("BFA_REQUIRE_PROTECTIVE_ORDERS")):
            errors.append("BFA_REQUIRE_PROTECTIVE_ORDERS must be true for live mode")

    if mode is RuntimeMode.LIVE and config.get("BINANCE_USE_TESTNET").lower() in {"1", "true", "yes"}:
        warnings.append("BINANCE_USE_TESTNET is true while BFA_MODE=live")

    redacted = redact_object(config.values)
    return ValidationResult(
        valid=not errors,
        mode=mode,
        errors=errors,
        warnings=warnings,
        redacted=redacted,
    )


def market_symbols(config: AppConfig) -> list[str]:
    return config.get_list("BFA_MARKET_SYMBOLS")


def rss_feed_urls(config: AppConfig) -> list[str]:
    return _split_csv_values(config.get("RSS_FEED_URLS"))


def telegram_channels(config: AppConfig) -> list[str]:
    return _split_csv_values(config.get("TELEGRAM_CHANNELS"))


def _parse_mode(value: str, errors: list[str]) -> RuntimeMode | None:
    try:
        return RuntimeMode(value or RuntimeMode.DRY_RUN.value)
    except ValueError:
        allowed = ", ".join(mode.value for mode in RuntimeMode)
        errors.append(f"BFA_MODE must be one of: {allowed}")
        return None


def _required(config: AppConfig, key: str, mode: str, errors: list[str]) -> None:
    if not config.get(key):
        errors.append(f"{key} is required for {mode} mode")


def _positive_number(value: str, key: str, errors: list[str]) -> None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append(f"{key} must be a positive number")
        return
    if parsed <= 0:
        errors.append(f"{key} must be a positive number")


def _positive_integer(value: str, key: str, errors: list[str]) -> None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{key} must be a positive integer")
        return
    if parsed <= 0:
        errors.append(f"{key} must be a positive integer")


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_quotes(value.strip())
    return values


def _known_config_values(values: Mapping[str, str]) -> dict[str, str]:
    return {key: str(values[key]) for key in DEFAULTS if key in values}


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _split_csv_symbols(value: str) -> list[str]:
    return _split_csv_values(value, uppercase=True)


def _split_csv_values(value: str, *, uppercase: bool = False) -> list[str]:
    values: list[str] = []
    for raw_value in value.split(","):
        parsed = raw_value.strip()
        if parsed:
            values.append(parsed.upper() if uppercase else parsed)
    return values
