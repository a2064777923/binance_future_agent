"""Read-only gate for promoting a backtested strategy toward live use."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


PROMOTED_VERDICT = "candidate_for_forward_paper"
ALL_INTERVALS_SCOPE = "all-intervals"
SELECTED_INTERVALS_SCOPE = "selected-intervals"


@dataclass(frozen=True)
class PromotionCellCheck:
    interval: str
    variant: str
    verdict: str
    trade_count: int
    net_pnl_usdt: float
    positive_window_rate: float
    worst_drawdown_usdt: float
    max_daily_loss_usdt: float | None
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "variant": self.variant,
            "verdict": self.verdict,
            "trade_count": self.trade_count,
            "net_pnl_usdt": self.net_pnl_usdt,
            "positive_window_rate": self.positive_window_rate,
            "worst_drawdown_usdt": self.worst_drawdown_usdt,
            "max_daily_loss_usdt": self.max_daily_loss_usdt,
            "passed": self.passed,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class StrategyPromotionCheckReport:
    status: str
    promotion_allowed: bool
    reasons: list[str]
    matrix_report_path: str
    variant: str
    scope: str = ALL_INTERVALS_SCOPE
    intervals: list[str] = field(default_factory=list)
    live_resume_allowed: bool = False
    matrix_overall: str | None = None
    variant_summary: dict[str, Any] = field(default_factory=dict)
    selected_summary: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    cell_checks: list[PromotionCellCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "promotion_allowed": self.promotion_allowed,
            "reasons": list(self.reasons),
            "matrix_report_path": self.matrix_report_path,
            "variant": self.variant,
            "scope": self.scope,
            "intervals": list(self.intervals),
            "live_resume_allowed": self.live_resume_allowed,
            "matrix_overall": self.matrix_overall,
            "variant_summary": dict(self.variant_summary),
            "selected_summary": dict(self.selected_summary),
            "thresholds": dict(self.thresholds),
            "cell_checks": [cell.to_dict() for cell in self.cell_checks],
        }


def build_strategy_promotion_check_report(
    matrix_report_path: str | Path,
    *,
    variant: str = "quant_setup",
    min_trade_count: int = 5,
    min_positive_window_rate: float = 0.5,
    max_worst_drawdown_usdt: float | None = None,
    intervals: Sequence[str] | None = None,
    scope: str = ALL_INTERVALS_SCOPE,
) -> StrategyPromotionCheckReport:
    path = Path(matrix_report_path)
    normalized_scope = _normalize_scope(scope)
    selected_intervals = _normalize_intervals(intervals)
    thresholds = {
        "min_trade_count": min_trade_count,
        "min_positive_window_rate": min_positive_window_rate,
        "max_worst_drawdown_usdt": max_worst_drawdown_usdt,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _report(
            path,
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            status="invalid_report",
            reasons=["matrix_report_missing"],
            thresholds=thresholds,
        )
    except json.JSONDecodeError:
        return _report(
            path,
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            status="invalid_report",
            reasons=["matrix_report_invalid_json"],
            thresholds=thresholds,
        )

    if not isinstance(payload, Mapping) or payload.get("schema") != "bfa_hot_backtest_matrix_v1":
        return _report(
            path,
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            status="invalid_report",
            reasons=["matrix_report_schema_invalid"],
            thresholds=thresholds,
        )

    promotion = _mapping(payload.get("promotion"))
    overall = _optional_str(promotion.get("overall"))
    variant_summary = _mapping(_mapping(promotion.get("variants")).get(variant))
    cells = [
        cell
        for cell in _list(promotion.get("cells"))
        if isinstance(cell, Mapping) and str(cell.get("variant") or "") == variant
    ]
    cells_for_checks = _filter_cells_by_scope(cells, selected_intervals, normalized_scope)
    resolved_drawdown_cap = (
        max_worst_drawdown_usdt
        if max_worst_drawdown_usdt is not None
        else _drawdown_cap_from_cells(cells_for_checks)
    )
    thresholds["max_worst_drawdown_usdt"] = resolved_drawdown_cap

    reasons: list[str] = []
    if not variant_summary:
        reasons.append("variant_summary_missing")
    if not cells:
        reasons.append("variant_cells_missing")
    if selected_intervals and not cells_for_checks:
        reasons.append("selected_interval_cells_missing")
    if normalized_scope == SELECTED_INTERVALS_SCOPE and not selected_intervals:
        reasons.append("selected_intervals_required")

    selected_summary = _selected_summary(cells_for_checks)
    if normalized_scope == ALL_INTERVALS_SCOPE:
        variant_verdict = _optional_str(variant_summary.get("verdict"))
        if variant_verdict != PROMOTED_VERDICT:
            reasons.append("variant_not_promoted")
        if _float_or_zero(variant_summary.get("total_net_pnl_usdt")) <= 0:
            reasons.append("variant_total_net_pnl_not_positive")
        if resolved_drawdown_cap is not None and _float_or_zero(variant_summary.get("worst_drawdown_usdt")) >= resolved_drawdown_cap:
            reasons.append("variant_worst_drawdown_exceeds_cap")
    else:
        if _float_or_zero(selected_summary.get("total_net_pnl_usdt")) <= 0:
            reasons.append("selected_intervals_total_net_pnl_not_positive")
        if (
            resolved_drawdown_cap is not None
            and _float_or_zero(selected_summary.get("worst_drawdown_usdt")) >= resolved_drawdown_cap
        ):
            reasons.append("selected_intervals_worst_drawdown_exceeds_cap")

    cell_checks = [
        _cell_check(
            cell,
            min_trade_count=min_trade_count,
            min_positive_window_rate=min_positive_window_rate,
            max_worst_drawdown_usdt=resolved_drawdown_cap,
        )
        for cell in cells_for_checks
    ]
    for cell in cell_checks:
        reasons.extend(f"{cell.interval}:{reason}" for reason in cell.reasons)

    reasons = _dedupe(reasons)
    allowed = not reasons
    status = _success_status(normalized_scope) if allowed else "keep_live_paused"
    success_reasons = _success_reasons(normalized_scope)
    return StrategyPromotionCheckReport(
        status=status,
        promotion_allowed=allowed,
        reasons=reasons or success_reasons,
        matrix_report_path=str(path),
        variant=variant,
        scope=normalized_scope,
        intervals=selected_intervals,
        live_resume_allowed=allowed and normalized_scope == ALL_INTERVALS_SCOPE,
        matrix_overall=overall,
        variant_summary=dict(variant_summary),
        selected_summary=selected_summary,
        thresholds=thresholds,
        cell_checks=cell_checks,
    )


def _cell_check(
    cell: Mapping[str, Any],
    *,
    min_trade_count: int,
    min_positive_window_rate: float,
    max_worst_drawdown_usdt: float | None,
) -> PromotionCellCheck:
    reasons: list[str] = []
    verdict = str(cell.get("verdict") or "")
    trade_count = _int_or_zero(cell.get("trade_count"))
    net_pnl = _float_or_zero(cell.get("net_pnl_usdt"))
    positive_rate = _float_or_zero(cell.get("positive_window_rate"))
    drawdown = _float_or_zero(cell.get("worst_drawdown_usdt"))
    max_daily_loss = _float_or_none(cell.get("max_daily_loss_usdt"))
    if verdict != PROMOTED_VERDICT:
        reasons.append("cell_not_promoted")
    if trade_count < min_trade_count:
        reasons.append("cell_trade_count_below_min")
    if net_pnl <= 0:
        reasons.append("cell_net_pnl_not_positive")
    if positive_rate < min_positive_window_rate:
        reasons.append("cell_positive_window_rate_below_min")
    if max_worst_drawdown_usdt is not None and drawdown >= max_worst_drawdown_usdt:
        reasons.append("cell_worst_drawdown_exceeds_cap")
    if max_daily_loss is not None and drawdown >= max_daily_loss:
        reasons.append("cell_worst_drawdown_exceeds_matrix_daily_loss")
    return PromotionCellCheck(
        interval=str(cell.get("interval") or ""),
        variant=str(cell.get("variant") or ""),
        verdict=verdict,
        trade_count=trade_count,
        net_pnl_usdt=net_pnl,
        positive_window_rate=positive_rate,
        worst_drawdown_usdt=drawdown,
        max_daily_loss_usdt=max_daily_loss,
        reasons=_dedupe(reasons),
    )


def _drawdown_cap_from_cells(cells: list[Mapping[str, Any]]) -> float | None:
    values = [_float_or_none(cell.get("max_daily_loss_usdt")) for cell in cells]
    parsed = [value for value in values if value is not None]
    return min(parsed) if parsed else None


def _filter_cells_by_scope(
    cells: list[Mapping[str, Any]],
    selected_intervals: list[str],
    scope: str,
) -> list[Mapping[str, Any]]:
    if scope == ALL_INTERVALS_SCOPE or not selected_intervals:
        return list(cells)
    selected = set(selected_intervals)
    return [cell for cell in cells if str(cell.get("interval") or "").lower() in selected]


def _selected_summary(cells: list[Mapping[str, Any]]) -> dict[str, Any]:
    total_net = sum(_float_or_zero(cell.get("net_pnl_usdt")) for cell in cells)
    worst_drawdown = max((_float_or_zero(cell.get("worst_drawdown_usdt")) for cell in cells), default=0.0)
    trade_count = sum(_int_or_zero(cell.get("trade_count")) for cell in cells)
    rates = [_float_or_zero(cell.get("positive_window_rate")) for cell in cells]
    positive_window_rate = sum(rates) / len(rates) if rates else 0.0
    return {
        "interval_count": len(cells),
        "intervals": [str(cell.get("interval") or "") for cell in cells],
        "trade_count": trade_count,
        "total_net_pnl_usdt": round(total_net, 8),
        "worst_drawdown_usdt": round(worst_drawdown, 8),
        "positive_window_rate": round(positive_window_rate, 8),
    }


def _normalize_scope(scope: str) -> str:
    if scope == SELECTED_INTERVALS_SCOPE:
        return SELECTED_INTERVALS_SCOPE
    return ALL_INTERVALS_SCOPE


def _normalize_intervals(intervals: Sequence[str] | None) -> list[str]:
    if intervals is None:
        return []
    return _dedupe([str(interval).strip().lower() for interval in intervals if str(interval).strip()])


def _success_status(scope: str) -> str:
    if scope == SELECTED_INTERVALS_SCOPE:
        return "forward_paper_allowed"
    return "promotion_allowed"


def _success_reasons(scope: str) -> list[str]:
    if scope == SELECTED_INTERVALS_SCOPE:
        return ["selected_intervals_promoted"]
    return ["strategy_matrix_promoted"]


def _report(
    path: Path,
    *,
    variant: str,
    scope: str,
    intervals: list[str],
    status: str,
    reasons: list[str],
    thresholds: dict[str, Any],
) -> StrategyPromotionCheckReport:
    return StrategyPromotionCheckReport(
        status=status,
        promotion_allowed=False,
        reasons=reasons,
        matrix_report_path=str(path),
        variant=variant,
        scope=scope,
        intervals=intervals,
        thresholds=dict(thresholds),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
