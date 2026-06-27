"""Fast active-position sentinel for protective-order backfill and trailing."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import json
import sqlite3
from typing import Any, Mapping

from bfa.config import AppConfig, RuntimeMode
from bfa.event_store.migrations import connect
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.ops.position_adjustment import (
    PositionAdjustmentExecuteReport,
    PositionAdjustmentPlanReport,
    build_position_adjustment_plan_report,
    execute_position_adjustment_plan_report,
    position_adjustment_plan_from_review,
)
from bfa.execution.filters import SymbolExecutionFilters


@dataclass(frozen=True)
class ReversalRiskSignal:
    symbol: str
    position_side: str | None
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_side": self.position_side,
            "score": self.score,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class PositionSentinelReport:
    status: str
    checked_at: str
    execution_enabled: bool
    reasons: list[str] = field(default_factory=list)
    reversal_signals: list[ReversalRiskSignal] = field(default_factory=list)
    adjustment_plan: PositionAdjustmentPlanReport | None = None
    execution: PositionAdjustmentExecuteReport | None = None
    persisted: dict[str, int] = field(default_factory=dict)

    @property
    def action_executed(self) -> bool:
        return bool(self.execution and self.execution.adjustment_executed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_position_sentinel_v1",
            "status": self.status,
            "checked_at": self.checked_at,
            "execution_enabled": self.execution_enabled,
            "reasons": list(self.reasons),
            "reversal_signals": [signal.to_dict() for signal in self.reversal_signals],
            "adjustment_plan": self.adjustment_plan.to_dict() if self.adjustment_plan else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "persisted": dict(self.persisted),
        }


def build_position_sentinel_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    now: str | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
    market_client=None,
    exchange_info: Mapping[str, Any] | None = None,
    execute: bool = False,
) -> PositionSentinelReport:
    checked_at = _now_iso(now)
    if RuntimeMode(config.get("BFA_MODE")) is not RuntimeMode.LIVE:
        return _report(
            config,
            db_path,
            PositionSentinelReport(
                status="sentinel_blocked",
                checked_at=checked_at,
                execution_enabled=False,
                reasons=["live_mode_required"],
            ),
        )
    if not _truthy(config.get("BFA_POSITION_SENTINEL_ENABLED", "true")):
        return _report(
            config,
            db_path,
            PositionSentinelReport(
                status="sentinel_disabled",
                checked_at=checked_at,
                execution_enabled=False,
                reasons=["position_sentinel_disabled"],
            ),
        )

    client = signed_client or BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )
    market = market_client or BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    plan = build_position_adjustment_plan_report(
        config,
        db_path=resolved_db_path,
        check_binance=True,
        now=checked_at,
        signed_client=client,
        market_client=market,
        exchange_info=exchange_info,
        require_filters=True,
        ignore_normal_open_orders=True,
    )
    cooldowns = _trend_cooldowns_from_store(
        resolved_db_path,
        checked_at=checked_at,
        cooldown_seconds=_float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_COOLDOWN_SECONDS"), 180.0),
    )
    signals = _reversal_signals_from_plan(config, plan, market_client=market, cooldowns=cooldowns)
    plan = _plan_with_sentinel_trailing_requests(
        config,
        plan,
        signals,
        market_client=market,
        exchange_info=exchange_info,
    )
    allowed_actions = _allowed_actions_from_signals(plan, signals)
    execution_enabled = bool(execute and _truthy(config.get("BFA_POSITION_SENTINEL_EXECUTE_ENABLED", "false")))
    reasons = _sentinel_reasons(plan, signals, allowed_actions, execution_enabled=execution_enabled, requested=execute)
    execution = None
    if execution_enabled and allowed_actions:
        execution = execute_position_adjustment_plan_report(
            config,
            plan,
            db_path=resolved_db_path,
            checked_at=checked_at,
            signed_client=client,
            allowed_actions=tuple(allowed_actions),
            max_actions=max(1, _int_or_default(config.get("BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE"), 1)),
        )
    status = _status(plan, signals, execution, execution_enabled=execution_enabled, allowed_actions=allowed_actions)
    return _report(
        config,
        resolved_db_path,
        PositionSentinelReport(
            status=status,
            checked_at=checked_at,
            execution_enabled=execution_enabled,
            reasons=reasons,
            reversal_signals=signals,
            adjustment_plan=plan,
            execution=execution,
        ),
    )


def _reversal_signals_from_plan(
    config: AppConfig,
    plan: PositionAdjustmentPlanReport,
    *,
    market_client,
    cooldowns: Mapping[tuple[str, str | None], dict[str, Any]] | None = None,
) -> list[ReversalRiskSignal]:
    review = plan.position_review
    if review is None:
        return []
    return [
        _reversal_signal(config, item, market_client=market_client, cooldowns=cooldowns or {})
        for item in review.positions
        if item.recommendation != "manual_hold" and item.position_amt != 0
    ]


def _reversal_signal(
    config: AppConfig,
    item,
    *,
    market_client,
    cooldowns: Mapping[tuple[str, str | None], dict[str, Any]],
) -> ReversalRiskSignal:
    side = "LONG" if item.position_amt > 0 else "SHORT"
    profile = _protection_profile(config, item)
    cooldown = _cooldown_for_item(item, profile=profile, cooldowns=cooldowns)
    if cooldown is not None and item.algo_protection_count >= 2:
        return _cooldown_signal(item, profile=profile, cooldown=cooldown)
    threshold = profile["threshold"]
    min_profit_r = profile["min_profit_r"]
    min_progress = profile["min_progress"]
    klines = _recent_klines(
        market_client,
        item.symbol,
        interval=config.get("BFA_POSITION_SENTINEL_INTERVAL", "1m"),
        limit=_int_or_default(config.get("BFA_POSITION_SENTINEL_LOOKBACK_LIMIT"), 24),
    )
    elapsed_seconds = round((item.elapsed_minutes or 0.0) * 60.0, 3) if item.elapsed_minutes is not None else None
    entry_klines = _entry_scoped_klines(klines, elapsed_seconds=elapsed_seconds)
    metrics = {
        **_micro_path_metrics(klines, side=side),
        **_position_excursion_metrics(item, entry_klines, side=side),
        "elapsed_seconds": elapsed_seconds,
        "entry_scoped_sample_count": len(entry_klines),
        "current_stop_r_multiple": item.stop_r_multiple,
        "current_target_progress": item.target_progress,
    }
    score = _score_reversal_risk(item, metrics, side=side, profile=profile)
    reasons: list[str] = []
    if profile["name"]:
        reasons.append(f"protection_profile:{profile['name']}")
    if item.algo_protection_count < 2:
        reasons.append("protective_backfill_required")
    if item.stop_r_multiple is not None and item.stop_r_multiple >= min_profit_r:
        reasons.append("profit_r_threshold_met")
    if item.target_progress is not None and item.target_progress >= min_progress:
        reasons.append("target_progress_threshold_met")
    if _recent_mfe_threshold_met(metrics, min_profit_r=min_profit_r, min_progress=min_progress):
        reasons.append("recent_mfe_threshold_met")
    if _profit_giveback_detected(metrics, profile=profile):
        reasons.append("profit_giveback_detected")
    if _flow_is_fading(metrics, profile=profile):
        reasons.append("flow_fade_detected")
    if _adverse_micro_reversal(metrics, profile=profile):
        reasons.append("adverse_micro_reversal_detected")
    if _micro_stagnation_detected(item, metrics, profile=profile):
        reasons.append("stagnation_exit_pressure")
    if _micro_setup_invalidated(item, metrics, profile=profile):
        reasons.append("setup_invalidated_exit_pressure")
    if _trend_degrade_loss_control_ready(item, metrics, profile=profile):
        reasons.append("trend_degrade_loss_control_ready")
    if any(reason in {"stagnation_exit_pressure", "setup_invalidated_exit_pressure"} for reason in reasons):
        if _micro_loss_control_ready(item, metrics, profile=profile):
            reasons.append("loss_control_ready")
        else:
            reasons.append("loss_control_waiting_for_confirmation")
    protection_layer = _profit_protection_layer(item, metrics, profile=profile)
    reasons.extend(protection_layer["reasons"])
    metrics.update(
        {
            "profit_protection_layer": protection_layer["layer"],
            "profit_protection_lock_r": protection_layer["lock_r"],
            "profit_protection_giveback_r": protection_layer["giveback_r"],
        }
    )
    if score >= threshold:
        reasons.append("reversal_risk_threshold_met")
    decision = (
        "trail_or_backfill"
        if _signal_allows_trailing(
            item,
            score,
            threshold,
            min_profit_r,
            min_progress,
            metrics=metrics,
            profile=profile,
        )
        else "observe"
    )
    return ReversalRiskSignal(
        symbol=item.symbol,
        position_side=item.position_side,
        score=round(score, 4),
        decision=decision,
        reasons=_dedupe(reasons or ["no_reversal_action"]),
        metrics={**metrics, "protection_profile": profile["name"]},
    )


def _trend_cooldowns_from_store(
    db_path: str,
    *,
    checked_at: str,
    cooldown_seconds: float,
) -> dict[tuple[str, str | None], dict[str, Any]]:
    if cooldown_seconds <= 0:
        return {}
    checked = _parse_iso(checked_at)
    if checked is None:
        return {}
    since = checked - timedelta(seconds=cooldown_seconds)
    result: dict[tuple[str, str | None], dict[str, Any]] = {}
    try:
        connection = connect(db_path)
        try:
            rows = connection.execute(
                """
                SELECT occurred_at, payload_json
                FROM events
                WHERE event_type = ?
                  AND occurred_at >= ?
                  AND occurred_at < ?
                ORDER BY occurred_at DESC, id DESC
                """,
                (
                    "position_sentinel",
                    since.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    checked.isoformat(timespec="seconds").replace("+00:00", "Z"),
                ),
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return {}

    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if str(payload.get("status") or "").lower() != "sentinel_executed":
            continue
        if not _sentinel_payload_executed_trailing(payload):
            continue
        occurred_at = str(row["occurred_at"])
        occurred = _parse_iso(occurred_at)
        if occurred is None:
            continue
        elapsed = (checked - occurred).total_seconds()
        if elapsed < 0 or elapsed >= cooldown_seconds:
            continue
        for signal in payload.get("reversal_signals") or []:
            if not isinstance(signal, Mapping):
                continue
            metrics = signal.get("metrics") if isinstance(signal.get("metrics"), Mapping) else {}
            if str(metrics.get("protection_profile") or "").lower() != "trend":
                continue
            if str(signal.get("decision") or "").lower() != "trail_or_backfill":
                continue
            key = (
                str(signal.get("symbol") or "").upper(),
                str(signal.get("position_side") or "").upper() or None,
            )
            if not key[0] or key in result:
                continue
            result[key] = {
                "last_decision_at": occurred_at,
                "remaining_seconds": max(cooldown_seconds - elapsed, 0.0),
            }
    return result


def _sentinel_payload_executed_trailing(payload: Mapping[str, Any]) -> bool:
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        return False
    if not bool(execution.get("adjustment_executed")):
        return False
    for item in execution.get("executions") or []:
        if not isinstance(item, Mapping):
            continue
        order_plan = item.get("order_plan")
        if isinstance(order_plan, Mapping) and str(order_plan.get("action") or "").lower() == "trail_protective_orders":
            return True
    return False


def _cooldown_for_item(
    item,
    *,
    profile: Mapping[str, Any],
    cooldowns: Mapping[tuple[str, str | None], dict[str, Any]],
) -> dict[str, Any] | None:
    if str(profile.get("name") or "") != "trend":
        return None
    return cooldowns.get((str(item.symbol).upper(), str(item.position_side or "").upper() or None))


def _cooldown_signal(item, *, profile: Mapping[str, Any], cooldown: Mapping[str, Any]) -> ReversalRiskSignal:
    remaining_seconds = int(max(_float_or_none(cooldown.get("remaining_seconds")) or 0.0, 0.0))
    return ReversalRiskSignal(
        symbol=item.symbol,
        position_side=item.position_side,
        score=0.0,
        decision="observe",
        reasons=[
            f"protection_profile:{profile['name']}",
            "trend_protection_cooldown_active",
            f"trend_protection_cooldown_remaining_seconds:{remaining_seconds}",
        ],
        metrics={
            "protection_profile": profile["name"],
            "trend_protection_cooldown_remaining_seconds": remaining_seconds,
            "trend_protection_last_decision_at": cooldown.get("last_decision_at"),
        },
    )


def _recent_klines(market_client, symbol: str, *, interval: str, limit: int) -> list[Any]:
    try:
        payload = market_client.klines(symbol, interval=interval, limit=limit).payload
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _micro_path_metrics(klines: list[Any], *, side: str) -> dict[str, Any]:
    closes = [_float_or_none(row[4]) for row in klines if isinstance(row, list) and len(row) > 4]
    highs = [_float_or_none(row[2]) for row in klines if isinstance(row, list) and len(row) > 4]
    lows = [_float_or_none(row[3]) for row in klines if isinstance(row, list) and len(row) > 4]
    volumes = [_float_or_none(row[5]) for row in klines if isinstance(row, list) and len(row) > 5]
    closes = [value for value in closes if value is not None and value > 0]
    highs = [value for value in highs if value is not None and value > 0]
    lows = [value for value in lows if value is not None and value > 0]
    volumes = [value for value in volumes if value is not None and value >= 0]
    if len(closes) < 4:
        return {"sample_count": len(closes), "path_available": False}
    last = closes[-1]
    previous = closes[-4]
    short_return = (last - previous) / previous if previous > 0 else 0.0
    signed_short_return = short_return if side == "LONG" else -short_return
    recent_high = max(highs[-8:] or closes[-8:])
    recent_low = min(lows[-8:] or closes[-8:])
    range_fraction = (recent_high - recent_low) / last if last > 0 else 0.0
    volume_ratio = 1.0
    if len(volumes) >= 8:
        recent = sum(volumes[-4:]) / 4.0
        prior = sum(volumes[-8:-4]) / 4.0
        volume_ratio = recent / prior if prior > 0 else 1.0
    direction_alignment = 0.0
    if len(closes) >= 6:
        aligned = 0
        total = 0
        for previous_close, close in zip(closes[-6:-1], closes[-5:]):
            delta = close - previous_close
            if delta == 0:
                continue
            total += 1
            signed_delta = delta if side == "LONG" else -delta
            if signed_delta > 0:
                aligned += 1
        direction_alignment = aligned / total if total > 0 else 0.0
    return {
        "sample_count": len(closes),
        "path_available": True,
        "signed_short_return_percent": round(signed_short_return * 100.0, 5),
        "range_percent": round(range_fraction * 100.0, 5),
        "volume_ratio": round(volume_ratio, 5),
        "direction_alignment": round(direction_alignment, 5),
    }


def _entry_scoped_klines(klines: list[Any], *, elapsed_seconds: float | None) -> list[Any]:
    if not klines:
        return []
    if elapsed_seconds is None or elapsed_seconds <= 0:
        return [klines[-1]]
    timed_rows: list[tuple[float, Any]] = []
    for row in klines:
        if not isinstance(row, list) or not row:
            continue
        opened_at_ms = _float_or_none(row[0])
        if opened_at_ms is None:
            continue
        timed_rows.append((opened_at_ms, row))
    if not timed_rows:
        return list(klines)
    latest_open_ms = max(opened_at_ms for opened_at_ms, _ in timed_rows)
    cutoff_ms = latest_open_ms - max(elapsed_seconds, 0.0) * 1000.0
    scoped = [row for opened_at_ms, row in timed_rows if opened_at_ms >= cutoff_ms]
    return scoped or [timed_rows[-1][1]]


def _position_excursion_metrics(item, klines: list[Any], *, side: str) -> dict[str, Any]:
    highs = [_float_or_none(row[2]) for row in klines if isinstance(row, list) and len(row) > 4]
    lows = [_float_or_none(row[3]) for row in klines if isinstance(row, list) and len(row) > 4]
    highs = [value for value in highs if value is not None and value > 0]
    lows = [value for value in lows if value is not None and value > 0]
    entry = _float_or_none(item.entry_price)
    stop = _float_or_none(item.stop_price)
    target = _float_or_none(item.target_price)
    if entry is None or entry <= 0 or not highs or not lows:
        return {}
    if side == "LONG":
        best_price = max(highs)
        worst_price = min(lows)
        favorable_move = best_price - entry
        adverse_move = entry - worst_price
    else:
        best_price = min(lows)
        worst_price = max(highs)
        favorable_move = entry - best_price
        adverse_move = worst_price - entry
    payload: dict[str, Any] = {
        "recent_best_favorable_price": round(best_price, 8),
        "recent_worst_adverse_price": round(worst_price, 8),
        "recent_favorable_move_percent": round(favorable_move / entry * 100.0, 5),
        "recent_adverse_move_percent": round(adverse_move / entry * 100.0, 5),
    }
    if target is not None and target != entry:
        target_distance = abs(target - entry)
        if target_distance > 0:
            max_progress = favorable_move / target_distance
            current_progress = _float_or_none(item.target_progress) or 0.0
            payload["recent_max_target_progress"] = round(max_progress, 5)
            payload["target_progress_giveback"] = round(max(max_progress - current_progress, 0.0), 5)
            payload["target_progress_giveback_ratio"] = round(
                max(max_progress - current_progress, 0.0) / max_progress,
                5,
            ) if max_progress > 0 else 0.0
    if stop is not None and stop != entry:
        risk_distance = abs(entry - stop)
        if risk_distance > 0:
            payload["recent_max_stop_r_multiple"] = round(favorable_move / risk_distance, 5)
            payload["recent_max_adverse_r_multiple"] = round(adverse_move / risk_distance, 5)
    return payload


def _score_reversal_risk(item, metrics: Mapping[str, Any], *, side: str, profile: Mapping[str, Any]) -> float:
    score = 0.0
    target_progress = _float_or_none(item.target_progress) or 0.0
    stop_r = _float_or_none(item.stop_r_multiple) or 0.0
    recent_target_progress = _float_or_none(metrics.get("recent_max_target_progress")) or 0.0
    recent_stop_r = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    score += min(max(target_progress, 0.0), 1.25) * 0.28
    score += min(max(stop_r, 0.0), 1.5) * 0.18
    score += min(max(recent_target_progress - target_progress, 0.0), 1.0) * 0.12
    score += min(max(recent_stop_r - stop_r, 0.0), 1.0) * 0.08
    signed_short_return = _float_or_none(metrics.get("signed_short_return_percent")) or 0.0
    if signed_short_return < -0.05:
        score += min(abs(signed_short_return) / 0.35, 1.0) * 0.28
    volume_ratio = _float_or_none(metrics.get("volume_ratio")) or 1.0
    if volume_ratio > 1.25:
        score += min((volume_ratio - 1.25) / 1.75, 1.0) * 0.14
    if volume_ratio < 0.72 and (max(target_progress, recent_target_progress) >= 0.35 or max(stop_r, recent_stop_r) >= 0.25):
        score += min((0.72 - volume_ratio) / 0.42, 1.0) * 0.12
    alignment = _float_or_none(metrics.get("direction_alignment")) or 0.0
    if alignment < 0.35 and (max(target_progress, recent_target_progress) >= 0.35 or max(stop_r, recent_stop_r) >= 0.25):
        score += min((0.35 - alignment) / 0.35, 1.0) * 0.10
    range_percent = _float_or_none(metrics.get("range_percent")) or 0.0
    if range_percent > 0.35:
        score += min((range_percent - 0.35) / 1.25, 1.0) * 0.12
    if _micro_stagnation_detected(item, metrics, profile=profile):
        score += 0.18
    if _micro_setup_invalidated(item, metrics, profile=profile):
        score += 0.24
    return min(score, 1.0)


def _signal_allows_trailing(
    item,
    score: float,
    threshold: float,
    min_profit_r: float,
    min_progress: float,
    *,
    metrics: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> bool:
    if item.algo_protection_count < 2:
        return True
    if str(profile.get("name") or "") == "micro_grid":
        profitable = _micro_profit_gate_met(item, metrics, profile=profile)
        loss_control_ready = (
            _micro_stagnation_detected(item, metrics, profile=profile)
            or _micro_setup_invalidated(item, metrics, profile=profile)
        ) and _micro_loss_control_ready(item, metrics, profile=profile)
        if not loss_control_ready and not _micro_profit_protection_ready(item, metrics, profile=profile):
            return False
    else:
        profitable = _trend_profit_protection_ready(item, metrics, profile=profile)
        loss_control_ready = _trend_degrade_loss_control_ready(item, metrics, profile=profile)
        if loss_control_ready:
            return True
    if not profitable:
        return False
    if (_micro_stagnation_detected(item, metrics, profile=profile) or _micro_setup_invalidated(item, metrics, profile=profile)) and _micro_loss_control_ready(
        item,
        metrics,
        profile=profile,
    ):
        return True
    if score >= threshold:
        return True
    return (
        _profit_giveback_detected(metrics, profile=profile)
        or _flow_is_fading(metrics, profile=profile)
        or _adverse_micro_reversal(metrics, profile=profile)
    )


def _protection_profile(config: AppConfig, item) -> dict[str, Any]:
    leg = str(getattr(item, "strategy_leg", "") or "").strip().lower()
    regime = str(getattr(item, "regime_label", "") or "").strip().upper()
    reasons = [str(reason).lower() for reason in getattr(item, "reasons", []) or []]
    is_micro = leg in {"micro_grid", "range_reversion"} or regime == "RANGE" or any("micro_grid" in reason for reason in reasons)
    if is_micro:
        return {
            "name": "micro_grid",
            "min_profit_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_MIN_PROFIT_R"), 0.08),
            "min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_MIN_TARGET_PROGRESS"), 0.22),
            "threshold": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_REVERSAL_THRESHOLD"), 0.46),
            "volume_fade_ratio": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_VOLUME_FADE_RATIO"), 0.82),
            "adverse_return_percent": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_ADVERSE_RETURN_PERCENT"), 0.04),
            "lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOCK_R"), 0.10),
            "giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_GIVEBACK_R"), 0.22),
            "target_extension_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_TARGET_EXTENSION_R"), 0.20),
            "giveback_ratio": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_GIVEBACK_RATIO"), 0.35),
            "stagnation_seconds": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_STAGNATION_SECONDS"), 150.0),
            "stagnation_max_abs_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_STAGNATION_MAX_ABS_R"), 0.12),
            "stagnation_max_mfe_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_STAGNATION_MAX_MFE_R"), 0.18),
            "invalidation_adverse_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_INVALIDATION_ADVERSE_R"), 0.18),
            "invalidation_direction_alignment": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_INVALIDATION_DIRECTION_ALIGNMENT"), 0.25),
            "loss_control_lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_LOCK_R"), 0.0),
            "loss_control_giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_GIVEBACK_R"), 0.08),
            "loss_control_min_seconds": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_MIN_SECONDS"), 90.0),
            "loss_control_min_giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_MIN_GIVEBACK_R"), 0.35),
            "loss_control_hard_adverse_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_HARD_ADVERSE_R"), 0.55),
            "loss_control_target_extension_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_LOSS_CONTROL_TARGET_EXTENSION_R"), 0.08),
            "profit_protection_min_seconds": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_PROFIT_PROTECTION_MIN_SECONDS"), 45.0),
            "profit_protection_min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_PROFIT_PROTECTION_MIN_PROGRESS"), 0.35),
            "profit_protection_min_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_PROFIT_PROTECTION_MIN_R"), 0.45),
            "first_wave_min_seconds": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_FIRST_WAVE_MIN_SECONDS"), 20.0),
            "first_wave_min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_FIRST_WAVE_MIN_PROGRESS"), 0.55),
            "first_wave_min_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_MICRO_FIRST_WAVE_MIN_R"), 0.65),
        }
    return {
        "name": "trend",
        "min_profit_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_MIN_PROFIT_R"), _float_or_default(config.get("BFA_POSITION_SENTINEL_MIN_PROFIT_R"), 0.25)),
        "min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_MIN_TARGET_PROGRESS"), _float_or_default(config.get("BFA_POSITION_SENTINEL_MIN_TARGET_PROGRESS"), 0.25)),
        "threshold": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_REVERSAL_THRESHOLD"), _float_or_default(config.get("BFA_POSITION_SENTINEL_REVERSAL_THRESHOLD"), 0.62)),
        "volume_fade_ratio": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_VOLUME_FADE_RATIO"), 0.68),
        "adverse_return_percent": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_ADVERSE_RETURN_PERCENT"), 0.10),
        "lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOCK_R"), _float_or_default(config.get("BFA_TRAILING_PROTECTION_LOCK_R"), 0.25)),
        "giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_GIVEBACK_R"), _float_or_default(config.get("BFA_TRAILING_PROTECTION_GIVEBACK_R"), 0.65)),
        "target_extension_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_TARGET_EXTENSION_R"), _float_or_default(config.get("BFA_TRAILING_PROTECTION_TARGET_EXTENSION_R"), 0.75)),
        "giveback_ratio": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_GIVEBACK_RATIO"), 0.55),
        "defensive_min_profit_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_DEFENSIVE_MIN_PROFIT_R"), 0.60),
        "defensive_min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_DEFENSIVE_MIN_TARGET_PROGRESS"), 0.30),
        "defensive_lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_DEFENSIVE_LOCK_R"), 0.12),
        "defensive_giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_DEFENSIVE_GIVEBACK_R"), 0.75),
        "strong_min_profit_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_STRONG_MIN_PROFIT_R"), 1.0),
        "strong_min_progress": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_STRONG_MIN_TARGET_PROGRESS"), 0.55),
        "strong_lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_STRONG_LOCK_R"), 0.35),
        "strong_giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_STRONG_GIVEBACK_R"), 0.65),
        "loss_control_min_seconds": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_MIN_SECONDS"), 1800.0),
        "loss_control_adverse_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_ADVERSE_R"), 0.55),
        "loss_control_hard_adverse_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_HARD_ADVERSE_R"), 0.78),
        "loss_control_min_reversal_score": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_MIN_REVERSAL_SCORE"), 0.52),
        "loss_control_adverse_volume_ratio": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_ADVERSE_VOLUME_RATIO"), 1.50),
        "loss_control_max_alignment": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_MAX_ALIGNMENT"), 0.35),
        "loss_control_no_mfe_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_NO_MFE_R"), 0.12),
        "loss_control_lock_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_LOCK_R"), -0.30),
        "loss_control_giveback_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_GIVEBACK_R"), 0.20),
        "loss_control_target_extension_r": _float_or_default(config.get("BFA_POSITION_SENTINEL_TREND_LOSS_CONTROL_TARGET_EXTENSION_R"), 0.20),
    }


def _recent_mfe_threshold_met(metrics: Mapping[str, Any], *, min_profit_r: float, min_progress: float) -> bool:
    recent_stop_r = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    recent_progress = _float_or_none(metrics.get("recent_max_target_progress")) or 0.0
    return recent_stop_r >= min_profit_r or recent_progress >= min_progress


def _micro_loss_control_ready(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "micro_grid":
        return True
    if not _micro_profit_gate_met(item, metrics, profile=profile):
        return False
    elapsed = _float_or_none(metrics.get("elapsed_seconds"))
    min_seconds = _float_or_default(profile.get("loss_control_min_seconds"), 90.0)
    if elapsed is None or elapsed < min_seconds:
        return False
    if _micro_stagnation_detected(item, metrics, profile=profile):
        return True
    current_r = _float_or_none(metrics.get("current_stop_r_multiple")) or 0.0
    adverse_r = max(
        _float_or_none(metrics.get("recent_max_adverse_r_multiple")) or 0.0,
        -current_r,
    )
    hard_adverse_r = _float_or_default(profile.get("loss_control_hard_adverse_r"), 0.55)
    return adverse_r >= hard_adverse_r and _micro_setup_invalidated(item, metrics, profile=profile)


def _micro_profit_protection_ready(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "micro_grid":
        return True
    if not _micro_profit_gate_met(item, metrics, profile=profile):
        return False
    elapsed = _float_or_none(metrics.get("elapsed_seconds"))
    min_seconds = _float_or_default(profile.get("profit_protection_min_seconds"), 45.0)
    if elapsed is None or elapsed >= min_seconds:
        return True
    if not _micro_first_wave_profit_capture_ready(item, metrics, profile=profile):
        return False
    first_wave_min_seconds = _float_or_default(profile.get("first_wave_min_seconds"), 20.0)
    return elapsed >= first_wave_min_seconds


def _micro_first_wave_profit_capture_ready(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "micro_grid":
        return False
    current_r = _float_or_none(item.stop_r_multiple) or 0.0
    current_progress = _float_or_none(item.target_progress) or 0.0
    recent_r = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    recent_progress = _float_or_none(metrics.get("recent_max_target_progress")) or 0.0
    return max(current_r, recent_r) >= _float_or_default(profile.get("first_wave_min_r"), 0.65) or max(
        current_progress,
        recent_progress,
    ) >= _float_or_default(profile.get("first_wave_min_progress"), 0.55)


def _micro_profit_gate_met(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    current_r = _float_or_none(item.stop_r_multiple) or 0.0
    current_progress = _float_or_none(item.target_progress) or 0.0
    min_r = max(
        _float_or_default(profile.get("min_profit_r"), 0.08),
        _float_or_default(profile.get("profit_protection_min_r"), 0.45),
    )
    min_progress = max(
        _float_or_default(profile.get("min_progress"), 0.22),
        _float_or_default(profile.get("profit_protection_min_progress"), 0.35),
    )
    return current_r >= min_r or current_progress >= min_progress


def _trend_degrade_loss_control_ready(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "trend":
        return False
    if item.algo_protection_count < 2:
        return False
    elapsed = _float_or_none(metrics.get("elapsed_seconds"))
    min_seconds = _float_or_default(profile.get("loss_control_min_seconds"), 1800.0)
    if elapsed is None or elapsed < min_seconds:
        return False
    current_r = _float_or_none(metrics.get("current_stop_r_multiple")) or 0.0
    adverse_r = max(_float_or_none(metrics.get("recent_max_adverse_r_multiple")) or 0.0, -current_r)
    hard_adverse = _float_or_default(profile.get("loss_control_hard_adverse_r"), 0.78)
    base_adverse = _float_or_default(profile.get("loss_control_adverse_r"), 0.55)
    if adverse_r >= hard_adverse:
        return True
    if adverse_r < base_adverse:
        return False
    reversal_score = _score_reversal_risk(item, metrics, side="LONG" if item.position_amt > 0 else "SHORT", profile=profile)
    if reversal_score >= _float_or_default(profile.get("loss_control_min_reversal_score"), 0.52):
        return True
    if not _adverse_micro_reversal(metrics, profile=profile):
        return False
    if _flow_is_fading(metrics, profile=profile):
        return True
    volume_ratio = _float_or_none(metrics.get("volume_ratio")) or 1.0
    alignment = _float_or_none(metrics.get("direction_alignment")) or 0.0
    adverse_volume_ratio = _float_or_default(profile.get("loss_control_adverse_volume_ratio"), 1.50)
    max_alignment = _float_or_default(profile.get("loss_control_max_alignment"), 0.35)
    if volume_ratio >= adverse_volume_ratio and alignment <= max_alignment:
        return True
    recent_mfe_r = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    no_mfe_r = _float_or_default(profile.get("loss_control_no_mfe_r"), 0.12)
    return recent_mfe_r <= no_mfe_r and alignment <= max_alignment


def _trend_profit_protection_ready(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    return str(_profit_protection_layer(item, metrics, profile=profile).get("layer") or "observe") in {
        "defensive",
        "strong",
    }


def _profit_protection_layer(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> dict[str, Any]:
    name = str(profile.get("name") or "")
    if name == "micro_grid":
        reasons: list[str] = []
        if _micro_first_wave_profit_capture_ready(item, metrics, profile=profile):
            reasons.append("micro_first_wave_profit_capture_ready")
        return {
            "layer": "first_wave" if reasons else "standard",
            "reasons": reasons,
            "lock_r": profile.get("lock_r"),
            "giveback_r": profile.get("giveback_r"),
        }
    if name != "trend":
        return {"layer": "standard", "reasons": [], "lock_r": profile.get("lock_r"), "giveback_r": profile.get("giveback_r")}
    current_r = _float_or_none(item.stop_r_multiple) or 0.0
    current_progress = _float_or_none(item.target_progress) or 0.0
    recent_r = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    recent_progress = _float_or_none(metrics.get("recent_max_target_progress")) or 0.0
    best_r = max(current_r, recent_r)
    best_progress = max(current_progress, recent_progress)
    strong_ready = best_r >= _float_or_default(profile.get("strong_min_profit_r"), 1.0) or best_progress >= _float_or_default(
        profile.get("strong_min_progress"),
        0.55,
    )
    if strong_ready:
        return {
            "layer": "strong",
            "reasons": ["trend_profit_layer:strong"],
            "lock_r": _float_or_default(profile.get("strong_lock_r"), profile.get("lock_r")),
            "giveback_r": _float_or_default(profile.get("strong_giveback_r"), profile.get("giveback_r")),
        }
    defensive_ready = best_r >= _float_or_default(profile.get("defensive_min_profit_r"), 0.6) or best_progress >= _float_or_default(
        profile.get("defensive_min_progress"),
        0.3,
    )
    if defensive_ready:
        return {
            "layer": "defensive",
            "reasons": ["trend_profit_layer:defensive"],
            "lock_r": _float_or_default(profile.get("defensive_lock_r"), profile.get("lock_r")),
            "giveback_r": _float_or_default(profile.get("defensive_giveback_r"), profile.get("giveback_r")),
        }
    return {
        "layer": "observe",
        "reasons": ["trend_profit_layer:observe", "trend_profit_layer_waiting"],
        "lock_r": profile.get("lock_r"),
        "giveback_r": profile.get("giveback_r"),
    }


def _profit_giveback_detected(metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    giveback_ratio = _float_or_none(metrics.get("target_progress_giveback_ratio")) or 0.0
    threshold = _float_or_default(profile.get("giveback_ratio"), 0.45)
    return giveback_ratio >= threshold


def _flow_is_fading(metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    volume_ratio = _float_or_none(metrics.get("volume_ratio"))
    if volume_ratio is None:
        return False
    return volume_ratio <= _float_or_default(profile.get("volume_fade_ratio"), 0.75)


def _adverse_micro_reversal(metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    signed_short_return = _float_or_none(metrics.get("signed_short_return_percent")) or 0.0
    threshold = _float_or_default(profile.get("adverse_return_percent"), 0.08)
    return signed_short_return <= -abs(threshold)


def _micro_stagnation_detected(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "micro_grid":
        return False
    elapsed = _float_or_none(metrics.get("elapsed_seconds"))
    if elapsed is None or elapsed < _float_or_default(profile.get("stagnation_seconds"), 150.0):
        return False
    current_r = _float_or_none(metrics.get("current_stop_r_multiple"))
    recent_mfe = _float_or_none(metrics.get("recent_max_stop_r_multiple")) or 0.0
    max_abs_r = abs(_float_or_default(profile.get("stagnation_max_abs_r"), 0.12))
    max_mfe_r = _float_or_default(profile.get("stagnation_max_mfe_r"), 0.18)
    if current_r is None or abs(current_r) > max_abs_r or recent_mfe > max_mfe_r:
        return False
    return _flow_is_fading(metrics, profile=profile) or (_float_or_none(metrics.get("direction_alignment")) or 0.0) <= 0.5


def _micro_setup_invalidated(item, metrics: Mapping[str, Any], *, profile: Mapping[str, Any]) -> bool:
    if str(profile.get("name") or "") != "micro_grid":
        return False
    current_r = _float_or_none(metrics.get("current_stop_r_multiple")) or 0.0
    adverse_r = max(
        _float_or_none(metrics.get("recent_max_adverse_r_multiple")) or 0.0,
        -current_r,
    )
    if adverse_r < _float_or_default(profile.get("invalidation_adverse_r"), 0.18):
        return False
    alignment = _float_or_none(metrics.get("direction_alignment")) or 0.0
    alignment_threshold = _float_or_default(profile.get("invalidation_direction_alignment"), 0.25)
    volume_ratio = _float_or_none(metrics.get("volume_ratio")) or 1.0
    return _adverse_micro_reversal(metrics, profile=profile) or (
        alignment <= alignment_threshold and volume_ratio >= 1.05
    )


def _allowed_actions_from_signals(
    plan: PositionAdjustmentPlanReport,
    signals: list[ReversalRiskSignal],
) -> list[str]:
    allowed = {"backfill_protective_orders"}
    if any(signal.decision == "trail_or_backfill" for signal in signals):
        allowed.add("trail_protective_orders")
    if not plan.adjustment_allowed:
        return []
    actions = {
        item.order_plan.action
        for item in plan.plans
        if item.adjustment_allowed and item.order_plan is not None
    }
    return sorted(actions & allowed)


def _plan_with_sentinel_trailing_requests(
    config: AppConfig,
    plan: PositionAdjustmentPlanReport,
    signals: list[ReversalRiskSignal],
    *,
    market_client,
    exchange_info: Mapping[str, Any] | None,
) -> PositionAdjustmentPlanReport:
    review = plan.position_review
    if review is None:
        return plan
    forced_keys = {
        (signal.symbol.upper(), str(signal.position_side or "").upper() or None)
        for signal in signals
        if signal.decision == "trail_or_backfill"
    }
    if not forced_keys:
        return plan

    signals_by_key = {
        (signal.symbol.upper(), str(signal.position_side or "").upper() or None): signal
        for signal in signals
        if signal.decision == "trail_or_backfill"
    }
    changed = False
    positions = []
    for item in review.positions:
        key = (item.symbol.upper(), str(item.position_side or "").upper() or None)
        if (
            key in forced_keys
            and item.recommendation in {"hold", "watch", "close_review"}
            and item.algo_protection_count >= 2
            and item.matching_intent_event_id is not None
        ):
            changed = True
            signal = signals_by_key.get(key)
            sentinel_reasons = _sentinel_item_reason_codes(config, item, signal) if signal is not None else []
            positions.append(
                replace(
                    item,
                    recommendation="trail_or_reduce",
                    urgency="normal",
                    reasons=_dedupe([*item.reasons, "sentinel_reversal_risk_trailing", *sentinel_reasons]),
                )
            )
        else:
            positions.append(item)
    if not changed:
        return plan

    adjusted_review = replace(
        review,
        action_required=True,
        reasons=_dedupe([*review.reasons, "sentinel_reversal_risk_trailing"]),
        positions=positions,
    )
    filters_by_symbol = _filters_by_symbol_for_review(
        exchange_info or _exchange_info_payload(market_client),
        adjusted_review.positions,
    )
    sentinel_activate_r = min(
        _float_or_default(config.get("BFA_TRAILING_PROTECTION_ACTIVATE_R"), 0.8),
        _float_or_default(config.get("BFA_POSITION_SENTINEL_MIN_PROFIT_R"), 0.25),
    )
    return position_adjustment_plan_from_review(
        adjusted_review,
        position_mode=config.get("BFA_POSITION_MODE"),
        partial_take_profit_fraction=_float_or_default(config.get("BFA_PARTIAL_TAKE_PROFIT_FRACTION"), 0.5),
        trailing_protection_enabled=True,
        trailing_activate_r=max(sentinel_activate_r, 0.0),
        trailing_lock_r=_float_or_default(config.get("BFA_TRAILING_PROTECTION_LOCK_R"), 0.25),
        trailing_giveback_r=_float_or_default(config.get("BFA_TRAILING_PROTECTION_GIVEBACK_R"), 0.55),
        trailing_target_extension_r=_float_or_default(
            config.get("BFA_TRAILING_PROTECTION_TARGET_EXTENSION_R"),
            0.75,
        ),
        filters_by_symbol=filters_by_symbol,
        require_filters=True,
        ignore_normal_open_orders=True,
    )


def _sentinel_item_reason_codes(config: AppConfig, item, signal: ReversalRiskSignal | None) -> list[str]:
    if signal is None:
        return []
    profile = _protection_profile(config, item)
    loss_control = any(
        reason in {"stagnation_exit_pressure", "setup_invalidated_exit_pressure", "trend_degrade_loss_control_ready"}
        for reason in signal.reasons
    )
    layer = str(signal.metrics.get("profit_protection_layer") or "standard")
    layer_lock = _float_or_none(signal.metrics.get("profit_protection_lock_r"))
    layer_giveback = _float_or_none(signal.metrics.get("profit_protection_giveback_r"))
    lock_r = profile["loss_control_lock_r"] if loss_control else layer_lock if layer_lock is not None else profile["lock_r"]
    giveback_r = profile["loss_control_giveback_r"] if loss_control else layer_giveback if layer_giveback is not None else profile["giveback_r"]
    min_giveback_r = profile.get("loss_control_min_giveback_r") if loss_control else None
    target_extension_r = (
        profile["loss_control_target_extension_r"] if loss_control else profile["target_extension_r"]
    )
    if str(profile.get("name") or "") == "trend" and layer == "strong":
        min_profit_r = _float_or_default(profile.get("strong_min_profit_r"), profile["min_profit_r"])
        min_progress = _float_or_default(profile.get("strong_min_progress"), profile["min_progress"])
    elif str(profile.get("name") or "") == "trend" and layer == "defensive":
        min_profit_r = _float_or_default(profile.get("defensive_min_profit_r"), profile["min_profit_r"])
        min_progress = _float_or_default(profile.get("defensive_min_progress"), profile["min_progress"])
    else:
        min_profit_r = max(profile["min_profit_r"], profile.get("profit_protection_min_r", profile["min_profit_r"]))
        min_progress = max(profile["min_progress"], profile.get("profit_protection_min_progress", profile["min_progress"]))
    layer_reasons = [f"sentinel_trend_profit_layer:{layer}"] if str(profile.get("name") or "") == "trend" else []
    return _dedupe(
        [
            "sentinel_loss_control" if loss_control else "sentinel_profit_protection",
            *signal.reasons,
            *layer_reasons,
            f"sentinel_reversal_score:{signal.score}",
            f"sentinel_min_profit_r:{min_profit_r}",
            f"sentinel_min_target_progress:{min_progress}",
            f"sentinel_lock_r:{lock_r}",
            f"sentinel_giveback_r:{giveback_r}",
            *([f"sentinel_min_giveback_r:{min_giveback_r}"] if min_giveback_r is not None else []),
            f"sentinel_target_extension_r:{target_extension_r}",
        ]
    )


def _exchange_info_payload(market_client) -> Mapping[str, Any] | None:
    try:
        payload = market_client.exchange_info().payload
    except Exception:
        return None
    return payload if isinstance(payload, Mapping) else None


def _filters_by_symbol_for_review(exchange_info: Mapping[str, Any] | None, positions: list[Any]) -> dict[str, SymbolExecutionFilters]:
    if not exchange_info:
        return {}
    filters: dict[str, SymbolExecutionFilters] = {}
    for item in positions:
        symbol = str(item.symbol).upper()
        if symbol in filters:
            continue
        try:
            filters[symbol] = SymbolExecutionFilters.from_exchange_info(exchange_info, symbol)
        except ValueError:
            continue
    return filters


def _sentinel_reasons(
    plan: PositionAdjustmentPlanReport,
    signals: list[ReversalRiskSignal],
    allowed_actions: list[str],
    *,
    execution_enabled: bool,
    requested: bool,
) -> list[str]:
    reasons = []
    if not plan.adjustment_allowed:
        reasons.extend(plan.reasons)
    else:
        reasons.extend(
            reason
            for reason in plan.reasons
            if reason in {"normal_open_orders_ignored_for_sentinel"}
        )
    if signals:
        reasons.extend(reason for signal in signals for reason in signal.reasons)
    if requested and not execution_enabled:
        reasons.append("execution_not_enabled_by_config")
    if allowed_actions:
        reasons.extend(f"allowed_action:{action}" for action in allowed_actions)
    if not reasons:
        reasons.append("sentinel_observe_only")
    return _dedupe(reasons)


def _status(
    plan: PositionAdjustmentPlanReport,
    signals: list[ReversalRiskSignal],
    execution: PositionAdjustmentExecuteReport | None,
    *,
    execution_enabled: bool,
    allowed_actions: list[str],
) -> str:
    if execution is not None:
        return "sentinel_executed" if execution.adjustment_executed else "sentinel_execution_blocked"
    if execution_enabled and not allowed_actions:
        return "sentinel_no_allowed_action"
    if allowed_actions:
        return "sentinel_action_ready"
    if signals:
        return "sentinel_observing"
    if plan.status == "adjustment_plan_empty":
        return "sentinel_no_position"
    return "sentinel_observing"


def _report(config: AppConfig, db_path: str | None, report: PositionSentinelReport) -> PositionSentinelReport:
    path = db_path or config.get("BFA_DB_PATH")
    persisted: dict[str, int] = {}
    try:
        connection = connect(path)
        try:
            cursor = connection.execute(
                """
                INSERT INTO events (event_type, occurred_at, source, symbol, ref_id, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "position_sentinel",
                    report.checked_at,
                    "ops.position_sentinel",
                    None,
                    f"position_sentinel:{report.checked_at}",
                    _json(report.to_dict()),
                ),
            )
            connection.commit()
            persisted["position_sentinel"] = int(cursor.lastrowid)
        finally:
            connection.close()
    except Exception:
        persisted = {}
    return PositionSentinelReport(
        status=report.status,
        checked_at=report.checked_at,
        execution_enabled=report.execution_enabled,
        reasons=report.reasons,
        reversal_signals=report.reversal_signals,
        adjustment_plan=report.adjustment_plan,
        execution=report.execution,
        persisted=persisted,
    )


def _now_iso(now: str | None) -> str:
    if now:
        return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace(
            "+00:00",
            "Z",
        )
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _json(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(dict(payload), sort_keys=True, ensure_ascii=False)


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
