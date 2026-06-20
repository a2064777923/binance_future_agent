"""Adaptive guards derived from forward-paper evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Iterable, Mapping

from bfa.event_store.migrations import migrate


@dataclass(frozen=True)
class ForwardPaperGuardConfig:
    enabled: bool = True
    variant: str = "quant_setup_selective"
    interval: str = "5m"
    since: str | None = None
    min_total_outcomes: int = 30
    min_symbol_outcomes: int = 3
    symbol_min_loss_usdt: float = 0.5
    symbol_max_win_rate: float = 0.3
    min_side_outcomes: int = 20
    side_min_loss_usdt: float = 2.0
    side_max_win_rate: float = 0.3
    min_factor_outcomes: int = 30
    factor_min_loss_usdt: float = 3.0
    factor_max_win_rate: float = 0.25


@dataclass(frozen=True)
class GuardGroupStats:
    name: str
    outcome_count: int
    win_rate: float
    total_net_pnl_usdt: float
    average_net_pnl_usdt: float
    loss_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome_count": self.outcome_count,
            "win_rate": self.win_rate,
            "total_net_pnl_usdt": self.total_net_pnl_usdt,
            "average_net_pnl_usdt": self.average_net_pnl_usdt,
            "loss_count": self.loss_count,
        }


@dataclass(frozen=True)
class ForwardPaperGuard:
    status: str
    enabled: bool
    reasons: list[str]
    variant: str
    interval: str
    summary: dict[str, Any] = field(default_factory=dict)
    symbol_blocks: dict[str, GuardGroupStats] = field(default_factory=dict)
    side_blocks: dict[str, GuardGroupStats] = field(default_factory=dict)
    factor_blocks: dict[str, GuardGroupStats] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.enabled and self.status == "active"

    def blocks_symbol(self, symbol: str) -> bool:
        return symbol.upper() in self.symbol_blocks

    def symbol_reasons(self, symbol: str) -> list[str]:
        normalized = symbol.upper()
        if normalized not in self.symbol_blocks:
            return []
        return [f"forward_paper_symbol_block:{normalized}"]

    def setup_profile_overrides(self) -> dict[str, Any]:
        if not self.active:
            return {}
        overrides: dict[str, Any] = {}
        if self.side_blocks:
            overrides["disabled_sides"] = sorted(self.side_blocks)
        if self.factor_blocks:
            overrides["blocked_factor_reasons"] = sorted(self.factor_blocks)
        return overrides

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_forward_paper_guard_v1",
            "status": self.status,
            "enabled": self.enabled,
            "reasons": list(self.reasons),
            "variant": self.variant,
            "interval": self.interval,
            "summary": dict(self.summary),
            "symbol_blocks": {key: value.to_dict() for key, value in self.symbol_blocks.items()},
            "side_blocks": {key: value.to_dict() for key, value in self.side_blocks.items()},
            "factor_blocks": {key: value.to_dict() for key, value in self.factor_blocks.items()},
        }


def guard_config_from_app(config) -> ForwardPaperGuardConfig:
    return ForwardPaperGuardConfig(
        enabled=_truthy(config.get("BFA_FORWARD_PAPER_GUARD_ENABLED")),
        variant=config.get("BFA_FORWARD_PAPER_GUARD_VARIANT") or "quant_setup_selective",
        interval=config.get("BFA_FORWARD_PAPER_GUARD_INTERVAL") or "5m",
        since=config.get("BFA_FORWARD_PAPER_GUARD_SINCE") or None,
        min_total_outcomes=int(config.get("BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES")),
        min_symbol_outcomes=int(config.get("BFA_FORWARD_PAPER_GUARD_MIN_SYMBOL_OUTCOMES")),
        symbol_min_loss_usdt=float(config.get("BFA_FORWARD_PAPER_GUARD_SYMBOL_MIN_LOSS_USDT")),
        symbol_max_win_rate=float(config.get("BFA_FORWARD_PAPER_GUARD_SYMBOL_MAX_WIN_RATE")),
        min_side_outcomes=int(config.get("BFA_FORWARD_PAPER_GUARD_MIN_SIDE_OUTCOMES")),
        side_min_loss_usdt=float(config.get("BFA_FORWARD_PAPER_GUARD_SIDE_MIN_LOSS_USDT")),
        side_max_win_rate=float(config.get("BFA_FORWARD_PAPER_GUARD_SIDE_MAX_WIN_RATE")),
        min_factor_outcomes=int(config.get("BFA_FORWARD_PAPER_GUARD_MIN_FACTOR_OUTCOMES")),
        factor_min_loss_usdt=float(config.get("BFA_FORWARD_PAPER_GUARD_FACTOR_MIN_LOSS_USDT")),
        factor_max_win_rate=float(config.get("BFA_FORWARD_PAPER_GUARD_FACTOR_MAX_WIN_RATE")),
    )


def build_forward_paper_guard(
    connection: sqlite3.Connection,
    config: ForwardPaperGuardConfig,
) -> ForwardPaperGuard:
    if not config.enabled:
        return _guard(config, status="disabled", reasons=["guard_disabled"])

    migrate(connection)
    signals = _load_signals(connection, config)
    outcomes = _load_outcomes(connection, config, signal_ids=set(signals))
    joined = [_join_outcome(outcome, signals.get(_int_or_zero(outcome.get("signal_event_id")))) for outcome in outcomes]
    summary = _summary(signals, joined)
    if summary["outcome_count"] < config.min_total_outcomes:
        return _guard(
            config,
            status="insufficient_evidence",
            reasons=["paper_guard_min_total_outcomes_not_met"],
            summary=summary,
        )

    symbol_groups = _group(joined, "symbol")
    side_groups = _group(joined, "side")
    factor_groups = _group_tokens(joined, "factor_reasons")
    symbol_blocks = {
        name: stats
        for name, stats in symbol_groups.items()
        if _loss_block(
            stats,
            min_outcomes=config.min_symbol_outcomes,
            min_loss_usdt=config.symbol_min_loss_usdt,
            max_win_rate=config.symbol_max_win_rate,
        )
    }
    side_blocks = {
        name: stats
        for name, stats in side_groups.items()
        if _loss_block(
            stats,
            min_outcomes=config.min_side_outcomes,
            min_loss_usdt=config.side_min_loss_usdt,
            max_win_rate=config.side_max_win_rate,
        )
    }
    factor_blocks = {
        name: stats
        for name, stats in factor_groups.items()
        if _loss_block(
            stats,
            min_outcomes=config.min_factor_outcomes,
            min_loss_usdt=config.factor_min_loss_usdt,
            max_win_rate=config.factor_max_win_rate,
        )
    }
    if not symbol_blocks and not side_blocks and not factor_blocks:
        return _guard(config, status="active", reasons=["no_guard_blocks"], summary=summary)
    reasons = []
    if symbol_blocks:
        reasons.append("symbol_blocks_active")
    if side_blocks:
        reasons.append("side_blocks_active")
    if factor_blocks:
        reasons.append("factor_blocks_active")
    return _guard(
        config,
        status="active",
        reasons=reasons,
        summary=summary,
        symbol_blocks=symbol_blocks,
        side_blocks=side_blocks,
        factor_blocks=factor_blocks,
    )


def merge_guard_profile(profile: Mapping[str, Any] | None, guard: ForwardPaperGuard | None) -> Mapping[str, Any] | None:
    if guard is None or not guard.active:
        return profile
    overrides = guard.setup_profile_overrides()
    if not overrides:
        return profile
    merged = dict(profile or {})
    base_name = str(merged.get("name") or "standard")
    merged["name"] = f"{base_name}+paper_guard"
    merged["disabled_sides"] = _merged_sequence(merged.get("disabled_sides"), overrides.get("disabled_sides"))
    merged["blocked_factor_reasons"] = _merged_sequence(
        merged.get("blocked_factor_reasons"),
        overrides.get("blocked_factor_reasons"),
    )
    return merged


def _guard(
    config: ForwardPaperGuardConfig,
    *,
    status: str,
    reasons: list[str],
    summary: dict[str, Any] | None = None,
    symbol_blocks: dict[str, GuardGroupStats] | None = None,
    side_blocks: dict[str, GuardGroupStats] | None = None,
    factor_blocks: dict[str, GuardGroupStats] | None = None,
) -> ForwardPaperGuard:
    return ForwardPaperGuard(
        status=status,
        enabled=config.enabled,
        reasons=reasons,
        variant=config.variant,
        interval=config.interval,
        summary=summary or {},
        symbol_blocks=symbol_blocks or {},
        side_blocks=side_blocks or {},
        factor_blocks=factor_blocks or {},
    )


def _load_signals(connection: sqlite3.Connection, config: ForwardPaperGuardConfig) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM paper_signals
        WHERE json_extract(payload_json, '$.interval') = ?
          AND json_extract(payload_json, '$.variant') = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (config.interval, config.variant),
    ).fetchall()
    signals: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        opened_at = str(payload.get("opened_at") or row["occurred_at"])
        if config.since and opened_at < config.since:
            continue
        event_id = int(row["event_id"])
        payload["event_id"] = event_id
        payload["symbol"] = str(payload.get("symbol") or row["symbol"] or "").upper()
        signals[event_id] = payload
    return signals


def _load_outcomes(
    connection: sqlite3.Connection,
    config: ForwardPaperGuardConfig,
    *,
    signal_ids: set[int],
) -> list[dict[str, Any]]:
    if not signal_ids:
        return []
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM paper_outcomes
        WHERE json_extract(payload_json, '$.interval') = ?
          AND json_extract(payload_json, '$.variant') = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (config.interval, config.variant),
    ).fetchall()
    outcomes: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        signal_event_id = _int_or_zero(payload.get("signal_event_id"))
        if signal_event_id not in signal_ids:
            continue
        payload["event_id"] = int(row["event_id"])
        payload["signal_event_id"] = signal_event_id
        payload["symbol"] = str(payload.get("symbol") or row["symbol"] or "").upper()
        outcomes.append(payload)
    return outcomes


def _join_outcome(outcome: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
    setup = _mapping((signal or {}).get("setup"))
    factor_scores = [_mapping(item) for item in _list(setup.get("factor_scores")) if isinstance(item, dict)]
    factor_reasons = sorted({str(reason) for factor in factor_scores for reason in _list(factor.get("reasons")) if str(reason)})
    return {
        "symbol": str(outcome.get("symbol") or (signal or {}).get("symbol") or "").upper(),
        "side": str(outcome.get("side") or (signal or {}).get("side") or "unknown").lower(),
        "factor_reasons": factor_reasons,
        "net_pnl_usdt": _float_or_zero(outcome.get("net_pnl_usdt")),
    }


def _summary(signals: dict[int, dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in outcomes]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    return {
        "signal_count": len(signals),
        "outcome_count": len(outcomes),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": _ratio(len(wins), len(outcomes)),
        "total_net_pnl_usdt": round(sum(pnl_values), 8),
        "gross_loss_abs_usdt": round(abs(sum(losses)), 8),
    }


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, GuardGroupStats]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return {name: _group_stats(name, values) for name, values in grouped.items()}


def _group_tokens(rows: list[dict[str, Any]], key: str) -> dict[str, GuardGroupStats]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for value in [str(item) for item in _list(row.get(key)) if str(item)]:
            grouped[value].append(row)
    return {name: _group_stats(name, values) for name, values in grouped.items()}


def _group_stats(name: str, rows: list[dict[str, Any]]) -> GuardGroupStats:
    pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in rows]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    return GuardGroupStats(
        name=name,
        outcome_count=len(rows),
        win_rate=_ratio(len(wins), len(rows)),
        total_net_pnl_usdt=round(sum(pnl_values), 8),
        average_net_pnl_usdt=round(_ratio(sum(pnl_values), len(rows)), 8),
        loss_count=len(losses),
    )


def _loss_block(stats: GuardGroupStats, *, min_outcomes: int, min_loss_usdt: float, max_win_rate: float) -> bool:
    return (
        stats.outcome_count >= min_outcomes
        and stats.total_net_pnl_usdt <= -abs(min_loss_usdt)
        and stats.win_rate <= max_win_rate
    )


def _merged_sequence(left: Any, right: Any) -> list[str]:
    values: list[str] = []
    for item in [*_sequence(left), *_sequence(right)]:
        normalized = str(item)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 8)


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
