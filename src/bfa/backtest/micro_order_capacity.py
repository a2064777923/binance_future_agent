"""Outcome-blind admission of micro order attempts into bounded live-like capacity."""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class MicroOrderAttempt:
    """One scored order proposal plus its replay-only lifecycle timestamps.

    Admission may inspect fields through ``score`` and ``pending_until_ms``.
    ``fill_time_ms``, ``exit_time_ms``, and ``payload`` are used only after an
    attempt has been admitted, so future outcomes cannot improve its rank.
    """

    attempt_id: str
    symbol: str
    side: str
    signal_time_ms: int
    pending_until_ms: int
    score: float
    fill_time_ms: int | None = None
    exit_time_ms: int | None = None
    payload: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if self.signal_time_ms < 0 or self.pending_until_ms < self.signal_time_ms:
            raise ValueError("pending lifecycle must not precede the signal")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")
        if self.fill_time_ms is not None:
            if not self.signal_time_ms <= self.fill_time_ms <= self.pending_until_ms:
                raise ValueError("fill_time_ms must be inside the pending lifetime")
            if self.exit_time_ms is None or self.exit_time_ms < self.fill_time_ms:
                raise ValueError("a filled attempt requires exit_time_ms at or after fill")
        elif self.exit_time_ms is not None:
            raise ValueError("exit_time_ms requires fill_time_ms")


@dataclass(frozen=True)
class MicroOrderAdmissionResult:
    admitted: tuple[MicroOrderAttempt, ...]
    rejected_attempt_ids: tuple[str, ...]
    diagnostics: dict[str, int]


def admit_micro_order_attempts(
    attempts: Iterable[MicroOrderAttempt],
    *,
    max_pending_orders: int,
    max_active_intents: int,
) -> MicroOrderAdmissionResult:
    """Rank the watched universe first, then apply pending/active capacity.

    Attempts at one signal timestamp compete by score. Lifecycle outcomes are
    consulted only after admission to release a pending or open slot.
    """

    pending_limit = int(max_pending_orders)
    active_limit = int(max_active_intents)
    if pending_limit <= 0 or active_limit <= 0:
        raise ValueError("micro pending and active capacity must be positive")

    ordered = sorted(
        attempts,
        key=lambda item: (item.signal_time_ms, item.attempt_id),
    )
    admitted: list[MicroOrderAttempt] = []
    rejected: list[str] = []
    pending_events: list[tuple[int, str, MicroOrderAttempt]] = []
    open_events: list[tuple[int, str]] = []
    symbol_release_events: list[tuple[int, str, str]] = []
    occupied_attempt_by_symbol: dict[str, str] = {}
    pending_count = 0
    open_count = 0
    max_pending_observed = 0
    max_open_observed = 0
    max_active_observed = 0
    capacity_rejected_count = 0
    symbol_busy_rejected_count = 0

    def advance(now_ms: int) -> None:
        nonlocal pending_count, open_count, max_open_observed
        while pending_events and pending_events[0][0] <= now_ms:
            _pending_end, _attempt_id, item = heapq.heappop(pending_events)
            pending_count -= 1
            if item.fill_time_ms is not None and item.exit_time_ms is not None and item.exit_time_ms > now_ms:
                open_count += 1
                max_open_observed = max(max_open_observed, open_count)
                heapq.heappush(open_events, (item.exit_time_ms, item.attempt_id))
        while open_events and open_events[0][0] <= now_ms:
            heapq.heappop(open_events)
            open_count -= 1
        while symbol_release_events and symbol_release_events[0][0] <= now_ms:
            _release_ms, symbol, attempt_id = heapq.heappop(symbol_release_events)
            if occupied_attempt_by_symbol.get(symbol) == attempt_id:
                del occupied_attempt_by_symbol[symbol]

    index = 0
    while index < len(ordered):
        signal_time_ms = ordered[index].signal_time_ms
        end = index + 1
        while end < len(ordered) and ordered[end].signal_time_ms == signal_time_ms:
            end += 1
        group = ordered[index:end]
        advance(signal_time_ms)

        ranked = [
            (-item.score, item.symbol, item.side, item.attempt_id, item)
            for item in group
        ]
        heapq.heapify(ranked)
        while ranked:
            _negative_score, _symbol, _side, _attempt_id, item = heapq.heappop(ranked)
            if item.symbol in occupied_attempt_by_symbol:
                rejected.append(item.attempt_id)
                symbol_busy_rejected_count += 1
                continue
            if pending_count >= pending_limit or pending_count + open_count >= active_limit:
                rejected.append(item.attempt_id)
                capacity_rejected_count += 1
                continue

            admitted.append(item)
            release_ms = item.exit_time_ms if item.fill_time_ms is not None else item.pending_until_ms
            occupied_attempt_by_symbol[item.symbol] = item.attempt_id
            heapq.heappush(symbol_release_events, (int(release_ms), item.symbol, item.attempt_id))
            pending_end_ms = item.fill_time_ms if item.fill_time_ms is not None else item.pending_until_ms
            if pending_end_ms <= signal_time_ms:
                if item.exit_time_ms is not None and item.exit_time_ms > signal_time_ms:
                    open_count += 1
                    max_open_observed = max(max_open_observed, open_count)
                    heapq.heappush(open_events, (item.exit_time_ms, item.attempt_id))
            else:
                pending_count += 1
                heapq.heappush(pending_events, (pending_end_ms, item.attempt_id, item))
            max_pending_observed = max(max_pending_observed, pending_count)
            max_active_observed = max(max_active_observed, pending_count + open_count)
        index = end

    return MicroOrderAdmissionResult(
        admitted=tuple(admitted),
        rejected_attempt_ids=tuple(rejected),
        diagnostics={
            "watch_attempt_count": len(ordered),
            "admitted_count": len(admitted),
            "capacity_rejected_count": capacity_rejected_count,
            "symbol_busy_rejected_count": symbol_busy_rejected_count,
            "max_pending_observed": max_pending_observed,
            "max_open_observed": max_open_observed,
            "max_active_observed": max_active_observed,
        },
    )
