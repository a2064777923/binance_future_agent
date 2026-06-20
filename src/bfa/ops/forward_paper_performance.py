"""Read-only performance gate for forward-paper evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any

from bfa.event_store.migrations import connect, migrate


@dataclass(frozen=True)
class ForwardPaperPerformanceReport:
    status: str
    paper_promotion_allowed: bool
    live_resume_allowed: bool
    reasons: list[str]
    variant: str
    interval: str
    thresholds: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    by_symbol: list[dict[str, Any]] = field(default_factory=list)
    latest_outcomes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_forward_paper_performance_v1",
            "status": self.status,
            "paper_promotion_allowed": self.paper_promotion_allowed,
            "live_resume_allowed": self.live_resume_allowed,
            "reasons": list(self.reasons),
            "variant": self.variant,
            "interval": self.interval,
            "thresholds": dict(self.thresholds),
            "summary": dict(self.summary),
            "by_symbol": [dict(item) for item in self.by_symbol],
            "latest_outcomes": [dict(item) for item in self.latest_outcomes],
        }


def build_forward_paper_performance_report(
    db_path: str,
    *,
    variant: str = "quant_setup_selective",
    interval: str = "5m",
    since: str | None = None,
    min_outcomes: int = 20,
    min_win_rate: float = 0.5,
    min_net_pnl_usdt: float = 0.0,
    max_worst_drawdown_usdt: float | None = 1.5,
    latest_limit: int = 10,
) -> ForwardPaperPerformanceReport:
    thresholds = {
        "since": since,
        "min_outcomes": min_outcomes,
        "min_win_rate": min_win_rate,
        "min_net_pnl_usdt": min_net_pnl_usdt,
        "max_worst_drawdown_usdt": max_worst_drawdown_usdt,
    }
    connection = connect(db_path)
    try:
        migrate(connection)
        signals = _load_signals(connection, variant=variant, interval=interval, since=since)
        outcomes = _load_outcomes(connection, variant=variant, interval=interval, signal_ids={item["event_id"] for item in signals})
    finally:
        connection.close()

    summary = _summary(signals, outcomes)
    reasons = _reasons(
        summary,
        min_outcomes=min_outcomes,
        min_win_rate=min_win_rate,
        min_net_pnl_usdt=min_net_pnl_usdt,
        max_worst_drawdown_usdt=max_worst_drawdown_usdt,
    )
    status = _status(reasons)
    allowed = status == "paper_evidence_promising"
    return ForwardPaperPerformanceReport(
        status=status,
        paper_promotion_allowed=allowed,
        live_resume_allowed=False,
        reasons=reasons or ["paper_thresholds_passed"],
        variant=variant,
        interval=interval,
        thresholds=thresholds,
        summary=summary,
        by_symbol=_by_symbol(outcomes),
        latest_outcomes=_latest_outcomes(outcomes, latest_limit=latest_limit),
    )


def _load_signals(
    connection: sqlite3.Connection,
    *,
    variant: str,
    interval: str,
    since: str | None,
) -> list[dict[str, Any]]:
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
    signals: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        opened_at = str(payload.get("opened_at") or row["occurred_at"])
        if since and opened_at < since:
            continue
        payload["event_id"] = int(row["event_id"])
        payload["symbol"] = str(payload.get("symbol") or row["symbol"] or "").upper()
        signals.append(payload)
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


def _summary(signals: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    outcome_signal_ids = {_int_or_zero(item.get("signal_event_id")) for item in outcomes}
    signal_ids = {_int_or_zero(item.get("event_id")) for item in signals}
    pnl_values = [_float_or_zero(item.get("net_pnl_usdt")) for item in outcomes]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    flats = [value for value in pnl_values if value == 0]
    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    exit_counts = Counter(str(item.get("exit_reason") or "unknown") for item in outcomes)
    return {
        "signal_count": len(signals),
        "outcome_count": len(outcomes),
        "open_signal_count": len(signal_ids - outcome_signal_ids),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate": _ratio(len(wins), len(outcomes)),
        "total_net_pnl_usdt": round(sum(pnl_values), 8),
        "average_net_pnl_usdt": round(_ratio(sum(pnl_values), len(outcomes)), 8),
        "gross_profit_usdt": round(gross_profit, 8),
        "gross_loss_abs_usdt": round(gross_loss_abs, 8),
        "profit_factor": _profit_factor(gross_profit, gross_loss_abs),
        "worst_drawdown_usdt": _worst_drawdown(outcomes),
        "exit_reason_counts": dict(sorted(exit_counts.items())),
    }


def _reasons(
    summary: dict[str, Any],
    *,
    min_outcomes: int,
    min_win_rate: float,
    min_net_pnl_usdt: float,
    max_worst_drawdown_usdt: float | None,
) -> list[str]:
    reasons: list[str] = []
    if int(summary["signal_count"]) <= 0:
        reasons.append("paper_signals_missing")
        return reasons
    if int(summary["outcome_count"]) < min_outcomes:
        reasons.append("paper_outcome_count_below_min")
    if float(summary["total_net_pnl_usdt"]) <= min_net_pnl_usdt:
        reasons.append("paper_total_net_pnl_not_above_min")
    if float(summary["win_rate"]) < min_win_rate:
        reasons.append("paper_win_rate_below_min")
    if max_worst_drawdown_usdt is not None and float(summary["worst_drawdown_usdt"]) >= max_worst_drawdown_usdt:
        reasons.append("paper_worst_drawdown_exceeds_cap")
    return reasons


def _status(reasons: list[str]) -> str:
    if "paper_signals_missing" in reasons:
        return "no_paper_evidence"
    if "paper_outcome_count_below_min" in reasons:
        return "insufficient_paper_evidence"
    if reasons:
        return "keep_live_paused"
    return "paper_evidence_promising"


def _by_symbol(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for outcome in outcomes:
        grouped.setdefault(str(outcome.get("symbol") or "").upper(), []).append(_float_or_zero(outcome.get("net_pnl_usdt")))
    rows = []
    for symbol, values in grouped.items():
        rows.append(
            {
                "symbol": symbol,
                "outcome_count": len(values),
                "win_rate": _ratio(len([value for value in values if value > 0]), len(values)),
                "total_net_pnl_usdt": round(sum(values), 8),
            }
        )
    return sorted(rows, key=lambda item: (float(item["total_net_pnl_usdt"]), str(item["symbol"])), reverse=True)


def _latest_outcomes(outcomes: list[dict[str, Any]], *, latest_limit: int) -> list[dict[str, Any]]:
    rows = sorted(outcomes, key=lambda item: (str(item.get("closed_at") or ""), int(item.get("event_id") or 0)), reverse=True)
    return [
        {
            "symbol": str(item.get("symbol") or ""),
            "side": str(item.get("side") or ""),
            "opened_at": str(item.get("opened_at") or ""),
            "closed_at": str(item.get("closed_at") or ""),
            "net_pnl_usdt": _float_or_zero(item.get("net_pnl_usdt")),
            "exit_reason": str(item.get("exit_reason") or ""),
        }
        for item in rows[: max(0, latest_limit)]
    ]


def _worst_drawdown(outcomes: list[dict[str, Any]]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for item in sorted(outcomes, key=lambda row: (str(row.get("closed_at") or ""), int(row.get("event_id") or 0))):
        cumulative += _float_or_zero(item.get("net_pnl_usdt"))
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return round(worst, 8)


def _profit_factor(gross_profit: float, gross_loss_abs: float) -> float | None:
    if gross_loss_abs == 0:
        return None
    return round(gross_profit / gross_loss_abs, 8)


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
