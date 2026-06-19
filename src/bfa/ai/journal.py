"""Secret-safe journaling and persistence for AI decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from bfa.ai.schema import AiDecisionContext, DecisionValidationResult
from bfa.event_store.store import EventStore
from bfa.redaction import redact_object


class AiDecisionJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact_object(dict(record)), sort_keys=True, ensure_ascii=False))
            handle.write("\n")


def build_journal_record(
    *,
    context: AiDecisionContext,
    request_payload: Mapping[str, Any],
    raw_response: Mapping[str, Any],
    validation: DecisionValidationResult,
) -> dict[str, Any]:
    return {
        "record_type": "ai_decision",
        "occurred_at": context.decided_at,
        "symbol": context.candidate.get("symbol"),
        "context": context.to_dict(),
        "request": dict(request_payload),
        "response": dict(raw_response),
        "validation": validation.to_dict(),
    }


def persist_ai_decision(
    store: EventStore,
    *,
    context: AiDecisionContext,
    validation: DecisionValidationResult,
    raw_response: Mapping[str, Any],
) -> int:
    symbol = context.candidate.get("symbol")
    payload = {
        "context": context.to_dict(),
        "validation": validation.to_dict(),
        "response": redact_object(dict(raw_response)),
    }
    return store.insert_artifact(
        "ai_decisions",
        occurred_at=context.decided_at,
        source="openai.responses",
        symbol=str(symbol) if symbol else None,
        ref_id=f"ai_decision:{symbol}:{context.decided_at}" if symbol else f"ai_decision:{context.decided_at}",
        payload=payload,
        event_type="ai_decision",
    )
