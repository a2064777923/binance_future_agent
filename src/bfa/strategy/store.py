"""Persist generated strategy candidates."""

from __future__ import annotations

from bfa.event_store.store import EventStore
from bfa.strategy.candidates import CandidateSignal


def persist_candidates(store: EventStore, candidates: list[CandidateSignal]) -> list[int]:
    event_ids: list[int] = []
    for candidate in candidates:
        event_ids.append(
            store.insert_artifact(
                "candidates",
                occurred_at=candidate.generated_at,
                source="strategy.hot_coin",
                symbol=candidate.symbol,
                ref_id=f"candidate:{candidate.symbol}:{candidate.generated_at}",
                payload=candidate.to_dict(),
                event_type="candidate",
            )
        )
    return event_ids

