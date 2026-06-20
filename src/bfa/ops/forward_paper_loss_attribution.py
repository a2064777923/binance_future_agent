"""Read-only loss attribution for forward-paper evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Iterable

from bfa.event_store.migrations import connect, migrate


@dataclass(frozen=True)
class ForwardPaperLossAttributionReport:
    status: str
    live_resume_allowed: bool
    reasons: list[str]
    variant: str
    interval: str
    filters: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    worst_groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recalibration_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_forward_paper_loss_attribution_v1",
            "status": self.status,
            "live_resume_allowed": self.live_resume_allowed,
            "reasons": list(self.reasons),
            "variant": self.variant,
            "interval": self.interval,
            "filters": dict(self.filters),
            "summary": dict(self.summary),
            "worst_groups": {key: [dict(item) for item in value] for key, value in self.worst_groups.items()},
            "recalibration_candidates": [dict(item) for item in self.recalibration_candidates],
        }


def build_forward_paper_loss_attribution_report(
    db_path: str,
    *,
    variant: str = "quant_setup_selective",
    interval: str = "5m",
    since: str | None = None,
    min_group_outcomes: int = 1,
    worst_limit: int = 8,
) -> ForwardPaperLossAttributionReport:
    filters = {
        "since": since,
        "min_group_outcomes": min_group_outcomes,
        "worst_limit": worst_limit,
    }
    connection = connect(db_path)
    try:
        migrate(connection)
        signals = _load_signals(connection, variant=variant, interval=interval, since=since)
        outcomes = _load_outcomes(connection, variant=variant, interval=interval, signal_ids=set(signals))
    finally:
        connection.close()

    joined = [_join_outcome(outcome, signals.get(_int_or_zero(outcome.get("signal_event_id")))) for outcome in outcomes]
    summary = _summary(signals, joined)
    if not signals:
        return _report(
            variant=variant,
            interval=interval,
            filters=filters,
            summary=summary,
            status="no_paper_evidence",
            reasons=["paper_signals_missing"],
        )
    if not joined:
        return _report(
            variant=variant,
            interval=interval,
            filters=filters,
            summary=summary,
            status="no_settled_outcomes",
            reasons=["paper_outcomes_missing"],
        )

    worst_groups = {
        "symbols": _group(joined, "symbol", min_outcomes=min_group_outcomes, limit=worst_limit),
        "sides": _group(joined, "side", min_outcomes=min_group_outcomes, limit=worst_limit),
        "exit_reasons": _group(joined, "exit_reason", min_outcomes=min_group_outcomes, limit=worst_limit),
        "setup_reasons": _group_tokens(joined, "setup_reasons", min_outcomes=min_group_outcomes, limit=worst_limit),
        "setup_warnings": _group_tokens(joined, "setup_warnings", min_outcomes=min_group_outcomes, limit=worst_limit),
        "factor_reasons": _group_tokens(joined, "factor_reasons", min_outcomes=min_group_outcomes, limit=worst_limit),
        "factor_names": _group_tokens(joined, "negative_factor_names", min_outcomes=min_group_outcomes, limit=worst_limit),
    }
    candidates = _recalibration_candidates(worst_groups)
    return _report(
        variant=variant,
        interval=interval,
        filters=filters,
        summary=summary,
        status="loss_attribution_ready",
        reasons=["loss_attribution_ready"],
        worst_groups=worst_groups,
        recalibration_candidates=candidates,
    )


def _report(
    *,
    variant: str,
    interval: str,
    filters: dict[str, Any],
    summary: dict[str, Any],
    status: str,
    reasons: list[str],
    worst_groups: dict[str, list[dict[str, Any]]] | None = None,
    recalibration_candidates: list[dict[str, Any]] | None = None,
) -> ForwardPaperLossAttributionReport:
    return ForwardPaperLossAttributionReport(
        status=status,
        live_resume_allowed=False,
        reasons=reasons,
        variant=variant,
        interval=interval,
        filters=filters,
        summary=summary,
        worst_groups=worst_groups or {},
        recalibration_candidates=recalibration_candidates or [],
    )


def _load_signals(
    connection: sqlite3.Connection,
    *,
    variant: str,
    interval: str,
    since: str | None,
) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM paper_signals
        WHERE json_extract(payload_json, '$.interval') = ?
          AND json_extract(payload_json, '$.variant') = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (interval, variant),
    ).fetchall()
    signals: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        opened_at = str(payload.get("opened_at") or row["occurred_at"])
        if since and opened_at < since:
            continue
        event_id = int(row["event_id"])
        payload["event_id"] = event_id
        payload["symbol"] = str(payload.get("symbol") or row["symbol"] or "").upper()
        signals[event_id] = payload
    return signals


def _load_outcomes(
    connection: sqlite3.Connection,
    *,
    variant: str,
    interval: str,
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
        (interval, variant),
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
        payload["closed_at"] = str(payload.get("closed_at") or row["occurred_at"])
        outcomes.append(payload)
    return outcomes


def _join_outcome(outcome: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
    setup = _mapping((signal or {}).get("setup"))
    factor_scores = [_mapping(item) for item in _list(setup.get("factor_scores")) if isinstance(item, dict)]
    factor_reasons = sorted({str(reason) for factor in factor_scores for reason in _list(factor.get("reasons")) if str(reason)})
    negative_factor_names = sorted(
        {
            str(factor.get("name"))
            for factor in factor_scores
            if _float_or_zero(factor.get("weighted_score")) < 0 and str(factor.get("name"))
        }
    )
    return {
        "symbol": str(outcome.get("symbol") or (signal or {}).get("symbol") or "").upper(),
        "side": str(outcome.get("side") or (signal or {}).get("side") or "unknown").lower(),
        "exit_reason": str(outcome.get("exit_reason") or "unknown"),
        "net_pnl_usdt": _float_or_zero(outcome.get("net_pnl_usdt")),
        "signal_event_id": _int_or_zero(outcome.get("signal_event_id")),
        "opened_at": str(outcome.get("opened_at") or (signal or {}).get("opened_at") or ""),
        "closed_at": str(outcome.get("closed_at") or ""),
        "setup_reasons": [str(item) for item in _list(setup.get("reasons")) if str(item)],
        "setup_warnings": [str(item) for item in _list(setup.get("warnings")) if str(item)],
        "factor_reasons": factor_reasons,
        "negative_factor_names": negative_factor_names,
        "edge_score": _float_or_none(setup.get("edge_score")),
        "confidence": _float_or_none(setup.get("confidence")),
        "risk_reward_ratio": _float_or_none(setup.get("risk_reward_ratio")),
    }


def _summary(signals: dict[int, dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in outcomes]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    return {
        "signal_count": len(signals),
        "outcome_count": len(outcomes),
        "matched_outcome_count": sum(1 for item in outcomes if item.get("signal_event_id") in signals),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": _ratio(len(wins), len(outcomes)),
        "total_net_pnl_usdt": round(sum(pnl_values), 8),
        "average_net_pnl_usdt": round(_ratio(sum(pnl_values), len(outcomes)), 8),
        "gross_loss_abs_usdt": round(abs(sum(losses)), 8),
    }


def _group(
    rows: list[dict[str, Any]],
    key: str,
    *,
    min_outcomes: int,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return _rank_groups(groups.items(), min_outcomes=min_outcomes, limit=limit)


def _group_tokens(
    rows: list[dict[str, Any]],
    key: str,
    *,
    min_outcomes: int,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        values = [str(item) for item in _list(row.get(key)) if str(item)]
        for value in values or ["<none>"]:
            groups.setdefault(value, []).append(row)
    return _rank_groups(groups.items(), min_outcomes=min_outcomes, limit=limit)


def _rank_groups(
    items: Iterable[tuple[str, list[dict[str, Any]]]],
    *,
    min_outcomes: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows = []
    for name, group_rows in items:
        if len(group_rows) < min_outcomes:
            continue
        pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in group_rows]
        losses = [value for value in pnl_values if value < 0]
        rows.append(
            {
                "name": name,
                "outcome_count": len(group_rows),
                "win_rate": _ratio(len([value for value in pnl_values if value > 0]), len(pnl_values)),
                "total_net_pnl_usdt": round(sum(pnl_values), 8),
                "average_net_pnl_usdt": round(_ratio(sum(pnl_values), len(pnl_values)), 8),
                "gross_loss_abs_usdt": round(abs(sum(losses)), 8),
                "loss_count": len(losses),
            }
        )
    return sorted(rows, key=lambda item: (float(item["total_net_pnl_usdt"]), -int(item["outcome_count"]), str(item["name"])))[: max(0, limit)]


def _recalibration_candidates(worst_groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    mapping = {
        "symbols": "quarantine_or_reduce_symbol",
        "sides": "tighten_side_filter",
        "exit_reasons": "inspect_exit_geometry",
        "setup_reasons": "tighten_setup_reason",
        "setup_warnings": "block_or_penalize_warning",
        "factor_reasons": "tighten_factor_reason",
        "factor_names": "raise_or_reweight_factor",
    }
    for group_name, action in mapping.items():
        for row in worst_groups.get(group_name, [])[:3]:
            if float(row["total_net_pnl_usdt"]) >= 0:
                continue
            candidates.append(
                {
                    "action": action,
                    "group": group_name,
                    "name": row["name"],
                    "outcome_count": row["outcome_count"],
                    "total_net_pnl_usdt": row["total_net_pnl_usdt"],
                    "win_rate": row["win_rate"],
                }
            )
    return candidates


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 8)


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
