"""Read-only gate for deciding whether live risk limits may be changed."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.models import RiskState
from bfa.ops.live_status import LiveStatusReport, build_live_status_report


@dataclass(frozen=True)
class SubmittedIntentWithoutOutcome:
    event_id: int
    occurred_at: str
    symbol: str
    side: str | None = None
    quantity: float | None = None
    leverage: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "leverage": self.leverage,
        }


@dataclass(frozen=True)
class RiskChangeCheckReport:
    status: str
    risk_change_allowed: bool
    reasons: list[str] = field(default_factory=list)
    account: dict[str, Any] = field(default_factory=dict)
    position_count: int = 0
    open_order_count: int = 0
    open_algo_order_count: int = 0
    openai_backoff_active: bool = False
    target_leverage: int | None = None
    current_max_leverage: float | None = None
    target_profile: dict[str, Any] | None = None
    active_exposures: list[dict[str, Any]] = field(default_factory=list)
    unreconciled_submitted_intents: list[SubmittedIntentWithoutOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "risk_change_allowed": self.risk_change_allowed,
            "reasons": list(self.reasons),
            "account": dict(self.account),
            "position_count": self.position_count,
            "open_order_count": self.open_order_count,
            "open_algo_order_count": self.open_algo_order_count,
            "openai_backoff_active": self.openai_backoff_active,
            "target_leverage": self.target_leverage,
            "current_max_leverage": self.current_max_leverage,
            "target_profile": dict(self.target_profile) if self.target_profile else None,
            "active_exposures": [dict(item) for item in self.active_exposures],
            "unreconciled_submitted_intents": [
                item.to_dict() for item in self.unreconciled_submitted_intents
            ],
        }


def build_risk_change_check_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    check_binance: bool = True,
    target_leverage: int | None = None,
    target_profile: Mapping[str, Any] | None = None,
    live_status_report: LiveStatusReport | None = None,
    signed_client: BinanceFuturesSignedClient | None = None,
) -> RiskChangeCheckReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    live_status = live_status_report or build_live_status_report(
        config,
        db_path=resolved_db_path,
        check_binance=check_binance,
        signed_client=signed_client,
    )
    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        unreconciled = unreconciled_submitted_intents(connection)
    finally:
        connection.close()
    return risk_change_check_from_live_status(
        live_status,
        unreconciled_submitted_intents=unreconciled,
        target_leverage=target_leverage,
        current_max_leverage=_float_or_none(config.get("BFA_MAX_LEVERAGE")),
        target_profile=target_profile,
    )


def risk_change_check_from_live_status(
    report: LiveStatusReport,
    *,
    unreconciled_submitted_intents: list[SubmittedIntentWithoutOutcome] | None = None,
    target_leverage: int | None = None,
    current_max_leverage: float | None = None,
    target_profile: Mapping[str, Any] | None = None,
) -> RiskChangeCheckReport:
    payload = report.to_dict()
    exchange = _mapping(payload.get("exchange_evidence"))
    has_exchange_evidence = bool(exchange)
    positions = _list(exchange.get("positions"))
    open_orders = _list(exchange.get("open_orders"))
    open_algo_orders = _list(exchange.get("open_algo_orders"))
    account = _mapping(exchange.get("account"))
    protective = _mapping(payload.get("protective_evidence"))
    backoff = _mapping(payload.get("openai_backoff"))
    unreconciled = list(unreconciled_submitted_intents or [])
    normalized_target_profile = _normalize_target_profile(target_profile)
    active_exposures = [_exposure_from_position(position) for position in positions]

    reasons: list[str] = []
    status = "risk_change_allowed"
    backoff_active = bool(backoff.get("active"))

    if not has_exchange_evidence:
        reasons.append("exchange_evidence_missing")
        status = "keep_current_profile"
    if backoff_active:
        reasons.append("ai_backoff_active")
        status = "keep_current_profile"
    if positions:
        reasons.append("active_position_present")
        protected = _positions_have_confirmed_algo_protection(positions, open_algo_orders, protective)
        profile_capacity = _target_profile_capacity(active_exposures, normalized_target_profile)
        if not protected:
            reasons.append("active_position_without_confirmed_algo_protection")
            status = "urgent_attention"
        elif profile_capacity:
            reasons.append("position_has_algo_protection")
            reasons.extend(profile_capacity)
            status = "keep_current_profile"
        elif normalized_target_profile and _target_allows_multi_position(normalized_target_profile):
            reasons.append("active_position_within_target_profile_caps")
        else:
            reasons.append("position_has_algo_protection")
            status = "keep_current_profile"
    elif open_orders or open_algo_orders:
        reasons.append("open_orders_without_position")
        status = "urgent_attention"
    if unreconciled:
        reasons.append("submitted_intents_missing_outcomes")
        if (
            positions
            and normalized_target_profile
            and _target_allows_multi_position(normalized_target_profile)
            and _unreconciled_match_active_positions(unreconciled, active_exposures)
        ):
            reasons.append("active_submitted_intent_carried_forward")
        elif status == "risk_change_allowed":
            status = "keep_current_profile"

    reasons = _dedupe(reasons)
    allowed = not _blocking_reasons(reasons)
    if allowed:
        if positions:
            status = "risk_change_allowed_with_active_position"
            reasons = _dedupe(["active_position_within_target_profile_caps", *reasons])
        else:
            reasons = ["exchange_clear_and_outcomes_reconciled"]

    return RiskChangeCheckReport(
        status=status,
        risk_change_allowed=allowed,
        reasons=reasons,
        account=dict(account),
        position_count=len(positions),
        open_order_count=len(open_orders),
        open_algo_order_count=len(open_algo_orders),
        openai_backoff_active=backoff_active,
        target_leverage=target_leverage,
        current_max_leverage=current_max_leverage,
        target_profile=dict(normalized_target_profile) if normalized_target_profile else None,
        active_exposures=active_exposures,
        unreconciled_submitted_intents=unreconciled,
    )


def unreconciled_submitted_intents(connection: sqlite3.Connection) -> list[SubmittedIntentWithoutOutcome]:
    rows = connection.execute(
        """
        SELECT event_id, occurred_at, symbol, payload_json
        FROM order_intents
        ORDER BY occurred_at ASC, id ASC
        """
    ).fetchall()
    missing: list[SubmittedIntentWithoutOutcome] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if payload.get("status") != "submitted":
            continue
        event_id = int(row["event_id"])
        if _has_closed_outcome_for_event(connection, event_id):
            continue
        intent = payload.get("intent")
        intent_payload = intent if isinstance(intent, Mapping) else {}
        missing.append(
            SubmittedIntentWithoutOutcome(
                event_id=event_id,
                occurred_at=str(row["occurred_at"]),
                symbol=str(row["symbol"] or intent_payload.get("symbol", "")).upper(),
                side=_optional_str(intent_payload.get("side")),
                quantity=_float_or_none(intent_payload.get("quantity")),
                leverage=_int_or_none(intent_payload.get("leverage")),
            )
        )
    return missing


def _has_closed_outcome_for_event(connection: sqlite3.Connection, event_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM outcomes
        WHERE ref_id = ?
        LIMIT 1
        """,
        (f"outcome:{event_id}:closed",),
    ).fetchone()
    return row is not None


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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _exposure_from_position(position: Any) -> dict[str, Any]:
    data = _mapping(position)
    amount = _float_or_none(data.get("positionAmt")) or 0.0
    position_side = str(data.get("positionSide") or "").upper()
    direction = position_side if position_side in {"LONG", "SHORT"} else "LONG" if amount > 0 else "SHORT"
    return {
        "symbol": str(data.get("symbol") or "").upper(),
        "direction": direction,
        "position_amt": amount,
        "notional_usdt": _position_notional(data),
        "initial_margin_usdt": _position_initial_margin(data),
        "leverage": _float_or_none(data.get("leverage")),
    }


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


def _normalize_target_profile(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        return {}
    return dict(profile)


def _target_allows_multi_position(profile: Mapping[str, Any]) -> bool:
    return _truthy(profile.get("BFA_MULTI_POSITION_ENABLED")) and (_int_or_none(profile.get("BFA_MAX_OPEN_POSITIONS")) or 0) > 1


def _target_profile_capacity(active_exposures: list[dict[str, Any]], profile: Mapping[str, Any]) -> list[str]:
    if not profile:
        return ["target_profile_missing"]
    reasons: list[str] = []
    max_open = _int_or_none(profile.get("BFA_MAX_OPEN_POSITIONS")) or 0
    if not _target_allows_multi_position(profile):
        reasons.append("target_profile_multi_position_disabled")
    if len(active_exposures) >= max_open:
        reasons.append("target_profile_max_open_positions_reached")

    state = RiskState(active_positions=len(active_exposures), active_exposures=active_exposures)
    max_margin = _float_or_none(profile.get("BFA_MAX_PORTFOLIO_MARGIN_USDT"))
    if max_margin is not None and state.active_initial_margin_usdt > max_margin:
        reasons.append("target_profile_portfolio_margin_cap_reached")
    capital = _float_or_none(profile.get("BFA_ACCOUNT_CAPITAL_USDT")) or 0.0
    margin_fraction = _float_or_none(profile.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION"))
    if margin_fraction is not None and capital > 0 and state.active_initial_margin_usdt > capital * margin_fraction:
        reasons.append("target_profile_portfolio_margin_fraction_reached")
    max_notional = _float_or_none(profile.get("BFA_MAX_PORTFOLIO_NOTIONAL_USDT"))
    if max_notional is not None and state.active_notional_usdt > max_notional:
        reasons.append("target_profile_portfolio_notional_cap_reached")
    same_direction_cap = _float_or_none(profile.get("BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT"))
    if same_direction_cap is not None:
        by_direction: dict[str, float] = {}
        for exposure in active_exposures:
            direction = str(exposure.get("direction") or "").upper()
            by_direction[direction] = by_direction.get(direction, 0.0) + (_float_or_none(exposure.get("notional_usdt")) or 0.0)
        for direction_total in by_direction.values():
            if direction_total > same_direction_cap:
                reasons.append("target_profile_same_direction_notional_cap_reached")
                break
    return _dedupe(reasons)


def _positions_have_confirmed_algo_protection(
    positions: list[Any],
    open_algo_orders: list[Any],
    protective: Mapping[str, Any],
) -> bool:
    if not positions or not open_algo_orders or not bool(protective.get("complete")):
        return False
    for position in positions:
        position_data = _mapping(position)
        symbol = str(position_data.get("symbol") or "").upper()
        side = str(position_data.get("positionSide") or "").upper()
        matching = [
            order
            for order in open_algo_orders
            if str(_mapping(order).get("symbol") or "").upper() == symbol
            and (not side or str(_mapping(order).get("positionSide") or "").upper() in {"", side})
        ]
        if len(matching) < 2:
            return False
    return True


def _blocking_reasons(reasons: list[str]) -> list[str]:
    reason_set = set(reasons)
    informational = {
        "active_submitted_intent_carried_forward",
        "active_position_within_target_profile_caps",
    }
    if "active_position_within_target_profile_caps" in reason_set:
        informational.update({"active_position_present", "position_has_algo_protection"})
    if "active_submitted_intent_carried_forward" in reason_set:
        informational.add("submitted_intents_missing_outcomes")
    return [reason for reason in reasons if reason not in informational]


def _unreconciled_match_active_positions(
    unreconciled: list[SubmittedIntentWithoutOutcome],
    active_exposures: list[dict[str, Any]],
) -> bool:
    active_symbols = {str(exposure.get("symbol") or "").upper() for exposure in active_exposures}
    if not active_symbols:
        return False
    return all(item.symbol.upper() in active_symbols for item in unreconciled)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
