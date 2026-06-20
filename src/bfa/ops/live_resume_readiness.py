"""Read-only live-resume readiness report across strategy, risk, and exchange gates."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.ops.exposure_status import ExposureStatusReport, build_exposure_status_report
from bfa.ops.strategy_evidence_baseline import (
    StrategyEvidenceBaselineReport,
    build_strategy_evidence_baseline_report,
)
from bfa.ops.strategy_promotion import (
    ALL_INTERVALS_SCOPE,
    SELECTED_INTERVALS_SCOPE,
    build_strategy_promotion_check_report,
)


PROMOTED_VERDICT = "candidate_for_forward_paper"


@dataclass(frozen=True)
class MatrixReadinessReport:
    status: str
    promotion_allowed: bool
    live_resume_allowed: bool
    reasons: list[str]
    matrix_report_path: str | None = None
    matrix_schema: str | None = None
    variant: str = "quant_setup_selective"
    scope: str = ALL_INTERVALS_SCOPE
    intervals: list[str] = field(default_factory=list)
    matrix_overall: str | None = None
    variant_summary: dict[str, Any] = field(default_factory=dict)
    selected_summary: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    cell_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_matrix_readiness_v1",
            "status": self.status,
            "promotion_allowed": self.promotion_allowed,
            "live_resume_allowed": self.live_resume_allowed,
            "reasons": list(self.reasons),
            "matrix_report_path": self.matrix_report_path,
            "matrix_schema": self.matrix_schema,
            "variant": self.variant,
            "scope": self.scope,
            "intervals": list(self.intervals),
            "matrix_overall": self.matrix_overall,
            "variant_summary": dict(self.variant_summary),
            "selected_summary": dict(self.selected_summary),
            "thresholds": dict(self.thresholds),
            "cell_checks": [dict(item) for item in self.cell_checks],
        }


@dataclass(frozen=True)
class LiveResumeReadinessReport:
    status: str
    live_resume_allowed: bool
    reasons: dict[str, list[str]]
    variant: str
    interval: str
    matrix: MatrixReadinessReport
    strategy_evidence: StrategyEvidenceBaselineReport
    exposure_status: ExposureStatusReport
    exchange_review: dict[str, Any] = field(default_factory=dict)
    live_auto_hot_preview: dict[str, Any] = field(default_factory=dict)
    read_only: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_live_resume_readiness_v1",
            "status": self.status,
            "live_resume_allowed": self.live_resume_allowed,
            "reasons": {key: list(value) for key, value in self.reasons.items()},
            "variant": self.variant,
            "interval": self.interval,
            "matrix": self.matrix.to_dict(),
            "strategy_evidence": self.strategy_evidence.to_dict(),
            "exposure_status": self.exposure_status.to_dict(),
            "exchange_review": dict(self.exchange_review),
            "live_auto_hot_preview": dict(self.live_auto_hot_preview),
            "read_only": dict(self.read_only),
        }


def build_live_resume_readiness_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    matrix_report_path: str | None = None,
    variant: str = "quant_setup_selective",
    interval: str = "5m",
    since: str | None = None,
    min_outcomes: int = 20,
    min_win_rate: float = 0.5,
    min_net_pnl_usdt: float = 0.0,
    min_profit_factor: float | None = 1.1,
    max_worst_drawdown_usdt: float | None = 1.5,
    latest_limit: int = 10,
    min_group_outcomes: int = 1,
    worst_limit: int = 8,
    matrix_scope: str = ALL_INTERVALS_SCOPE,
    matrix_intervals: Sequence[str] | None = None,
    matrix_min_trade_count: int = 5,
    matrix_min_positive_window_rate: float = 0.5,
    matrix_max_worst_drawdown_usdt: float | None = None,
    target_profile: str | None = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
    hypothetical_symbol: str | None = None,
    hypothetical_side: str | None = None,
    check_binance: bool = True,
    signed_client: BinanceFuturesSignedClient | None = None,
    exchange_state: str = "auto",
    manual_exposure_symbols: Sequence[str] | None = None,
    check_systemd: bool = True,
    server_state_overrides: Mapping[str, str] | None = None,
    require_operator_confirmation: bool = True,
) -> LiveResumeReadinessReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    manual_symbols = _normalize_symbols(manual_exposure_symbols)
    exposure = build_exposure_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client if check_binance else None,
        target_profile=target_profile,
        allow_two_positions=allow_two_positions,
        hypothetical_symbol=hypothetical_symbol,
        hypothetical_side=hypothetical_side,
    )
    exchange_review = _exchange_review(exposure, manual_symbols=manual_symbols)
    resolved_exchange_state = _resolve_exchange_state(exchange_state, exchange_review)

    strategy_evidence = build_strategy_evidence_baseline_report(
        config,
        db_path=resolved_db_path,
        variant=variant,
        interval=interval,
        since=since,
        min_outcomes=min_outcomes,
        min_win_rate=min_win_rate,
        min_net_pnl_usdt=min_net_pnl_usdt,
        min_profit_factor=min_profit_factor,
        max_worst_drawdown_usdt=max_worst_drawdown_usdt,
        latest_limit=latest_limit,
        min_group_outcomes=min_group_outcomes,
        worst_limit=worst_limit,
        check_systemd=check_systemd,
        server_state_overrides=server_state_overrides,
        exchange_state=resolved_exchange_state,
        manual_exposure_symbols=manual_symbols,
        require_operator_confirmation=require_operator_confirmation,
    )
    matrix = build_matrix_readiness_report(
        matrix_report_path,
        variant=variant,
        scope=matrix_scope,
        intervals=matrix_intervals,
        min_trade_count=matrix_min_trade_count,
        min_positive_window_rate=matrix_min_positive_window_rate,
        max_worst_drawdown_usdt=matrix_max_worst_drawdown_usdt,
    )
    reasons = _readiness_reasons(
        matrix=matrix,
        strategy_evidence=strategy_evidence,
        exposure=exposure,
        exchange_review=exchange_review,
        require_operator_confirmation=require_operator_confirmation,
    )
    live_resume_allowed = not any(reasons.values())
    return LiveResumeReadinessReport(
        status=_status(reasons),
        live_resume_allowed=live_resume_allowed,
        reasons=reasons,
        variant=variant,
        interval=interval,
        matrix=matrix,
        strategy_evidence=strategy_evidence,
        exposure_status=exposure,
        exchange_review=exchange_review,
        live_auto_hot_preview=_live_auto_hot_preview(config),
        read_only={
            "places_orders": False,
            "applies_risk_profiles": False,
            "writes_env_files": False,
            "changes_systemd_state": False,
            "mutates_exchange_state": False,
            "creates_order_intents": False,
            "restores_live_timer": False,
        },
    )


def build_matrix_readiness_report(
    matrix_report_path: str | None,
    *,
    variant: str,
    scope: str,
    intervals: Sequence[str] | None,
    min_trade_count: int,
    min_positive_window_rate: float,
    max_worst_drawdown_usdt: float | None,
) -> MatrixReadinessReport:
    normalized_scope = _normalize_scope(scope)
    selected_intervals = _normalize_intervals(intervals)
    thresholds = {
        "min_trade_count": min_trade_count,
        "min_positive_window_rate": min_positive_window_rate,
        "max_worst_drawdown_usdt": max_worst_drawdown_usdt,
    }
    if not matrix_report_path:
        return MatrixReadinessReport(
            status="matrix_report_missing",
            promotion_allowed=False,
            live_resume_allowed=False,
            reasons=["matrix_report_not_provided"],
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            thresholds=thresholds,
        )

    path = Path(matrix_report_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return MatrixReadinessReport(
            status="invalid_report",
            promotion_allowed=False,
            live_resume_allowed=False,
            reasons=["matrix_report_missing"],
            matrix_report_path=str(path),
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            thresholds=thresholds,
        )
    except json.JSONDecodeError:
        return MatrixReadinessReport(
            status="invalid_report",
            promotion_allowed=False,
            live_resume_allowed=False,
            reasons=["matrix_report_invalid_json"],
            matrix_report_path=str(path),
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            thresholds=thresholds,
        )

    if not isinstance(payload, Mapping):
        return _invalid_matrix_report(path, variant, normalized_scope, selected_intervals, thresholds)
    schema = str(payload.get("schema") or "")
    if schema == "bfa_hot_backtest_matrix_v1":
        promotion = build_strategy_promotion_check_report(
            path,
            variant=variant,
            min_trade_count=min_trade_count,
            min_positive_window_rate=min_positive_window_rate,
            max_worst_drawdown_usdt=max_worst_drawdown_usdt,
            intervals=selected_intervals,
            scope=normalized_scope,
        )
        payload = promotion.to_dict()
        return MatrixReadinessReport(
            status=promotion.status,
            promotion_allowed=promotion.promotion_allowed,
            live_resume_allowed=promotion.live_resume_allowed,
            reasons=list(promotion.reasons),
            matrix_report_path=str(path),
            matrix_schema=schema,
            variant=variant,
            scope=promotion.scope,
            intervals=list(promotion.intervals),
            matrix_overall=promotion.matrix_overall,
            variant_summary=dict(promotion.variant_summary),
            selected_summary=dict(promotion.selected_summary),
            thresholds=dict(promotion.thresholds),
            cell_checks=[dict(item) for item in payload.get("cell_checks", [])],
        )
    if schema == "bfa_hot_backtest_matrix_suite_v1":
        return _suite_matrix_readiness(
            path,
            payload,
            variant=variant,
            scope=normalized_scope,
            intervals=selected_intervals,
            thresholds=thresholds,
        )
    return _invalid_matrix_report(path, variant, normalized_scope, selected_intervals, thresholds)


def _suite_matrix_readiness(
    path: Path,
    payload: Mapping[str, Any],
    *,
    variant: str,
    scope: str,
    intervals: list[str],
    thresholds: dict[str, Any],
) -> MatrixReadinessReport:
    promotion = _mapping(payload.get("promotion"))
    variants = _mapping(promotion.get("variants"))
    variant_summary = _mapping(variants.get(variant))
    reasons: list[str] = []
    if scope == SELECTED_INTERVALS_SCOPE:
        reasons.append("selected_interval_scope_not_supported_for_matrix_suite")
    if intervals:
        reasons.append("selected_intervals_not_supported_for_matrix_suite")
    if not variant_summary:
        reasons.append("variant_summary_missing")
    if _optional_str(variant_summary.get("verdict")) != PROMOTED_VERDICT:
        reasons.append("suite_variant_not_promoted")
    if _float_or_zero(variant_summary.get("total_net_pnl_usdt")) <= 0:
        reasons.append("suite_variant_total_net_pnl_not_positive")

    matrices = [
        item
        for item in _list(payload.get("matrices"))
        if isinstance(item, Mapping)
    ]
    matrix_count = len(matrices)
    if matrix_count <= 0:
        reasons.append("suite_matrices_missing")
    selected_summary = {
        "matrix_count": matrix_count,
        "candidate_matrix_count": _int_or_zero(variant_summary.get("candidate_matrix_count")),
        "mixed_matrix_count": _int_or_zero(variant_summary.get("mixed_matrix_count")),
        "total_net_pnl_usdt": _float_or_zero(variant_summary.get("total_net_pnl_usdt")),
        "worst_drawdown_usdt": _float_or_zero(variant_summary.get("worst_drawdown_usdt")),
    }
    allowed = not reasons
    return MatrixReadinessReport(
        status="promotion_allowed" if allowed else "keep_live_paused",
        promotion_allowed=allowed,
        live_resume_allowed=allowed,
        reasons=_dedupe(reasons or ["matrix_suite_promoted"]),
        matrix_report_path=str(path),
        matrix_schema="bfa_hot_backtest_matrix_suite_v1",
        variant=variant,
        scope=scope,
        intervals=intervals,
        matrix_overall=_optional_str(promotion.get("overall")),
        variant_summary=dict(variant_summary),
        selected_summary=selected_summary,
        thresholds=thresholds,
    )


def _invalid_matrix_report(
    path: Path,
    variant: str,
    scope: str,
    intervals: list[str],
    thresholds: dict[str, Any],
) -> MatrixReadinessReport:
    return MatrixReadinessReport(
        status="invalid_report",
        promotion_allowed=False,
        live_resume_allowed=False,
        reasons=["matrix_report_schema_invalid"],
        matrix_report_path=str(path),
        variant=variant,
        scope=scope,
        intervals=intervals,
        thresholds=thresholds,
    )


def _readiness_reasons(
    *,
    matrix: MatrixReadinessReport,
    strategy_evidence: StrategyEvidenceBaselineReport,
    exposure: ExposureStatusReport,
    exchange_review: Mapping[str, Any],
    require_operator_confirmation: bool,
) -> dict[str, list[str]]:
    strategy_reasons = list(strategy_evidence.reasons.get("strategy_evidence", []))
    risk_reasons = _risk_profile_reasons(exposure)
    exchange_reasons = list(exchange_review.get("reasons") or [])
    if not exchange_reasons and not bool(exchange_review.get("exchange_evidence_present")):
        exchange_reasons = ["exchange_evidence_missing"]
    return {
        "matrix": [] if matrix.live_resume_allowed else list(matrix.reasons),
        "strategy_evidence": strategy_reasons,
        "server_state": list(strategy_evidence.reasons.get("server_state", [])),
        "exchange_state": _dedupe(exchange_reasons),
        "risk_profile": risk_reasons,
        "confirmation": ["operator_confirmation_required"] if require_operator_confirmation else [],
    }


def _risk_profile_reasons(exposure: ExposureStatusReport) -> list[str]:
    payload = exposure.to_dict()
    risk_change = _mapping(payload.get("risk_change"))
    if not risk_change:
        return ["target_profile_preview_missing"]
    if bool(risk_change.get("risk_change_allowed")):
        return []
    return _dedupe([str(item) for item in _list(risk_change.get("reasons")) if str(item)])


def _exchange_review(
    exposure: ExposureStatusReport,
    *,
    manual_symbols: list[str],
) -> dict[str, Any]:
    payload = exposure.to_dict()
    exchange_summary = _mapping(payload.get("exchange_summary"))
    entry_capacity = _mapping(payload.get("entry_capacity"))
    capacity_active_exposures = [_mapping(item) for item in _list(entry_capacity.get("active_exposures"))]
    manual_exposures = [_mapping(item) for item in _list(entry_capacity.get("manual_exposures"))]
    active_exposures = [*capacity_active_exposures, *manual_exposures]
    risk_change = _mapping(payload.get("risk_change"))
    unreconciled = [_mapping(item) for item in _list(risk_change.get("unreconciled_submitted_intents"))]
    agent_symbols = {str(item.get("symbol") or "").upper() for item in unreconciled if item.get("symbol")}
    manual_set = set(manual_symbols)
    active_symbols = [str(item.get("symbol") or "").upper() for item in active_exposures if item.get("symbol")]
    agent_managed = [symbol for symbol in active_symbols if symbol in agent_symbols and symbol not in manual_set]
    manual_or_unattributed = _dedupe(
        [
            *[symbol for symbol in manual_symbols if symbol in active_symbols],
            *[symbol for symbol in active_symbols if symbol not in agent_symbols or symbol in manual_set],
        ]
    )
    reasons: list[str] = []
    if manual_or_unattributed:
        reasons.append("manual_or_unattributed_exchange_exposure_present")
    if _int_or_zero(exchange_summary.get("open_order_count")) > 0:
        reasons.append("exchange_open_orders_present")
    if (
        _int_or_zero(exchange_summary.get("open_algo_order_count")) > 0
        and _int_or_zero(exchange_summary.get("position_count")) <= 0
    ):
        reasons.append("orphan_exchange_algo_orders_present")
    return {
        "exchange_evidence_present": bool(exchange_summary.get("exchange_evidence_present")),
        "manual_or_unattributed_symbols": manual_or_unattributed,
        "agent_managed_symbols": _dedupe(agent_managed),
        "active_exposures": active_exposures,
        "capacity_active_exposures": capacity_active_exposures,
        "manual_exposures": manual_exposures,
        "unreconciled_submitted_intents": unreconciled,
        "position_count": _int_or_zero(exchange_summary.get("position_count")),
        "open_order_count": _int_or_zero(exchange_summary.get("open_order_count")),
        "open_algo_order_count": _int_or_zero(exchange_summary.get("open_algo_order_count")),
        "manual_exposure_is_agent_evidence": False,
        "reasons": reasons,
    }


def _resolve_exchange_state(exchange_state: str, exchange_review: Mapping[str, Any]) -> str:
    normalized = str(exchange_state or "auto").strip().lower()
    if normalized != "auto":
        return normalized
    if exchange_review.get("manual_or_unattributed_symbols"):
        return "manual_exposure"
    if _int_or_zero(exchange_review.get("open_order_count")) > 0:
        return "open_orders"
    if exchange_review.get("agent_managed_symbols"):
        return "agent_exposure"
    if bool(exchange_review.get("exchange_evidence_present")):
        return "clear"
    return "unknown"


def _live_auto_hot_preview(config: AppConfig) -> dict[str, Any]:
    enabled = _truthy(config.get("BFA_LIVE_AUTO_HOT_SYMBOLS"))
    return {
        "enabled_in_config": enabled,
        "status": "enabled_requires_operator_review" if enabled else "disabled_by_default",
        "top_n": _int_or_zero(config.get("BFA_LIVE_AUTO_HOT_TOP_N")),
        "min_quote_volume_usdt": _float_or_zero(config.get("BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT")),
        "min_abs_price_change_percent": _float_or_zero(
            config.get("BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT")
        ),
        "preview_only": True,
        "places_orders": False,
    }


def _status(reasons: Mapping[str, list[str]]) -> str:
    if reasons.get("matrix") or reasons.get("strategy_evidence"):
        return "keep_live_paused"
    if any(reasons.values()):
        return "live_resume_blocked"
    return "live_resume_ready"


def _normalize_scope(scope: str) -> str:
    if scope == SELECTED_INTERVALS_SCOPE:
        return SELECTED_INTERVALS_SCOPE
    return ALL_INTERVALS_SCOPE


def _normalize_intervals(intervals: Sequence[str] | None) -> list[str]:
    return _dedupe([str(item).strip().lower() for item in intervals or [] if str(item).strip()])


def _normalize_symbols(symbols: Sequence[str] | None) -> list[str]:
    return _dedupe([str(item).strip().upper() for item in symbols or [] if str(item).strip()])


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


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


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
