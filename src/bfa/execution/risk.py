"""Deterministic risk gates for order intents."""

from __future__ import annotations

from pathlib import Path

from bfa.ai.decision import estimate_stop_risk_usdt
from bfa.ai.schema import AiTradeDecision, DecisionValidationResult, RiskLimits
from bfa.config import AppConfig, RuntimeMode
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import OrderIntent, RiskDecision, RiskState
from bfa.execution.sizing import multi_position_enabled


def intent_from_ai_decision(
    *,
    symbol: str,
    validation: DecisionValidationResult,
    risk_limits: RiskLimits,
    mode: RuntimeMode,
    decided_at: str,
    filters: SymbolExecutionFilters | None = None,
) -> tuple[OrderIntent | None, RiskDecision]:
    if not validation.accepted or validation.decision is None:
        return None, RiskDecision(False, ["ai_decision_not_accepted"])
    decision = validation.decision
    if decision.decision != "trade":
        return None, RiskDecision(False, ["ai_decision_pass"])
    missing = [
        decision.entry_price,
        decision.stop_price,
        decision.target_price,
        decision.notional_usdt,
    ]
    if any(value is None for value in missing):
        return None, RiskDecision(False, ["trade_decision_missing_prices"])

    assert decision.entry_price is not None
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.notional_usdt is not None
    quantity = decision.notional_usdt / decision.entry_price
    entry_price = decision.entry_price
    stop_price = decision.stop_price
    target_price = decision.target_price
    notional = decision.notional_usdt
    filter_rejections: list[str] = []
    if filters is not None:
        filtered = filters.apply(
            quantity=quantity,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )
        quantity = filtered.quantity
        entry_price = filtered.entry_price
        stop_price = filtered.stop_price
        target_price = filtered.target_price
        notional = filtered.notional_usdt
        filter_rejections = filtered.rejection_reasons

    intent = OrderIntent(
        symbol=symbol.upper(),
        side=_order_side(decision),
        quantity=quantity,
        notional_usdt=notional,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        leverage=int(risk_limits.max_leverage),
        mode=mode.value,
        decided_at=decided_at,
        order_type=_entry_order_type(decision.reasons),
        time_in_force=_entry_time_in_force(decision.reasons),
        limit_wait_seconds=_entry_limit_wait_seconds(decision.reasons),
        reason_codes=list(decision.reasons),
        metadata={
            "ai_confidence": decision.confidence,
            "ai_side": decision.side,
            "hold_time_minutes": decision.hold_time_minutes,
            **_route_metadata_from_reasons(decision.reasons),
        },
    )
    if filter_rejections:
        return intent, RiskDecision(False, filter_rejections)
    return intent, RiskDecision(True, ["intent_created"])


def evaluate_risk(
    *,
    intent: OrderIntent | None,
    validation: DecisionValidationResult,
    risk_limits: RiskLimits,
    risk_state: RiskState,
    mode: RuntimeMode,
    config: AppConfig,
    now: str,
) -> RiskDecision:
    reasons: list[str] = []
    warnings: list[str] = []

    if not validation.accepted:
        reasons.append("ai_decision_not_accepted")
    if validation.decision is not None and validation.decision.decision == "pass":
        reasons.append("ai_decision_pass")
    if intent is None:
        reasons.append("missing_order_intent")
        return RiskDecision(False, _dedupe(reasons), warnings)

    if intent.notional_usdt > risk_limits.max_position_notional_usdt:
        reasons.append("notional_exceeds_cap")
    if intent.leverage > risk_limits.max_leverage:
        reasons.append("leverage_exceeds_cap")
    if risk_state.daily_loss_usdt >= risk_limits.max_daily_loss_usdt:
        reasons.append("daily_loss_cap_reached")
    if not multi_position_enabled(config) and risk_state.active_positions >= 1:
        reasons.append("multi_position_disabled")
    if risk_state.active_positions >= _effective_max_open_positions(intent, risk_limits, config):
        reasons.append("max_open_positions_reached")
    if _duplicate_exposure(intent, risk_state):
        reasons.append("duplicate_symbol_direction_exposure")
    if _same_symbol_opposite_exposure(intent, risk_state) and not _same_symbol_opposite_positions_enabled(config):
        reasons.append("same_symbol_opposite_exposure_blocked")
    if _portfolio_margin_after_entry(intent, risk_state) > _float_config(config, "BFA_MAX_PORTFOLIO_MARGIN_USDT"):
        reasons.append("portfolio_margin_cap_reached")
    portfolio_margin_fraction_cap = _float_config(config, "BFA_ACCOUNT_CAPITAL_USDT") * _float_config(
        config,
        "BFA_MAX_PORTFOLIO_MARGIN_FRACTION",
    )
    if _portfolio_margin_after_entry(intent, risk_state) > portfolio_margin_fraction_cap:
        reasons.append("portfolio_margin_fraction_reached")
    if (
        risk_state.account_available_balance_usdt is not None
        and intent.estimated_initial_margin_usdt > risk_state.account_available_balance_usdt
    ):
        reasons.append("account_available_balance_insufficient")
    if risk_state.manual_initial_margin_usdt > 0:
        warnings.append("manual_margin_pressure_included")
    if _portfolio_notional_after_entry(intent, risk_state) > _float_config(config, "BFA_MAX_PORTFOLIO_NOTIONAL_USDT"):
        reasons.append("portfolio_notional_cap_reached")
    if _same_direction_notional_after_entry(intent, risk_state) > _effective_same_direction_notional_cap(intent, config):
        reasons.append("same_direction_notional_cap_reached")
    if risk_state.cooldown_until and now < risk_state.cooldown_until:
        reasons.append("cooldown_active")

    decision = validation.decision
    if decision is not None:
        stop_risk = estimate_stop_risk_usdt(decision)
        if stop_risk > risk_limits.max_risk_per_trade_usdt:
            reasons.append("risk_exceeds_cap")

    if mode is RuntimeMode.LIVE:
        if _kill_switch_active(config.get("BFA_KILL_SWITCH_FILE")):
            reasons.append("kill_switch_active")
        if not config.get("BINANCE_API_KEY") or not config.get("BINANCE_API_SECRET"):
            reasons.append("missing_binance_credentials")
        if config.get("BINANCE_USE_TESTNET").lower() in {"1", "true", "yes"}:
            warnings.append("live_mode_with_testnet_flag")

    return RiskDecision(not reasons, _dedupe(reasons or ["risk_accepted"]), warnings)


def _kill_switch_active(path: str) -> bool:
    return bool(path) and Path(path).exists()


def _order_side(decision: AiTradeDecision) -> str:
    if decision.side == "long":
        return "BUY"
    if decision.side == "short":
        return "SELL"
    raise ValueError(f"unsupported trade side: {decision.side}")


def _entry_order_type(reasons: list[str]) -> str:
    values = _reason_values(reasons)
    order_type = values.get("entry_order_type", "market").strip().upper()
    if order_type == "LIMIT":
        return "LIMIT"
    return "MARKET"


def _entry_time_in_force(reasons: list[str]) -> str | None:
    if _entry_order_type(reasons) != "LIMIT":
        return None
    values = _reason_values(reasons)
    return values.get("entry_time_in_force", "GTX").strip().upper() or "GTX"


def _entry_limit_wait_seconds(reasons: list[str]) -> int | None:
    if _entry_order_type(reasons) != "LIMIT":
        return None
    values = _reason_values(reasons)
    try:
        parsed = int(float(values.get("limit_entry_max_wait_seconds", "45")))
    except (TypeError, ValueError):
        parsed = 45
    return max(1, min(parsed, 90))


def _reason_values(reasons: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for reason in reasons:
        if ":" not in reason:
            continue
        key, value = reason.split(":", 1)
        values[key] = value
    return values


def _route_metadata_from_reasons(reasons: list[str]) -> dict[str, str]:
    values = _reason_values(reasons)
    return {
        key: str(values[key]).strip()
        for key in ("strategy_leg", "regime_label", "route_decision")
        if key in values and str(values[key]).strip()
    }


def _duplicate_exposure(intent: OrderIntent, risk_state: RiskState) -> bool:
    intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
    for exposure in risk_state.active_exposures:
        symbol = str(exposure.get("symbol", "")).upper()
        direction = str(exposure.get("direction", "")).upper()
        if symbol == intent.symbol.upper() and direction == intended_direction:
            return True
    return False


def _same_symbol_opposite_exposure(intent: OrderIntent, risk_state: RiskState) -> bool:
    intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
    opposite_direction = "SHORT" if intended_direction == "LONG" else "LONG"
    for exposure in risk_state.active_exposures:
        symbol = str(exposure.get("symbol", "")).upper()
        direction = str(exposure.get("direction", "")).upper()
        if symbol == intent.symbol.upper() and direction == opposite_direction:
            return True
    return False


def _same_symbol_opposite_positions_enabled(config: AppConfig) -> bool:
    return str(config.get("BFA_ALLOW_SAME_SYMBOL_OPPOSITE_POSITIONS")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _effective_max_open_positions(intent: OrderIntent, risk_limits: RiskLimits, config: AppConfig) -> int:
    max_open = int(risk_limits.max_open_positions)
    if _is_micro_grid_intent(intent):
        max_open += max(_int_config(config, "BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS"), 0)
    return max_open


def _effective_same_direction_notional_cap(intent: OrderIntent, config: AppConfig) -> float:
    cap = _float_config(config, "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT")
    if _is_micro_grid_intent(intent):
        cap += max(_float_config(config, "BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT"), 0.0)
    return cap


def _is_micro_grid_intent(intent: OrderIntent) -> bool:
    metadata = intent.metadata if isinstance(intent.metadata, dict) else {}
    leg = str(metadata.get("strategy_leg") or "").strip().lower()
    regime = str(metadata.get("regime_label") or "").strip().upper()
    reasons = [str(reason).strip().lower() for reason in intent.reason_codes]
    return leg == "micro_grid" or regime == "RANGE" or any(reason == "strategy_leg:micro_grid" for reason in reasons)


def _portfolio_margin_after_entry(intent: OrderIntent, risk_state: RiskState) -> float:
    return risk_state.active_initial_margin_usdt + intent.estimated_initial_margin_usdt


def _portfolio_notional_after_entry(intent: OrderIntent, risk_state: RiskState) -> float:
    return risk_state.active_notional_usdt + intent.notional_usdt


def _same_direction_notional_after_entry(intent: OrderIntent, risk_state: RiskState) -> float:
    intended_direction = "LONG" if intent.side.upper() == "BUY" else "SHORT"
    total = intent.notional_usdt
    for exposure in risk_state.active_exposures:
        if str(exposure.get("direction", "")).upper() == intended_direction:
            total += _float_or_zero(exposure.get("notional_usdt"))
    return total


def _float_config(config: AppConfig, key: str) -> float:
    return _float_or_zero(config.get(key))


def _int_config(config: AppConfig, key: str) -> int:
    try:
        return int(config.get(key))
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
