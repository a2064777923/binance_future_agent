"""Decision orchestration and deterministic validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from bfa.ai.schema import (
    DECISION_SCHEMA_FIELDS,
    AiDecisionContext,
    AiTradeDecision,
    DecisionValidationResult,
    decision_json_schema,
)


DECISION_INSTRUCTIONS = """You evaluate one Binance USD-M futures hot-coin candidate.
Return only the requested structured JSON. You may choose pass when evidence is weak.
Never claim that an order was placed. notional_usdt means contract position notional,
not initial margin; approximate initial margin is notional_usdt divided by leverage.
Keep notional within the provided risk limits.

When quant_setup is present, audit it as an adversarial overlay before echoing
it. First ask whether direction, entry location, stop placement, and volume
follow-through are all good enough for a live futures order. If you agree with
the setup, echo its side, entry_price, stop_price, target_price, notional_usdt,
and hold_time_minutes exactly. If you disagree, return decision=pass with
side=flat and explain the veto in reasons. Your role is an overlay/veto, not
point generation.

Veto long setups when the candidate is only hot on 24h momentum but short-horizon
evidence has rolled over: price below VWAP with EMA trend down, RSI below the
long regime, negative micro momentum, close near the range low, or volume fading
against the move. Veto short setups for the mirrored condition. Also veto when
the entry appears chased late into a wick or the stop sits inside normal recent
noise; a stopped trade can still have the right direction, so distinguish
direction risk from entry/stop-quality risk in reasons.

If you choose decision=trade, you MUST provide non-null entry_price, stop_price,
target_price, notional_usdt, hold_time_minutes, and side long/short. Use the
candidate features.reference_price as the market reference when present: entry
should be close to that reference price, stop/target must form valid long or
short geometry, notional_usdt must fit both features.min_executable_notional and
max_position_notional_usdt when present, and stop risk must fit
max_risk_per_trade_usdt. If you cannot derive a complete executable setup from
the provided context, return decision=pass with side=flat and null trade
fields."""


@dataclass(frozen=True)
class AiDecisionRun:
    context: AiDecisionContext
    request_payload: dict[str, Any]
    raw_response: dict[str, Any]
    validation: DecisionValidationResult
    response_text: str
    journaled: bool = False
    persisted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.validation.accepted,
            "decision": self.validation.decision.to_dict() if self.validation.decision else None,
            "validation_errors": list(self.validation.validation_errors),
            "validation_warnings": list(self.validation.validation_warnings),
            "journaled": self.journaled,
            "persisted": self.persisted,
        }


def parse_decision_json(text: str) -> dict[str, Any]:
    candidate_text = _extract_json_text(text)
    try:
        payload = json.loads(candidate_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"decision response is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("decision response must be a JSON object")
    return payload


def _extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def validate_decision_payload(
    payload: Mapping[str, Any],
    context: AiDecisionContext,
) -> DecisionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    keys = set(payload)
    required = set(DECISION_SCHEMA_FIELDS)
    for key in sorted(required - keys):
        errors.append(f"missing_field:{key}")
    for key in sorted(keys - required):
        errors.append(f"unexpected_field:{key}")

    decision = _text(payload.get("decision"))
    side = _text(payload.get("side"))
    confidence = _float(payload.get("confidence"))
    reasons = _reasons(payload.get("reasons"))

    if decision not in {"trade", "pass"}:
        errors.append("invalid_decision")
    if side not in {"long", "short", "flat"}:
        errors.append("invalid_side")
    if confidence is not None and 1 < confidence <= 100:
        confidence = confidence / 100
        warnings.append("confidence_percent_normalized")
    if confidence is None or confidence < 0 or confidence > 1:
        errors.append("invalid_confidence")
        confidence = 0.0
    if not reasons:
        errors.append("missing_reasons")

    parsed = AiTradeDecision(
        decision=decision or "",
        side=side or "",
        confidence=float(confidence),
        entry_price=_float(payload.get("entry_price")),
        stop_price=_float(payload.get("stop_price")),
        target_price=_float(payload.get("target_price")),
        notional_usdt=_float(payload.get("notional_usdt")),
        hold_time_minutes=_int(payload.get("hold_time_minutes")),
        reasons=reasons,
    )

    if decision == "pass":
        _validate_pass(parsed, errors, warnings)
    elif decision == "trade":
        _validate_trade(parsed, context, errors)
        _validate_quant_setup_echo(parsed, context, errors)

    return DecisionValidationResult(
        accepted=not errors,
        decision=parsed,
        validation_errors=_dedupe(errors),
        validation_warnings=_dedupe(warnings),
    )


def run_ai_decision(
    *,
    client,
    context: AiDecisionContext,
    journal=None,
    store=None,
    source: str = "ai.provider",
) -> AiDecisionRun:
    response = client.create_decision(
        context.to_dict(),
        instructions=DECISION_INSTRUCTIONS,
        schema=decision_json_schema(),
    )
    try:
        payload = parse_decision_json(response.output_text)
        validation = validate_decision_payload(payload, context)
    except ValueError as exc:
        validation = DecisionValidationResult(
            accepted=False,
            decision=None,
            validation_errors=[str(exc)],
        )

    journaled = False
    if journal is not None:
        from bfa.ai.journal import build_journal_record

        journal.append(
            build_journal_record(
                context=context,
                request_payload=response.request_payload,
                raw_response=response.raw_response,
                validation=validation,
            )
        )
        journaled = True

    persisted = 0
    if store is not None:
        from bfa.ai.journal import persist_ai_decision

        persist_ai_decision(
            store,
            context=context,
            validation=validation,
            raw_response=response.raw_response,
            source=source,
        )
        persisted = 1

    return AiDecisionRun(
        context=context,
        request_payload=response.request_payload,
        raw_response=response.raw_response,
        validation=validation,
        response_text=response.output_text,
        journaled=journaled,
        persisted=persisted,
    )


def _validate_pass(
    decision: AiTradeDecision,
    errors: list[str],
    warnings: list[str],
) -> None:
    if decision.side != "flat":
        errors.append("pass_requires_flat_side")
    if any(
        value is not None
        for value in (
            decision.entry_price,
            decision.stop_price,
            decision.target_price,
            decision.notional_usdt,
        )
    ):
        warnings.append("pass_ignored_trade_prices")


def _validate_trade(
    decision: AiTradeDecision,
    context: AiDecisionContext,
    errors: list[str],
) -> None:
    if decision.side not in {"long", "short"}:
        errors.append("trade_requires_long_or_short_side")

    missing = [
        name
        for name, value in (
            ("entry_price", decision.entry_price),
            ("stop_price", decision.stop_price),
            ("target_price", decision.target_price),
            ("notional_usdt", decision.notional_usdt),
            ("hold_time_minutes", decision.hold_time_minutes),
        )
        if value is None
    ]
    for name in missing:
        errors.append(f"trade_missing_{name}")
    if missing:
        return

    assert decision.entry_price is not None
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.notional_usdt is not None
    assert decision.hold_time_minutes is not None

    if decision.hold_time_minutes <= 0:
        errors.append("invalid_hold_time")
    if min(decision.entry_price, decision.stop_price, decision.target_price, decision.notional_usdt) <= 0:
        errors.append("trade_values_must_be_positive")
        return
    if decision.side == "long" and not (decision.stop_price < decision.entry_price < decision.target_price):
        errors.append("invalid_long_price_geometry")
    if decision.side == "short" and not (decision.target_price < decision.entry_price < decision.stop_price):
        errors.append("invalid_short_price_geometry")

    risk_limits = context.risk_limits
    if decision.notional_usdt > risk_limits.max_position_notional_usdt:
        errors.append("notional_exceeds_cap")
    if decision.notional_usdt > risk_limits.account_capital_usdt * risk_limits.max_leverage:
        errors.append("notional_exceeds_leverage_cap")
    risk = estimate_stop_risk_usdt(decision)
    if risk > risk_limits.max_risk_per_trade_usdt:
        errors.append("risk_exceeds_cap")
    reference_price = _reference_price(context)
    if reference_price is not None and _entry_deviation_percent(decision.entry_price, reference_price) > 1.5:
        errors.append("entry_too_far_from_reference_price")
    min_executable_notional = _min_executable_notional(context)
    if (
        min_executable_notional is not None
        and decision.notional_usdt is not None
        and decision.notional_usdt < min_executable_notional
    ):
        errors.append("notional_below_min_executable")


def estimate_stop_risk_usdt(decision: AiTradeDecision) -> float:
    if decision.entry_price in (None, 0) or decision.stop_price is None or decision.notional_usdt is None:
        return 0.0
    stop_distance = abs(decision.entry_price - decision.stop_price) / decision.entry_price
    return decision.notional_usdt * stop_distance


def _validate_quant_setup_echo(
    decision: AiTradeDecision,
    context: AiDecisionContext,
    errors: list[str],
) -> None:
    setup = context.quant_setup
    if not isinstance(setup, Mapping):
        return
    if setup.get("decision") != "trade":
        errors.append("quant_setup_not_trade")
        return
    if _text(setup.get("side")) != decision.side:
        errors.append("quant_setup_side_mismatch")
    checks = {
        "entry_price": decision.entry_price,
        "stop_price": decision.stop_price,
        "target_price": decision.target_price,
        "notional_usdt": decision.notional_usdt,
    }
    for key, actual in checks.items():
        expected = _float(setup.get(key))
        if expected is None or actual is None:
            continue
        tolerance = max(abs(expected) * 0.000001, 0.00000001)
        if abs(actual - expected) > tolerance:
            errors.append(f"quant_setup_{key}_mismatch")
    hold_time = _int(setup.get("hold_time_minutes"))
    if hold_time is not None and decision.hold_time_minutes != hold_time:
        errors.append("quant_setup_hold_time_mismatch")


def _reference_price(context: AiDecisionContext) -> float | None:
    features = context.candidate.get("features")
    if not isinstance(features, Mapping):
        return None
    reference = _float(features.get("reference_price"))
    if reference is None or reference <= 0:
        return None
    return reference


def _min_executable_notional(context: AiDecisionContext) -> float | None:
    features = context.candidate.get("features")
    if not isinstance(features, Mapping):
        return None
    value = _float(features.get("min_executable_notional"))
    if value is None or value <= 0:
        return None
    return value


def _entry_deviation_percent(entry_price: float | None, reference_price: float) -> float:
    if entry_price is None or reference_price <= 0:
        return 0.0
    return abs(entry_price - reference_price) / reference_price * 100.0


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _reasons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
