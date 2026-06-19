"""Deterministic risk gates for order intents."""

from __future__ import annotations

from pathlib import Path

from bfa.ai.decision import estimate_stop_risk_usdt
from bfa.ai.schema import AiTradeDecision, DecisionValidationResult, RiskLimits
from bfa.config import AppConfig, RuntimeMode
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import OrderIntent, RiskDecision, RiskState


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
        reason_codes=list(decision.reasons),
        metadata={
            "ai_confidence": decision.confidence,
            "ai_side": decision.side,
            "hold_time_minutes": decision.hold_time_minutes,
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
    if risk_state.active_positions >= risk_limits.max_open_positions:
        reasons.append("max_open_positions_reached")
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


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
