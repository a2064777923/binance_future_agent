"""Event store result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StoredEvent:
    id: int
    event_type: str
    occurred_at: str
    source: str | None
    symbol: str | None
    ref_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "source": self.source,
            "symbol": self.symbol,
            "ref_id": self.ref_id,
            "payload": dict(self.payload),
        }

