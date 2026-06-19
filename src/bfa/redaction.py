"""Utilities for removing secret values from diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTION_MARKER = "<redacted>"
_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "cookie",
    "authorization",
    "private_key",
)
_NON_SENSITIVE_KEYS = {
    "max_tokens",
    "max_output_tokens",
    "openai_max_output_tokens",
}


def is_sensitive_key(key: str) -> bool:
    """Return true when a config or diagnostic key is likely secret-bearing."""

    normalized = str(key).lower().replace("-", "_")
    if normalized in _NON_SENSITIVE_KEYS or normalized.endswith("_max_output_tokens"):
        return False
    return any(part in normalized for part in _SENSITIVE_PARTS)


def redact_value(value: Any) -> Any:
    """Redact a scalar secret value while preserving empty values."""

    if value is None or value == "":
        return value
    return REDACTION_MARKER


def redact_object(value: Any) -> Any:
    """Recursively redact secret-bearing values from nested diagnostics."""

    return _redact_object(value, sensitive_context=False)


def _redact_object(value: Any, *, sensitive_context: bool) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _redact_object(item, sensitive_context=is_sensitive_key(str(key)))
            for key, item in value.items()
        }

    if isinstance(value, tuple):
        return tuple(_redact_object(item, sensitive_context=sensitive_context) for item in value)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_object(item, sensitive_context=sensitive_context) for item in value]

    if sensitive_context:
        return redact_value(value)

    return value
