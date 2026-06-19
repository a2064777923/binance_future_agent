"""Deterministic replay packet helpers."""

from __future__ import annotations

from typing import Any

from bfa.event_store.store import EventStore


def build_replay_packet(
    store: EventStore,
    *,
    start: str,
    end: str,
    symbol: str | None = None,
) -> dict[str, Any]:
    events = store.events_between(start, end, symbol=symbol)
    symbols = sorted({event.symbol for event in events if event.symbol})
    return {
        "start": start,
        "end": end,
        "symbol": symbol,
        "event_count": len(events),
        "symbols": symbols,
        "records": [event.to_dict() for event in events],
    }

