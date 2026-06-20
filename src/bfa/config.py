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
    "BFA_AI_PROVIDER": "openai",
    "BFA_OPENAI_ENABLED": "false",
    "BFA_AI_FALLBACK_TO_QUANT_ENABLED": "false",
    "BFA_ACCOUNT_CAPITAL_USDT": "100",
    "BFA_MAX_LEVERAGE": "3",
    "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
    "BFA_MAX_RISK_PER_TRADE_USDT": "1",
    "BFA_MAX_DAILY_LOSS_USDT": "3",
    "BFA_MAX_OPEN_POSITIONS": "2",
    "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "false",
    "BFA_MAX_MARGIN_PER_POSITION_USDT": "2.4",
    "BFA_MAX_MARGIN_FRACTION": "0.08",
    "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "20",
    "BFA_MAX_PORTFOLIO_MARGIN_USDT": "20",
    "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "0.2",
    "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "60",
    "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "40",
    "BFA_MULTI_POSITION_ENABLED": "false",
    "BFA_POSITION_ADJUSTMENT_ENABLED": "true",
    "BFA_POSITION_AUTO_MANAGEMENT_ENABLED": "false",
    "BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE": "1",
    "BFA_POSITION_REVIEW_INTERVAL_MINUTES": "15",
    "BFA_PARTIAL_TAKE_PROFIT_FRACTION": "0.5",
    "BFA_REQUIRE_PROTECTIVE_ORDERS": "true",
    "BFA_MARGIN_MODE": "isolated",
    "BFA_POSITION_MODE": "one_way",
    "BFA_KILL_SWITCH_FILE": "/opt/binance-futures-agent/runtime/KILL_SWITCH",
    "BFA_MARKET_SYMBOLS": "HYPEUSDT,SOLUSDT,ZECUSDT,WLDUSDT,XRPUSDT,AVAXUSDT,BNBUSDT,DOGEUSDT,NEARUSDT,ADAUSDT",
    "BFA_MANUAL_POSITION_SYMBOLS": "",
    "BFA_LIVE_AUTO_HOT_SYMBOLS": "false",
    "BFA_LIVE_AUTO_HOT_TOP_N": "40",
    "BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT": "10000000",
    "BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT": "0.5",
    "BFA_FORWARD_PAPER_SYMBOLS": "",
    "BFA_FORWARD_PAPER_AUTO_HOT_SYMBOLS": "true",
    "BFA_FORWARD_PAPER_TOP_N": "40",
    "BFA_FORWARD_PAPER_MIN_QUOTE_VOLUME_USDT": "10000000",
    "BFA_FORWARD_PAPER_MIN_ABS_PRICE_CHANGE_PERCENT": "0.5",
    "BFA_FORWARD_PAPER_GUARD_ENABLED": "true",
    "BFA_FORWARD_PAPER_GUARD_VARIANT": "quant_setup_selective",
    "BFA_FORWARD_PAPER_GUARD_INTERVAL": "5m",
    "BFA_FORWARD_PAPER_GUARD_SINCE": "",
    "BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES": "30",
    "BFA_FORWARD_PAPER_GUARD_MIN_SYMBOL_OUTCOMES": "3",
    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MIN_LOSS_USDT": "0.5",
    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MAX_WIN_RATE": "0.3",
    "BFA_FORWARD_PAPER_GUARD_MIN_SIDE_OUTCOMES": "20",
    "BFA_FORWARD_PAPER_GUARD_SIDE_MIN_LOSS_USDT": "2",
    "BFA_FORWARD_PAPER_GUARD_SIDE_MAX_WIN_RATE": "0.3",
    "BFA_FORWARD_PAPER_GUARD_MIN_FACTOR_OUTCOMES": "30",
    "BFA_FORWARD_PAPER_GUARD_FACTOR_MIN_LOSS_USDT": "3",
    "BFA_FORWARD_PAPER_GUARD_FACTOR_MAX_WIN_RATE": "0.25",
    "BFA_MARKET_HEAT_NARRATIVE_ENABLED": "true",
    "BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT": "5000000",
    "BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT": "0.3",
    "BFA_MARKET_HEAT_MIN_TAKER_BUY_SELL_RATIO": "1.05",
    "BFA_MARKET_HEAT_MIN_OPEN_INTEREST_VALUE_USDT": "1000000",
    "BFA_MARKET_HEAT_MAX_KLINE_RANGE_PERCENT": "15",
    "BFA_MARKET_HEAT_MAX_RECORDS": "3",
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
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-v4-flash",
}

NUMERIC_FIELDS = (
    "BFA_ACCOUNT_CAPITAL_USDT",
    "BFA_MAX_LEVERAGE",
    "BFA_MAX_POSITION_NOTIONAL_USDT",
    "BFA_MAX_RISK_PER_TRADE_USDT",
    "BFA_MAX_DAILY_LOSS_USDT",
    "BFA_MAX_MARGIN_PER_POSITION_USDT",
    "BFA_MAX_MARGIN_FRACTION",
    "BFA_MAX_EFFECTIVE_NOTIONAL_USDT",
    "BFA_MAX_PORTFOLIO_MARGIN_USDT",
    "BFA_MAX_PORTFOLIO_MARGIN_FRACTION",
    "BFA_MAX_PORTFOLIO_NOTIONAL_USDT",
    "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT",
    "BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT",
    "BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT",
    "BFA_MARKET_HEAT_MIN_TAKER_BUY_SELL_RATIO",
    "BFA_MARKET_HEAT_MIN_OPEN_INTEREST_VALUE_USDT",
    "BFA_MARKET_HEAT_MAX_KLINE_RANGE_PERCENT",
    "BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT",
    "BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT",
    "BFA_FORWARD_PAPER_MIN_QUOTE_VOLUME_USDT",
    "BFA_FORWARD_PAPER_MIN_ABS_PRICE_CHANGE_PERCENT",
    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MIN_LOSS_USDT",
    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MAX_WIN_RATE",
    "BFA_FORWARD_PAPER_GUARD_SIDE_MIN_LOSS_USDT",
    "BFA_FORWARD_PAPER_GUARD_SIDE_MAX_WIN_RATE",
    "BFA_FORWARD_PAPER_GUARD_FACTOR_MIN_LOSS_USDT",
    "BFA_FORWARD_PAPER_GUARD_FACTOR_MAX_WIN_RATE",
    "BFA_PARTIAL_TAKE_PROFIT_FRACTION",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_RETRY_AFTER_SECONDS",
)
INTEGER_FIELDS = (
    "BFA_MAX_OPEN_POSITIONS",
    "BFA_MARKET_HEAT_MAX_RECORDS",
    "BFA_LIVE_AUTO_HOT_TOP_N",
    "BFA_FORWARD_PAPER_TOP_N",
    "BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES",
    "BFA_FORWARD_PAPER_GUARD_MIN_SYMBOL_OUTCOMES",
    "BFA_FORWARD_PAPER_GUARD_MIN_SIDE_OUTCOMES",
    "BFA_FORWARD_PAPER_GUARD_MIN_FACTOR_OUTCOMES",
    "BFA_POSITION_REVIEW_INTERVAL_MINUTES",
    "BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE",
    "OPENAI_MAX_OUTPUT_TOKENS",
)


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

    ai_provider = config.get("BFA_AI_PROVIDER").strip().lower()
    if ai_provider not in {"openai", "deepseek"}:
        errors.append("BFA_AI_PROVIDER must be openai or deepseek")
    openai_enabled = _truthy(config.get("BFA_OPENAI_ENABLED"))
    if openai_enabled and ai_provider == "openai" and not config.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is required when BFA_OPENAI_ENABLED=true and BFA_AI_PROVIDER=openai")
    if openai_enabled and ai_provider == "deepseek" and not config.get("DEEPSEEK_API_KEY"):
        errors.append("DEEPSEEK_API_KEY is required when BFA_OPENAI_ENABLED=true and BFA_AI_PROVIDER=deepseek")

    if mode in (RuntimeMode.TESTNET, RuntimeMode.LIVE):
        _required(config, "BINANCE_API_KEY", mode.value, errors)
        _required(config, "BINANCE_API_SECRET", mode.value, errors)

    if mode is RuntimeMode.LIVE:
        if not config.get("BFA_KILL_SWITCH_FILE"):
            errors.append("BFA_KILL_SWITCH_FILE is required for live mode")
        if not _truthy(config.get("BFA_REQUIRE_PROTECTIVE_ORDERS")):
            errors.append("BFA_REQUIRE_PROTECTIVE_ORDERS must be true for live mode")
        if _truthy(config.get("BFA_MULTI_POSITION_ENABLED")):
            warnings.append("BFA_MULTI_POSITION_ENABLED=true allows concurrent live positions")
        if _float_or_zero(config.get("BFA_MAX_LEVERAGE")) > 10:
            warnings.append("BFA_MAX_LEVERAGE above 10x requires extra operator review")
        if config.get("BFA_MARGIN_MODE").strip().lower() == "cross":
            warnings.append("BFA_MARGIN_MODE=cross uses account-level cross margin under pilot caps")
        if config.get("BFA_POSITION_MODE").strip().lower() == "hedge":
            warnings.append("BFA_POSITION_MODE=hedge sends explicit Binance positionSide values")

    if config.get("BFA_MARGIN_MODE").strip().lower() not in {"isolated", "cross"}:
        errors.append("BFA_MARGIN_MODE must be isolated or cross")
    if config.get("BFA_POSITION_MODE").strip().lower() not in {"one_way", "hedge"}:
        errors.append("BFA_POSITION_MODE must be one_way or hedge")

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


def forward_paper_symbols(config: AppConfig) -> list[str]:
    configured = config.get_list("BFA_FORWARD_PAPER_SYMBOLS")
    return configured or market_symbols(config)


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


def _float_or_zero(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
