"""Read-only exposure and sizing status for live risk conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.sizing import (
    PositionSizingResult,
    compute_position_sizing,
    dynamic_sizing_enabled,
    multi_position_enabled,
    sizing_input_from_config,
)
from bfa.ops.live_status import LiveStatusReport, build_live_status_report
from bfa.ops.risk_change_check import RiskChangeCheckReport, build_risk_change_check_report
from bfa.ops.risk_profile import RiskProfilePlan, build_risk_profile_plan


@dataclass(frozen=True)
class DirectionSupport:
    long_entries_supported: bool
    short_entries_supported: bool
    long_order_side: str
    short_order_side: str
    long_position_side: str | None
    short_position_side: str | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "long_entries_supported": self.long_entries_supported,
            "short_entries_supported": self.short_entries_supported,
            "long_order_side": self.long_order_side,
            "short_order_side": self.short_order_side,
            "long_position_side": self.long_position_side,
            "short_position_side": self.short_position_side,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class EntryCapacity:
    status: str
    can_open_new_position: bool
    reasons: list[str]
    active_position_count: int
    max_open_positions: int
    multi_position_enabled: bool
    active_notional_usdt: float = 0.0
    active_initial_margin_usdt: float = 0.0
    max_portfolio_notional_usdt: float | None = None
    max_portfolio_margin_usdt: float | None = None
    active_exposures: list[dict[str, Any]] = field(default_factory=list)
    hypothetical: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "can_open_new_position": self.can_open_new_position,
            "reasons": list(self.reasons),
            "active_position_count": self.active_position_count,
            "max_open_positions": self.max_open_positions,
            "multi_position_enabled": self.multi_position_enabled,
            "active_notional_usdt": self.active_notional_usdt,
            "active_initial_margin_usdt": self.active_initial_margin_usdt,
            "max_portfolio_notional_usdt": self.max_portfolio_notional_usdt,
            "max_portfolio_margin_usdt": self.max_portfolio_margin_usdt,
            "active_exposures": [dict(item) for item in self.active_exposures],
            "hypothetical": dict(self.hypothetical) if self.hypothetical else None,
        }


@dataclass(frozen=True)
class ExposureStatusReport:
    status: str
    current_profile: dict[str, Any]
    current_sizing: PositionSizingResult
    direction_support: DirectionSupport
    entry_capacity: EntryCapacity
    exchange_summary: dict[str, Any]
    target_profile: RiskProfilePlan | None = None
    target_sizing: PositionSizingResult | None = None
    risk_change: RiskChangeCheckReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "current_profile": dict(self.current_profile),
            "current_sizing": self.current_sizing.to_dict(),
            "direction_support": self.direction_support.to_dict(),
            "entry_capacity": self.entry_capacity.to_dict(),
            "exchange_summary": dict(self.exchange_summary),
            "target_profile": self.target_profile.to_dict() if self.target_profile else None,
            "target_sizing": self.target_sizing.to_dict() if self.target_sizing else None,
            "risk_change": self.risk_change.to_dict() if self.risk_change else None,
        }


def build_exposure_status_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    signed_client: BinanceFuturesSignedClient | None = None,
    target_profile: str | None = "30u_10x_multi_dynamic",
    allow_two_positions: bool = False,
    hypothetical_symbol: str | None = None,
    hypothetical_side: str | None = None,
) -> ExposureStatusReport:
    live_status = build_live_status_report(
        config,
        db_path=db_path,
        check_binance=check_binance,
        signed_client=signed_client,
    )
    exchange = _mapping(live_status.exchange_evidence)
    available_balance = _available_balance(exchange)
    current_sizing = compute_position_sizing(
        sizing_input_from_config(config, available_balance_usdt=available_balance),
        enabled=dynamic_sizing_enabled(config),
    )
    target_plan = (
        build_risk_profile_plan(
            config,
            profile=target_profile,
            allow_two_positions=allow_two_positions,
        )
        if target_profile
        else None
    )
    target_sizing = (
        compute_position_sizing(
            sizing_input_from_config(
                AppConfig(values={**config.values, **target_plan.target_values}),
                available_balance_usdt=available_balance,
            ),
            enabled=True,
        )
        if target_plan
        else None
    )
    risk_change = (
        build_risk_change_check_report(
            config,
            db_path=db_path,
            check_binance=check_binance,
            target_leverage=target_plan.target_leverage,
            target_profile=target_plan.target_values,
            live_status_report=live_status,
            signed_client=signed_client if check_binance else None,
        )
        if target_plan
        else None
    )
    direction_support = _direction_support(config)
    entry_capacity = _entry_capacity(
        config,
        live_status=live_status,
        hypothetical_symbol=hypothetical_symbol,
        hypothetical_side=hypothetical_side,
    )
    return ExposureStatusReport(
        status=_status(entry_capacity, risk_change),
        current_profile=_profile_dict(config, current_sizing),
        current_sizing=current_sizing,
        direction_support=direction_support,
        entry_capacity=entry_capacity,
        exchange_summary=_exchange_summary(live_status),
        target_profile=target_plan,
        target_sizing=target_sizing,
        risk_change=risk_change,
    )


def _profile_dict(config: AppConfig, sizing: PositionSizingResult) -> dict[str, Any]:
    return {
        "mode": config.get("BFA_MODE"),
        "account_capital_usdt": _float_or_none(config.get("BFA_ACCOUNT_CAPITAL_USDT")),
        "max_leverage": _float_or_none(config.get("BFA_MAX_LEVERAGE")),
        "max_position_notional_usdt": sizing.max_position_notional_usdt,
        "max_position_margin_usdt": sizing.max_position_margin_usdt,
        "max_portfolio_margin_usdt": _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")),
        "max_portfolio_margin_fraction": _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")),
        "max_portfolio_notional_usdt": _float_or_none(config.get("BFA_MAX_PORTFOLIO_NOTIONAL_USDT")),
        "max_same_direction_notional_usdt": _float_or_none(config.get("BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT")),
        "max_risk_per_trade_usdt": _float_or_none(config.get("BFA_MAX_RISK_PER_TRADE_USDT")),
        "max_daily_loss_usdt": _float_or_none(config.get("BFA_MAX_DAILY_LOSS_USDT")),
        "max_open_positions": _int_or_default(config.get("BFA_MAX_OPEN_POSITIONS"), 0),
        "dynamic_position_sizing_enabled": dynamic_sizing_enabled(config),
        "multi_position_enabled": multi_position_enabled(config),
        "margin_mode": config.get("BFA_MARGIN_MODE"),
        "position_mode": config.get("BFA_POSITION_MODE"),
    }


def _direction_support(config: AppConfig) -> DirectionSupport:
    hedge_mode = config.get("BFA_POSITION_MODE").strip().lower() == "hedge"
    notes = ["short_entries_require_valid_short_geometry"]
    if hedge_mode:
        notes.append("hedge_mode_sends_explicit_position_side")
    else:
        notes.append("one_way_mode_omits_position_side")
    return DirectionSupport(
        long_entries_supported=True,
        short_entries_supported=True,
        long_order_side="BUY",
        short_order_side="SELL",
        long_position_side="LONG" if hedge_mode else None,
        short_position_side="SHORT" if hedge_mode else None,
        notes=notes,
    )


def _entry_capacity(
    config: AppConfig,
    *,
    live_status: LiveStatusReport,
    hypothetical_symbol: str | None,
    hypothetical_side: str | None,
) -> EntryCapacity:
    exchange = _mapping(live_status.exchange_evidence)
    positions = _list(exchange.get("positions"))
    active_exposures = [_exposure_from_position(position) for position in positions]
    active_exposures = [item for item in active_exposures if item]
    max_open = _int_or_default(config.get("BFA_MAX_OPEN_POSITIONS"), 0)
    multi_enabled = multi_position_enabled(config)
    active_notional = sum(_float_or_none(item.get("notional_usdt")) or 0.0 for item in active_exposures)
    active_margin = sum(_exposure_margin(item) for item in active_exposures)
    max_portfolio_notional = _float_or_none(config.get("BFA_MAX_PORTFOLIO_NOTIONAL_USDT"))
    max_portfolio_margin = min(
        _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")) or 0.0,
        (_float_or_none(config.get("BFA_ACCOUNT_CAPITAL_USDT")) or 0.0)
        * (_float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")) or 0.0),
    )
    reasons: list[str] = []
    has_exchange_evidence = bool(exchange)

    if not has_exchange_evidence:
        reasons.append("exchange_evidence_missing")
    if positions and not multi_enabled:
        reasons.append("multi_position_disabled")
    if len(positions) >= max_open:
        reasons.append("max_open_positions_reached")
    if max_portfolio_notional is not None and active_notional >= max_portfolio_notional:
        reasons.append("portfolio_notional_cap_reached")
    if max_portfolio_margin > 0 and active_margin >= max_portfolio_margin:
        reasons.append("portfolio_margin_cap_reached")

    hypothetical = _hypothetical_capacity(
        active_exposures,
        multi_enabled=multi_enabled,
        symbol=hypothetical_symbol,
        side=hypothetical_side,
    )
    if hypothetical and not hypothetical["accepted"]:
        reasons.extend(str(reason) for reason in hypothetical["reasons"])

    reasons = _dedupe(reasons)
    can_open = not reasons
    if not has_exchange_evidence:
        status = "unknown"
        can_open = False
    elif can_open:
        status = "entry_capacity_available"
        reasons = ["entry_capacity_available"]
    else:
        status = "entry_capacity_blocked"

    return EntryCapacity(
        status=status,
        can_open_new_position=can_open,
        reasons=reasons,
        active_position_count=len(positions),
        max_open_positions=max_open,
        multi_position_enabled=multi_enabled,
        active_notional_usdt=round(active_notional, 8),
        active_initial_margin_usdt=round(active_margin, 8),
        max_portfolio_notional_usdt=max_portfolio_notional,
        max_portfolio_margin_usdt=round(max_portfolio_margin, 8) if max_portfolio_margin > 0 else None,
        active_exposures=active_exposures,
        hypothetical=hypothetical,
    )


def _hypothetical_capacity(
    active_exposures: list[dict[str, Any]],
    *,
    multi_enabled: bool,
    symbol: str | None,
    side: str | None,
) -> dict[str, Any] | None:
    if not symbol or not side:
        return None
    normalized_side = side.strip().lower()
    direction = "LONG" if normalized_side == "long" else "SHORT" if normalized_side == "short" else ""
    reasons: list[str] = []
    if not direction:
        reasons.append("unsupported_hypothetical_side")
    for exposure in active_exposures:
        if (
            str(exposure.get("symbol", "")).upper() == symbol.upper()
            and str(exposure.get("direction", "")).upper() == direction
        ):
            reasons.append("duplicate_symbol_direction_exposure")
            break
    if active_exposures and not multi_enabled:
        reasons.append("multi_position_disabled")
    return {
        "symbol": symbol.upper(),
        "side": normalized_side,
        "order_side": "BUY" if direction == "LONG" else "SELL" if direction == "SHORT" else None,
        "direction": direction or None,
        "accepted": not reasons,
        "reasons": _dedupe(reasons or ["hypothetical_capacity_available"]),
    }


def _exposure_from_position(position: Any) -> dict[str, Any]:
    data = _mapping(position)
    amount = _float_or_none(data.get("positionAmt")) or 0.0
    position_side = str(data.get("positionSide") or "").upper()
    direction = position_side if position_side in {"LONG", "SHORT"} else "LONG" if amount > 0 else "SHORT"
    return {
        "symbol": str(data.get("symbol") or "").upper(),
        "direction": direction,
        "position_amt": amount,
        "entry_price": _float_or_none(data.get("entryPrice")),
        "mark_price": _float_or_none(data.get("markPrice")),
        "notional_usdt": _position_notional(data),
        "initial_margin_usdt": _position_initial_margin(data),
        "leverage": _float_or_none(data.get("leverage")),
        "unrealized_pnl_usdt": _float_or_none(data.get("unRealizedProfit")),
    }


def _exchange_summary(live_status: LiveStatusReport) -> dict[str, Any]:
    exchange = _mapping(live_status.exchange_evidence)
    account = _mapping(exchange.get("account"))
    return {
        "exchange_evidence_present": bool(exchange),
        "available_balance_usdt": _float_or_none(account.get("available_balance")),
        "total_wallet_balance_usdt": _float_or_none(account.get("total_wallet_balance")),
        "position_count": len(_list(exchange.get("positions"))),
        "open_order_count": len(_list(exchange.get("open_orders"))),
        "open_algo_order_count": len(_list(exchange.get("open_algo_orders"))),
        "openai_backoff_active": live_status.openai_backoff.active,
    }


def _status(entry_capacity: EntryCapacity, risk_change: RiskChangeCheckReport | None) -> str:
    if entry_capacity.status == "unknown":
        return "exchange_evidence_missing"
    if risk_change and risk_change.risk_change_allowed:
        return "ready_for_profile_switch"
    if entry_capacity.can_open_new_position:
        return "current_profile_entry_capacity_available"
    return "keep_current_profile"


def _available_balance(exchange: Mapping[str, Any]) -> float | None:
    account = _mapping(exchange.get("account"))
    return _float_or_none(account.get("available_balance"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_notional(data: Mapping[str, Any]) -> float:
    notional = _float_or_none(data.get("notional"))
    if notional is not None:
        return abs(notional)
    amount = abs(_float_or_none(data.get("positionAmt")) or 0.0)
    mark = _float_or_none(data.get("markPrice")) or _float_or_none(data.get("entryPrice")) or 0.0
    return round(abs(amount * mark), 8)


def _position_initial_margin(data: Mapping[str, Any]) -> float:
    margin = _float_or_none(data.get("initialMargin"))
    if margin is not None:
        return abs(margin)
    leverage = _float_or_none(data.get("leverage")) or 0.0
    if leverage <= 0:
        return 0.0
    return round(_position_notional(data) / leverage, 8)


def _exposure_margin(item: Mapping[str, Any]) -> float:
    margin = _float_or_none(item.get("initial_margin_usdt"))
    if margin is not None:
        return margin
    leverage = _float_or_none(item.get("leverage")) or 0.0
    if leverage <= 0:
        return 0.0
    return (_float_or_none(item.get("notional_usdt")) or 0.0) / leverage


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
