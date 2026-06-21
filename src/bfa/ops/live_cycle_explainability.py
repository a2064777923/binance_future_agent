"""Read-only live cycle explainability and ledger cadence report."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any, Mapping

from bfa.config import AppConfig
from bfa.event_store.migrations import connect, migrate
from bfa.execution.sizing import (
    compute_position_sizing,
    dynamic_sizing_enabled,
    sizing_input_from_config,
)
from bfa.ops.live_outcome_ledger import build_live_outcome_ledger_report


_SINGULAR_TABLES = {"candidates", "trade_setups", "ai_decisions", "order_intents"}
_CAP_REASON_CODES = {
    "below_min_executable_notional",
    "effective_notional_cap",
    "margin_fraction_cap",
    "notional_exceeds_cap",
    "portfolio_margin_cap_reached",
    "portfolio_margin_fraction_reached",
    "portfolio_notional_cap_reached",
    "risk_exceeds_cap",
    "same_direction_notional_cap_reached",
    "stop_risk_cap",
}


@dataclass(frozen=True)
class LiveCycleExplainabilityReport:
    status: str
    reasons: list[str]
    filters: dict[str, Any]
    manual_symbols: list[str]
    summary: dict[str, Any]
    cycles: list[dict[str, Any]] = field(default_factory=list)
    ledger: dict[str, Any] | None = None
    mutation_proof: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bfa_live_cycle_explainability_v1",
            "status": self.status,
            "reasons": list(self.reasons),
            "filters": dict(self.filters),
            "manual_symbols": list(self.manual_symbols),
            "summary": dict(self.summary),
            "cycles": [dict(item) for item in self.cycles],
            "ledger": dict(self.ledger) if self.ledger else None,
            "mutation_proof": dict(self.mutation_proof),
        }


def build_live_cycle_explainability_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    since: str | None = None,
    latest_cycles: int = 10,
    include_ledger: bool = True,
    reconcile: bool = False,
    persist_closed: bool = False,
    signed_client=None,
) -> LiveCycleExplainabilityReport:
    resolved_db_path = db_path or config.get("BFA_DB_PATH")
    cycle_limit = max(0, latest_cycles)
    filters = {
        "since": since,
        "latest_cycles": cycle_limit,
        "include_ledger": include_ledger,
        "reconcile": reconcile,
        "persist_closed": persist_closed,
    }

    ledger_payload = None
    if include_ledger:
        ledger = build_live_outcome_ledger_report(
            config,
            db_path=resolved_db_path,
            since=since,
            latest_limit=max(1, cycle_limit or 1),
            min_group_outcomes=1,
            reconcile=reconcile,
            persist_closed=persist_closed,
            signed_client=signed_client if reconcile else None,
        )
        ledger_payload = ledger.to_dict()

    connection = connect(resolved_db_path)
    try:
        migrate(connection)
        artifacts = _load_artifacts(connection, since=since, latest_cycles=max(cycle_limit, 1))
    finally:
        connection.close()

    manual_symbols = config.get_list("BFA_MANUAL_POSITION_SYMBOLS")
    cycles = _build_cycles(artifacts, config=config, manual_symbols=manual_symbols, latest_cycles=cycle_limit)
    summary = _summary(cycles=cycles, ledger=ledger_payload)
    status = _status(cycles=cycles, ledger=ledger_payload)
    return LiveCycleExplainabilityReport(
        status=status,
        reasons=_reasons(cycles=cycles, ledger=ledger_payload, include_ledger=include_ledger),
        filters=filters,
        manual_symbols=manual_symbols,
        summary=summary,
        cycles=cycles,
        ledger=ledger_payload,
        mutation_proof=_mutation_proof(persist_closed=persist_closed),
    )


def _load_artifacts(
    connection: sqlite3.Connection,
    *,
    since: str | None,
    latest_cycles: int,
) -> dict[str, list[dict[str, Any]]]:
    row_limit = max(200, latest_cycles * 50)
    return {
        "position_lifecycle": _position_lifecycle_artifacts(connection, since=since, limit=row_limit),
        "candidates": _table_artifacts(connection, "candidates", since=since, limit=row_limit),
        "trade_setups": _table_artifacts(connection, "trade_setups", since=since, limit=row_limit),
        "ai_decisions": _table_artifacts(connection, "ai_decisions", since=since, limit=row_limit),
        "order_intents": _table_artifacts(connection, "order_intents", since=since, limit=row_limit),
        "exchange_responses": _table_artifacts(connection, "exchange_responses", since=since, limit=row_limit),
        "outcomes": _table_artifacts(connection, "outcomes", since=since, limit=row_limit),
    }


def _position_lifecycle_artifacts(
    connection: sqlite3.Connection,
    *,
    since: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists(connection, "risk_state"):
        return []
    where = "WHERE r.occurred_at >= ?" if since else ""
    params: list[Any] = [since] if since else []
    params.append(limit)
    rows = connection.execute(
        f"""
        SELECT r.id, r.event_id, r.occurred_at, r.source, r.symbol, r.ref_id, r.payload_json,
               e.event_type
        FROM risk_state r
        LEFT JOIN events e ON e.id = r.event_id
        {where}
        ORDER BY r.occurred_at DESC, r.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    artifacts = []
    for row in rows:
        item = _artifact_from_row("risk_state", row)
        payload = _mapping(item.get("payload"))
        if row["event_type"] == "position_lifecycle_decision" or payload.get("schema") == "bfa_position_lifecycle_decision_v1":
            artifacts.append(item)
    return artifacts


def _table_artifacts(
    connection: sqlite3.Connection,
    table: str,
    *,
    since: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    where = "WHERE occurred_at >= ?" if since else ""
    params: list[Any] = [since] if since else []
    params.append(limit)
    rows = connection.execute(
        f"""
        SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
        FROM {table}
        {where}
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_artifact_from_row(table, row) for row in rows]


def _build_cycles(
    artifacts: dict[str, list[dict[str, Any]]],
    *,
    config: AppConfig,
    manual_symbols: list[str],
    latest_cycles: int,
) -> list[dict[str, Any]]:
    cycles: dict[str, dict[str, Any]] = {}
    order_intents_by_event_id = {
        int(item["event_id"]): item
        for item in artifacts.get("order_intents", [])
        if item.get("event_id") is not None
    }

    for table in ("candidates", "trade_setups", "ai_decisions", "order_intents", "exchange_responses"):
        for artifact in artifacts.get(table, []):
            symbol, decided_at = _artifact_symbol_decided_at(artifact, table)
            cycle = _cycle_for(cycles, symbol=symbol, decided_at=decided_at or artifact["occurred_at"])
            _add_artifact(cycle, table, artifact)

    for outcome in artifacts.get("outcomes", []):
        symbol, decided_at = _outcome_symbol_decided_at(outcome, order_intents_by_event_id)
        cycle = _cycle_for(cycles, symbol=symbol, decided_at=decided_at or outcome["occurred_at"])
        cycle.setdefault("outcomes", []).append(outcome)

    for lifecycle in artifacts.get("position_lifecycle", []):
        decided_at = str(_mapping(lifecycle.get("payload")).get("decided_at") or lifecycle["occurred_at"])
        matching = [cycle for cycle in cycles.values() if cycle.get("decided_at") == decided_at]
        if not matching:
            matching = [_cycle_for(cycles, symbol=None, decided_at=decided_at, prefix="lifecycle")]
        for cycle in matching:
            cycle.setdefault("position_lifecycle", []).append(lifecycle)

    rendered = [
        _render_cycle(cycle, config=config, manual_symbols=manual_symbols)
        for cycle in cycles.values()
    ]
    rendered.sort(
        key=lambda item: (
            str(item.get("decided_at") or ""),
            int(_mapping(item.get("trace_ids")).get("order_intent_event_id") or 0),
        ),
        reverse=True,
    )
    return rendered[:latest_cycles] if latest_cycles else []


def _cycle_for(
    cycles: dict[str, dict[str, Any]],
    *,
    symbol: str | None,
    decided_at: str,
    prefix: str = "cycle",
) -> dict[str, Any]:
    normalized_symbol = symbol.upper() if symbol else None
    key = f"{prefix}:{normalized_symbol or '<none>'}:{decided_at}"
    if key not in cycles:
        cycles[key] = {"symbol": normalized_symbol, "decided_at": decided_at}
    elif normalized_symbol and not cycles[key].get("symbol"):
        cycles[key]["symbol"] = normalized_symbol
    return cycles[key]


def _add_artifact(cycle: dict[str, Any], table: str, artifact: dict[str, Any]) -> None:
    if table in _SINGULAR_TABLES:
        cycle.setdefault(table, artifact)
        return
    cycle.setdefault(table, []).append(artifact)


def _render_cycle(
    cycle: Mapping[str, Any],
    *,
    config: AppConfig,
    manual_symbols: list[str],
) -> dict[str, Any]:
    symbol = str(cycle.get("symbol") or "").upper() or None
    manual_symbol = symbol in set(manual_symbols) if symbol else False
    candidate = _mapping(cycle.get("candidates"))
    trade_setup = _mapping(cycle.get("trade_setups"))
    ai_decision = _mapping(cycle.get("ai_decisions"))
    order_intent = _mapping(cycle.get("order_intents"))
    exchange_responses = [_mapping(item) for item in _list(cycle.get("exchange_responses"))]
    outcomes = [_mapping(item) for item in _list(cycle.get("outcomes"))]
    lifecycle = [_mapping(item) for item in _list(cycle.get("position_lifecycle"))]
    risk = _order_risk(order_intent)
    setup = _setup_payload(trade_setup)
    validation = _ai_validation(ai_decision)
    submitted_status = order_intent.get("payload", {}).get("status") if order_intent else None

    payload = {
        "cycle_key": _cycle_key(symbol=symbol, decided_at=str(cycle.get("decided_at") or "")),
        "decided_at": cycle.get("decided_at"),
        "symbol": symbol,
        "manual_symbol": manual_symbol,
        "bot_managed": (not manual_symbol) if symbol else None,
        "side": _cycle_side(setup=setup, validation=validation, order_intent=order_intent),
        "candidate": _candidate_summary(candidate),
        "trade_setup": _trade_setup_summary(setup),
        "ai_decision": _ai_decision_summary(validation),
        "risk": {
            "accepted": risk.get("accepted"),
            "reason_codes": list(_list(risk.get("reason_codes"))),
            "warnings": list(_list(risk.get("warnings"))),
        },
        "order": {
            "status": submitted_status,
            "submitted": submitted_status == "submitted",
            "intent": _intent_summary(order_intent),
        },
        "exchange_responses": [_exchange_response_summary(item) for item in exchange_responses],
        "outcomes": [_outcome_summary(item) for item in outcomes],
        "position_lifecycle": _lifecycle_summary(lifecycle, manual_symbols=manual_symbols),
        "sizing_explanation": _sizing_explanation(
            config,
            candidate=candidate,
            setup=setup,
            validation=validation,
            order_intent=order_intent,
            risk=risk,
        ),
        "trace_ids": _trace_ids(
            candidate=candidate,
            trade_setup=trade_setup,
            ai_decision=ai_decision,
            order_intent=order_intent,
            exchange_responses=exchange_responses,
            outcomes=outcomes,
            lifecycle=lifecycle,
        ),
    }
    payload["evidence_quality"] = _evidence_quality(payload)
    return payload


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = _mapping(candidate.get("payload"))
    if not payload:
        return None
    return {
        "event_id": candidate.get("event_id"),
        "score": payload.get("score"),
        "reason_codes": list(_list(payload.get("reason_codes"))),
        "features": _mapping(payload.get("features")),
    }


def _trade_setup_summary(setup: Mapping[str, Any]) -> dict[str, Any] | None:
    if not setup:
        return None
    return {
        "decision": setup.get("decision"),
        "side": setup.get("side"),
        "entry_price": setup.get("entry_price"),
        "stop_price": setup.get("stop_price"),
        "target_price": setup.get("target_price"),
        "notional_usdt": setup.get("notional_usdt"),
        "hold_time_minutes": setup.get("hold_time_minutes"),
        "long_score": setup.get("long_score"),
        "short_score": setup.get("short_score"),
        "edge_score": setup.get("edge_score"),
        "regime": setup.get("regime"),
        "risk_reward_ratio": setup.get("risk_reward_ratio"),
        "stop_distance_percent": setup.get("stop_distance_percent"),
        "target_distance_percent": setup.get("target_distance_percent"),
        "price_basis": _mapping(setup.get("price_basis")),
        "factor_scores": [_factor_summary(item) for item in _list(setup.get("factor_scores"))],
        "reasons": list(_list(setup.get("reasons"))),
        "warnings": list(_list(setup.get("warnings"))),
    }


def _factor_summary(item: Any) -> dict[str, Any]:
    factor = _mapping(item)
    return {
        "name": factor.get("name"),
        "score": factor.get("score"),
        "weighted_score": factor.get("weighted_score"),
        "reasons": list(_list(factor.get("reasons"))),
    }


def _ai_decision_summary(validation: Mapping[str, Any]) -> dict[str, Any] | None:
    if not validation:
        return None
    decision = _mapping(validation.get("decision"))
    return {
        "accepted": validation.get("accepted"),
        "decision": decision.get("decision"),
        "side": decision.get("side"),
        "confidence": decision.get("confidence"),
        "entry_price": decision.get("entry_price"),
        "stop_price": decision.get("stop_price"),
        "target_price": decision.get("target_price"),
        "notional_usdt": decision.get("notional_usdt"),
        "hold_time_minutes": decision.get("hold_time_minutes"),
        "reasons": list(_list(decision.get("reasons"))),
        "validation_errors": list(_list(validation.get("validation_errors"))),
        "validation_warnings": list(_list(validation.get("validation_warnings"))),
    }


def _intent_summary(order_intent: Mapping[str, Any]) -> dict[str, Any] | None:
    intent = _mapping(_mapping(order_intent.get("payload")).get("intent"))
    if not intent:
        return None
    return {
        "event_id": order_intent.get("event_id"),
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "quantity": intent.get("quantity"),
        "notional_usdt": intent.get("notional_usdt"),
        "entry_price": intent.get("entry_price"),
        "stop_price": intent.get("stop_price"),
        "target_price": intent.get("target_price"),
        "leverage": intent.get("leverage"),
        "decided_at": intent.get("decided_at"),
        "metadata": _mapping(intent.get("metadata")),
    }


def _exchange_response_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(response.get("payload"))
    body = _mapping(payload.get("response"))
    return {
        "event_id": response.get("event_id"),
        "response_type": payload.get("response_type"),
        "has_entry_order": "entry_order" in body,
        "has_stop_loss_order": "stop_loss_order" in body,
        "has_take_profit_order": "take_profit_order" in body,
        "error_keys": sorted(key for key in body if str(key).endswith("_error") or key == "margin_error"),
    }


def _outcome_summary(outcome: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(outcome.get("payload"))
    return {
        "event_id": outcome.get("event_id"),
        "status": payload.get("status"),
        "net_realized_pnl_usdt": payload.get("net_realized_pnl_usdt"),
        "gross_realized_pnl_usdt": payload.get("gross_realized_pnl_usdt"),
        "commission_usdt": payload.get("commission_usdt"),
        "exit_reason": payload.get("exit_reason"),
        "first_trade_time": payload.get("first_trade_time"),
        "last_trade_time": payload.get("last_trade_time"),
    }


def _lifecycle_summary(lifecycle: list[Mapping[str, Any]], *, manual_symbols: list[str]) -> dict[str, Any] | None:
    if not lifecycle:
        return None
    latest = lifecycle[0]
    payload = _mapping(latest.get("payload"))
    diagnostics = [_mapping(item) for item in _list(payload.get("diagnostics"))]
    manual = []
    for item in diagnostics:
        symbol = str(item.get("symbol") or "").upper()
        if item.get("manual_symbol") or symbol in manual_symbols:
            manual.append(
                {
                    "symbol": symbol,
                    "lifecycle_decision": item.get("lifecycle_decision"),
                    "recommendation": item.get("recommendation"),
                    "reasons": list(_list(item.get("reasons")) or _list(item.get("failed_preconditions"))),
                    "bot_managed": False,
                    "manual_symbol": True,
                }
            )
    return {
        "event_id": latest.get("event_id"),
        "status": payload.get("status"),
        "reasons": list(_list(payload.get("reasons"))),
        "manual_position_symbols": list(_list(payload.get("manual_position_symbols"))),
        "auto_management": _mapping(payload.get("auto_management")),
        "manual_diagnostics": manual,
        "diagnostic_count": len(diagnostics),
    }


def _sizing_explanation(
    config: AppConfig,
    *,
    candidate: Mapping[str, Any],
    setup: Mapping[str, Any],
    validation: Mapping[str, Any],
    order_intent: Mapping[str, Any],
    risk: Mapping[str, Any],
) -> dict[str, Any]:
    decision = _mapping(validation.get("decision"))
    intent = _mapping(_mapping(order_intent.get("payload")).get("intent"))
    candidate_payload = _mapping(candidate.get("payload"))
    entry_price = _first_number(setup.get("entry_price"), decision.get("entry_price"), intent.get("entry_price"))
    stop_price = _first_number(setup.get("stop_price"), decision.get("stop_price"), intent.get("stop_price"))
    sizing = compute_position_sizing(
        sizing_input_from_config(
            config,
            candidate=candidate_payload,
            entry_price=entry_price,
            stop_price=stop_price,
        ),
        enabled=dynamic_sizing_enabled(config),
    )
    risk_reasons = [str(item) for item in _list(risk.get("reason_codes"))]
    setup_warnings = [str(item) for item in _list(setup.get("warnings"))]
    limiting_factors = _dedupe(
        [
            *[str(item) for item in sizing.reasons],
            *[str(item) for item in sizing.warnings],
            *[item for item in setup_warnings if item in _CAP_REASON_CODES],
            *[item for item in risk_reasons if item in _CAP_REASON_CODES],
        ]
    )
    return {
        "dynamic_sizing_enabled": sizing.enabled,
        "max_position_notional_usdt": sizing.max_position_notional_usdt,
        "fixed_max_notional_usdt": sizing.fixed_max_notional_usdt,
        "max_position_margin_usdt": sizing.max_position_margin_usdt,
        "entry_price_used": entry_price,
        "stop_price_used": stop_price,
        "limiting_factors": limiting_factors,
        "sizing_reasons": list(sizing.reasons),
        "sizing_warnings": list(sizing.warnings),
        "risk_reasons": risk_reasons,
        "configured_caps": {
            "account_capital_usdt": _float_or_none(config.get("BFA_ACCOUNT_CAPITAL_USDT")),
            "max_leverage": _float_or_none(config.get("BFA_MAX_LEVERAGE")),
            "max_risk_per_trade_usdt": _float_or_none(config.get("BFA_MAX_RISK_PER_TRADE_USDT")),
            "max_position_notional_usdt": _float_or_none(config.get("BFA_MAX_POSITION_NOTIONAL_USDT")),
            "max_effective_notional_usdt": _float_or_none(config.get("BFA_MAX_EFFECTIVE_NOTIONAL_USDT")),
            "max_margin_per_position_usdt": _float_or_none(config.get("BFA_MAX_MARGIN_PER_POSITION_USDT")),
            "max_margin_fraction": _float_or_none(config.get("BFA_MAX_MARGIN_FRACTION")),
            "max_portfolio_margin_usdt": _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")),
            "max_portfolio_margin_fraction": _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")),
            "max_portfolio_notional_usdt": _float_or_none(config.get("BFA_MAX_PORTFOLIO_NOTIONAL_USDT")),
            "max_same_direction_notional_usdt": _float_or_none(config.get("BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT")),
        },
    }


def _trace_ids(
    *,
    candidate: Mapping[str, Any],
    trade_setup: Mapping[str, Any],
    ai_decision: Mapping[str, Any],
    order_intent: Mapping[str, Any],
    exchange_responses: list[Mapping[str, Any]],
    outcomes: list[Mapping[str, Any]],
    lifecycle: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "candidate_event_id": candidate.get("event_id"),
        "trade_setup_event_id": trade_setup.get("event_id"),
        "ai_decision_event_id": ai_decision.get("event_id"),
        "order_intent_event_id": order_intent.get("event_id"),
        "exchange_response_event_ids": [
            item.get("event_id")
            for item in exchange_responses
            if item.get("event_id") is not None
        ],
        "outcome_event_ids": [
            item.get("event_id")
            for item in outcomes
            if item.get("event_id") is not None
        ],
        "position_lifecycle_event_ids": [
            item.get("event_id")
            for item in lifecycle
            if item.get("event_id") is not None
        ],
    }


def _evidence_quality(cycle: Mapping[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    if not cycle.get("symbol"):
        notes.append("symbol_missing")
    if not cycle.get("decided_at"):
        notes.append("decided_at_missing")
    if cycle.get("candidate") is None:
        notes.append("missing_candidate")
    if cycle.get("trade_setup") is None:
        notes.append("missing_trade_setup")
    setup = _mapping(cycle.get("trade_setup"))
    if setup.get("decision") == "trade" and cycle.get("ai_decision") is None:
        notes.append("missing_ai_decision")
    if cycle.get("order", {}).get("intent") is None:
        notes.append("no_order_intent")
    if cycle.get("order", {}).get("submitted") and not cycle.get("exchange_responses"):
        notes.append("missing_exchange_response")
    if cycle.get("position_lifecycle") is not None and cycle.get("candidate") is None and cycle.get("order", {}).get("intent") is None:
        notes.append("lifecycle_only_cycle")
    return {
        "stable_grouping": bool(cycle.get("symbol") and cycle.get("decided_at")),
        "notes": _dedupe(notes),
    }


def _summary(*, cycles: list[dict[str, Any]], ledger: dict[str, Any] | None) -> dict[str, Any]:
    submitted = [item for item in cycles if item.get("order", {}).get("submitted")]
    no_order = [item for item in cycles if item.get("order", {}).get("intent") is None]
    risk_blocked = [
        item
        for item in cycles
        if item.get("risk", {}).get("accepted") is False
        and item.get("order", {}).get("intent") is not None
    ]
    manual_cycles = [item for item in cycles if item.get("manual_symbol")]
    return {
        "cycle_count": len(cycles),
        "submitted_cycle_count": len(submitted),
        "no_order_cycle_count": len(no_order),
        "risk_blocked_cycle_count": len(risk_blocked),
        "manual_symbol_cycle_count": len(manual_cycles),
        "ledger_status": ledger.get("status") if ledger else None,
        "ledger_outcome_count": _mapping(ledger.get("summary") if ledger else {}).get("outcome_count"),
    }


def _reasons(*, cycles: list[dict[str, Any]], ledger: dict[str, Any] | None, include_ledger: bool) -> list[str]:
    reasons = []
    if cycles:
        reasons.append("live_cycle_explainability_ready")
    else:
        reasons.append("live_cycle_evidence_missing")
    if include_ledger:
        if ledger and ledger.get("status") == "ledger_blocked":
            reasons.extend([str(item) for item in _list(ledger.get("reasons"))])
        elif ledger:
            reasons.append("ledger_cadence_included")
    return _dedupe(reasons)


def _status(*, cycles: list[dict[str, Any]], ledger: dict[str, Any] | None) -> str:
    if ledger and ledger.get("status") == "ledger_blocked":
        return "explainability_blocked"
    if cycles:
        return "explainability_ready"
    return "no_live_cycles"


def _mutation_proof(*, persist_closed: bool) -> dict[str, bool]:
    return {
        "places_orders": False,
        "cancels_orders": False,
        "mutates_exchange_state": False,
        "changes_margin_or_leverage": False,
        "writes_env_files": False,
        "changes_systemd_state": False,
        "raises_risk": False,
        "applies_guard_changes": False,
        "exchange_mutation": False,
        "env_systemd_risk_guard_mutation": False,
        "persists_closed_fills_and_outcomes": bool(persist_closed),
        "local_event_store_closed_outcome_persistence": bool(persist_closed),
    }


def _artifact_symbol_decided_at(artifact: Mapping[str, Any], table: str) -> tuple[str | None, str | None]:
    payload = _mapping(artifact.get("payload"))
    if table == "candidates":
        return _from_ref(str(artifact.get("ref_id") or ""), "candidate")
    if table == "trade_setups":
        symbol, decided_at = _from_ref(str(artifact.get("ref_id") or ""), "trade_setup")
        setup = _setup_payload(artifact)
        return symbol or _str_or_none(setup.get("symbol")) or _str_or_none(artifact.get("symbol")), decided_at
    if table == "ai_decisions":
        return _from_ref(str(artifact.get("ref_id") or ""), "ai_decision")
    if table == "order_intents":
        intent = _mapping(payload.get("intent"))
        return (
            _str_or_none(intent.get("symbol")) or _str_or_none(artifact.get("symbol")),
            _str_or_none(intent.get("decided_at")) or _str_or_none(artifact.get("occurred_at")),
        )
    if table == "exchange_responses":
        intent = _mapping(payload.get("intent"))
        symbol = _str_or_none(intent.get("symbol")) or _str_or_none(artifact.get("symbol"))
        decided_at = _str_or_none(intent.get("decided_at"))
        if symbol and decided_at:
            return symbol, decided_at
        return _from_exchange_ref(str(artifact.get("ref_id") or ""))
    return _str_or_none(artifact.get("symbol")), _str_or_none(artifact.get("occurred_at"))


def _outcome_symbol_decided_at(
    outcome: Mapping[str, Any],
    order_intents_by_event_id: Mapping[int, Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    payload = _mapping(outcome.get("payload"))
    outcome_intent = _mapping(payload.get("intent"))
    event_id = _int_or_none(outcome_intent.get("event_id"))
    if event_id is not None and event_id in order_intents_by_event_id:
        return _artifact_symbol_decided_at(order_intents_by_event_id[event_id], "order_intents")
    return (
        _str_or_none(payload.get("symbol")) or _str_or_none(outcome_intent.get("symbol")) or _str_or_none(outcome.get("symbol")),
        _str_or_none(outcome_intent.get("occurred_at"))
        or _str_or_none(payload.get("first_trade_time"))
        or _str_or_none(outcome.get("occurred_at")),
    )


def _from_ref(ref_id: str, prefix: str) -> tuple[str | None, str | None]:
    marker = f"{prefix}:"
    if not ref_id.startswith(marker):
        return None, None
    rest = ref_id[len(marker) :]
    if ":" not in rest:
        return None, None
    symbol, decided_at = rest.split(":", 1)
    return symbol.upper() if symbol else None, decided_at or None


def _from_exchange_ref(ref_id: str) -> tuple[str | None, str | None]:
    marker = "exchange_response:"
    if not ref_id.startswith(marker):
        return None, None
    parts = ref_id[len(marker) :].split(":", 2)
    if len(parts) != 3:
        return None, None
    return parts[1].upper() if parts[1] else None, parts[2] or None


def _setup_payload(trade_setup: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(trade_setup.get("payload"))
    return _mapping(payload.get("setup")) or payload


def _ai_validation(ai_decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(ai_decision.get("payload"))
    return _mapping(payload.get("validation"))


def _order_risk(order_intent: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(_mapping(order_intent.get("payload")).get("risk"))


def _cycle_side(
    *,
    setup: Mapping[str, Any],
    validation: Mapping[str, Any],
    order_intent: Mapping[str, Any],
) -> str | None:
    decision = _mapping(validation.get("decision"))
    intent = _mapping(_mapping(order_intent.get("payload")).get("intent"))
    side = setup.get("side") or decision.get("side") or intent.get("side")
    if str(side).upper() == "BUY":
        return "long"
    if str(side).upper() == "SELL":
        return "short"
    return str(side).lower() if side else None


def _cycle_key(*, symbol: str | None, decided_at: str) -> str:
    return f"{symbol or '<none>'}:{decided_at}"


def _artifact_from_row(table: str, row: sqlite3.Row) -> dict[str, Any]:
    return {
        "table": table,
        "id": int(row["id"]),
        "event_id": int(row["event_id"]) if row["event_id"] is not None else None,
        "occurred_at": str(row["occurred_at"]),
        "source": row["source"],
        "symbol": str(row["symbol"]).upper() if row["symbol"] else None,
        "ref_id": row["ref_id"],
        "payload": json.loads(str(row["payload_json"])),
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_or_none(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text if text else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


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


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
