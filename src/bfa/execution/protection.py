"""Shared protective-order policy helpers.

The trigger source is intentionally selected per protective leg.  A scalp
take-profit should react to the traded contract price, while the stop can keep
the smoother mark-price trigger used by the wider trend leg.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bfa.config import AppConfig


SUPPORTED_WORKING_TYPES = frozenset({"MARK_PRICE", "CONTRACT_PRICE"})
MICRO_STRATEGY_LEGS = frozenset({"micro_grid", "range_reversion"})


def strategy_leg_from_context(
    metadata: Mapping[str, Any] | None = None,
    reason_codes: Sequence[str] | None = None,
) -> str | None:
    direct = str((metadata or {}).get("strategy_leg") or "").strip().lower()
    if direct:
        return direct
    for reason in reason_codes or ():
        text = str(reason)
        if text.startswith("strategy_leg:"):
            parsed = text.split(":", 1)[1].strip().lower()
            return parsed or None
    return None


def protective_working_type(
    config: AppConfig,
    *,
    order_kind: str,
    strategy_leg: str | None,
) -> str:
    kind = str(order_kind).strip().upper()
    if kind not in {"STOP", "TAKE_PROFIT"}:
        raise ValueError(f"unsupported protective order kind: {order_kind}")
    normalized_leg = str(strategy_leg or "").strip().lower()
    prefix = "BFA_MICRO_GRID" if normalized_leg in MICRO_STRATEGY_LEGS else "BFA_PROTECTIVE"
    suffix = "STOP_WORKING_TYPE" if kind == "STOP" else "TARGET_WORKING_TYPE"
    working_type = config.get(f"{prefix}_{suffix}").strip().upper()
    if working_type not in SUPPORTED_WORKING_TYPES:
        raise ValueError(
            f"{prefix}_{suffix} must be MARK_PRICE or CONTRACT_PRICE"
        )
    return working_type
