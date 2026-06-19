"""Persist execution artifacts."""

from __future__ import annotations

from typing import Any, Mapping

from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision


def persist_order_intent(
    store: EventStore,
    *,
    intent: OrderIntent,
    status: str,
    risk: RiskDecision,
) -> int:
    return store.insert_artifact(
        "order_intents",
        occurred_at=intent.decided_at,
        source=f"execution.{intent.mode}",
        symbol=intent.symbol,
        ref_id=f"order_intent:{intent.symbol}:{intent.decided_at}",
        payload={
            "status": status,
            "intent": intent.to_dict(),
            "risk": risk.to_dict(),
        },
        event_type="order_intent",
    )


def persist_exchange_response(
    store: EventStore,
    *,
    intent: OrderIntent,
    response: Mapping[str, Any],
    response_type: str = "new_order",
) -> int:
    return store.insert_artifact(
        "exchange_responses",
        occurred_at=intent.decided_at,
        source="binance_usdm",
        symbol=intent.symbol,
        ref_id=f"exchange_response:{response_type}:{intent.symbol}:{intent.decided_at}",
        payload={"response_type": response_type, "response": dict(response), "intent": intent.to_dict()},
        event_type="exchange_response",
    )
