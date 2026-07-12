"""Incremental, shadow-safe near-BBO scalping opportunity model.

This module only scores public market data.  It has no exchange client and no
order side effects.  The interface separates a broad watch universe from the
small pending-order capacity returned by :meth:`rank_opportunities`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import heapq
import math
from typing import Any


@dataclass(frozen=True)
class NearBboConfig:
    observation_window_ms: int = 5_000
    fast_window_ms: int = 1_000
    quote_ttl_ms: int = 5_000
    max_book_age_ms: int = 1_000
    max_trade_age_ms: int = 1_500
    max_pending_orders: int = 3
    min_trade_events: int = 5
    min_top_notional_usdt: float = 1_000.0
    min_spread_bps: float = 0.05
    max_spread_bps: float = 8.0
    min_direction_score: float = 0.20
    min_fill_probability: float = 0.15
    min_win_probability: float = 0.60
    min_conditional_net_ev_bps: float = 0.50
    max_abs_momentum_bps: float = 12.0
    queue_ahead_fraction: float = 1.0
    maker_entry_fee_bps: float = 2.0
    maker_exit_fee_bps: float = 2.0
    taker_exit_fee_bps: float = 4.0
    taker_exit_probability: float = 0.35
    exit_slippage_bps: float = 0.5
    min_target_bps: float = 12.0
    max_target_bps: float = 30.0
    stop_to_target_ratio: float = 0.75

    def __post_init__(self) -> None:
        positive_ints = (
            self.observation_window_ms,
            self.fast_window_ms,
            self.quote_ttl_ms,
            self.max_book_age_ms,
            self.max_trade_age_ms,
            self.max_pending_orders,
            self.min_trade_events,
        )
        if any(value <= 0 for value in positive_ints):
            raise ValueError("near-BBO timing, capacity, and sample controls must be positive")
        if self.fast_window_ms > self.observation_window_ms:
            raise ValueError("fast_window_ms cannot exceed observation_window_ms")
        if not 0.0 <= self.taker_exit_probability <= 1.0:
            raise ValueError("taker_exit_probability must be between zero and one")
        if self.max_spread_bps < self.min_spread_bps:
            raise ValueError("max_spread_bps cannot be below min_spread_bps")
        if self.max_target_bps < self.min_target_bps:
            raise ValueError("max_target_bps cannot be below min_target_bps")

    @property
    def expected_round_trip_cost_bps(self) -> float:
        taker_weight = _clip(self.taker_exit_probability, 0.0, 1.0)
        expected_exit_fee = (
            self.maker_exit_fee_bps * (1.0 - taker_weight)
            + self.taker_exit_fee_bps * taker_weight
        )
        return max(0.0, self.maker_entry_fee_bps) + max(0.0, expected_exit_fee) + max(0.0, self.exit_slippage_bps)


@dataclass(frozen=True)
class NearBboProposal:
    symbol: str
    side: str
    generated_at_ms: int
    expires_at_ms: int
    entry_price: float
    target_price: float
    stop_price: float
    spread_bps: float
    fill_probability: float
    win_probability: float
    conditional_net_ev_bps: float
    fill_weighted_ev_bps: float
    target_bps: float
    stop_bps: float
    queue_ahead_quantity: float
    reason_codes: tuple[str, ...]
    features: dict[str, float | int | str]


@dataclass
class _TradeBucket:
    open_time_ms: int
    first_price: float
    last_price: float
    high_price: float
    low_price: float
    taker_buy_quantity: float = 0.0
    taker_sell_quantity: float = 0.0
    trade_count: int = 0

    def update(self, *, price: float, quantity: float, taker_buy: bool) -> None:
        self.last_price = price
        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        if taker_buy:
            self.taker_buy_quantity += quantity
        else:
            self.taker_sell_quantity += quantity
        self.trade_count += 1


@dataclass
class _SymbolState:
    symbol: str
    bid_price: float | None = None
    bid_quantity: float | None = None
    ask_price: float | None = None
    ask_quantity: float | None = None
    book_event_time_ms: int | None = None
    latest_trade_time_ms: int | None = None
    trade_buckets: deque[_TradeBucket] = field(default_factory=deque)


class NearBboUniverse:
    """Maintain bounded per-second flow state and rank a broad symbol watchlist."""

    def __init__(self, config: NearBboConfig) -> None:
        self.config = config
        self._states: dict[str, _SymbolState] = {}

    def ingest_book_ticker(
        self,
        *,
        symbol: str,
        event_time_ms: int,
        bid_price: float,
        bid_quantity: float,
        ask_price: float,
        ask_quantity: float,
    ) -> bool:
        normalized = symbol.upper()
        if (
            not normalized
            or event_time_ms < 0
            or bid_price <= 0
            or ask_price <= bid_price
            or bid_quantity <= 0
            or ask_quantity <= 0
        ):
            return False
        state = self._states.setdefault(normalized, _SymbolState(symbol=normalized))
        if state.book_event_time_ms is not None and event_time_ms < state.book_event_time_ms:
            return False
        state.bid_price = float(bid_price)
        state.bid_quantity = float(bid_quantity)
        state.ask_price = float(ask_price)
        state.ask_quantity = float(ask_quantity)
        state.book_event_time_ms = int(event_time_ms)
        return True

    def ingest_trade(
        self,
        *,
        symbol: str,
        event_time_ms: int,
        price: float,
        quantity: float,
        taker_buy: bool,
    ) -> bool:
        normalized = symbol.upper()
        if not normalized or event_time_ms < 0 or price <= 0 or quantity <= 0:
            return False
        state = self._states.setdefault(normalized, _SymbolState(symbol=normalized))
        second_ms = event_time_ms // 1_000 * 1_000
        bucket = self._bucket_for_second(state, second_ms, price)
        bucket.update(price=float(price), quantity=float(quantity), taker_buy=bool(taker_buy))
        state.latest_trade_time_ms = max(state.latest_trade_time_ms or event_time_ms, int(event_time_ms))
        self._prune(state, latest_event_ms=state.latest_trade_time_ms)
        return True

    def rank_opportunities(
        self,
        *,
        now_ms: int,
        excluded_symbols: set[str] | None = None,
        capacity: int | None = None,
    ) -> tuple[list[NearBboProposal], dict[str, Any]]:
        excluded = {symbol.upper() for symbol in (excluded_symbols or set())}
        pending_capacity = max(0, min(self.config.max_pending_orders, capacity if capacity is not None else self.config.max_pending_orders))
        rejection_counts: dict[str, int] = {}
        ranked: list[tuple[float, str, NearBboProposal]] = []
        for symbol, state in self._states.items():
            self._prune(state, latest_event_ms=now_ms)
            if symbol in excluded:
                _increment(rejection_counts, "symbol_already_active")
                continue
            proposal, rejection = self._proposal(state, now_ms=now_ms)
            if proposal is None:
                _increment(rejection_counts, rejection or "no_opportunity")
                continue
            ranked.append((proposal.fill_weighted_ev_bps, symbol, proposal))

        selected = [item[2] for item in heapq.nlargest(pending_capacity, ranked, key=lambda item: (item[0], item[1]))]
        selected.sort(key=lambda item: (-item.fill_weighted_ev_bps, item.symbol))
        return selected, {
            "watch_symbol_count": len(self._states),
            "evaluated_symbol_count": len(self._states) - len(excluded.intersection(self._states)),
            "eligible_count": len(ranked),
            "selected_count": len(selected),
            "pending_capacity": pending_capacity,
            "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda item: (-item[1], item[0]))),
        }

    def symbol_diagnostics(self, symbol: str) -> dict[str, int | None]:
        state = self._states.get(symbol.upper())
        if state is None:
            return {"trade_bucket_count": 0, "trade_event_count": 0, "latest_trade_time_ms": None}
        return {
            "trade_bucket_count": len(state.trade_buckets),
            "trade_event_count": sum(bucket.trade_count for bucket in state.trade_buckets),
            "latest_trade_time_ms": state.latest_trade_time_ms,
        }

    def _proposal(self, state: _SymbolState, *, now_ms: int) -> tuple[NearBboProposal | None, str | None]:
        config = self.config
        if state.book_event_time_ms is None or state.bid_price is None or state.ask_price is None:
            return None, "missing_book"
        if now_ms - state.book_event_time_ms > config.max_book_age_ms:
            return None, "stale_book"
        if state.latest_trade_time_ms is None or now_ms - state.latest_trade_time_ms > config.max_trade_age_ms:
            return None, "stale_trades"
        bid_price = state.bid_price
        ask_price = state.ask_price
        bid_quantity = state.bid_quantity or 0.0
        ask_quantity = state.ask_quantity or 0.0
        mid_price = (bid_price + ask_price) / 2.0
        spread_bps = (ask_price - bid_price) / mid_price * 10_000.0
        if spread_bps < config.min_spread_bps:
            return None, "spread_below_min"
        if spread_bps > config.max_spread_bps:
            return None, "spread_above_max"
        if min(bid_price * bid_quantity, ask_price * ask_quantity) < config.min_top_notional_usdt:
            return None, "top_notional_below_min"

        slow = _window_stats(state.trade_buckets, now_ms - config.observation_window_ms)
        fast = _window_stats(state.trade_buckets, now_ms - config.fast_window_ms)
        if slow["trade_count"] < config.min_trade_events:
            return None, "insufficient_trade_events"
        if fast["quantity"] <= 0:
            return None, "insufficient_fast_flow"
        momentum_bps = _price_change_bps(float(slow["first_price"]), float(slow["last_price"]))
        if abs(momentum_bps) > config.max_abs_momentum_bps:
            return None, "momentum_too_large"

        total_top = bid_quantity + ask_quantity
        imbalance_signed = ((bid_quantity / total_top) - 0.5) * 2.0 if total_top > 0 else 0.0
        microprice = (ask_price * bid_quantity + bid_price * ask_quantity) / total_top
        half_spread = max((ask_price - bid_price) / 2.0, mid_price * 1e-9)
        microprice_signed = _clip((microprice - mid_price) / half_spread, -1.0, 1.0)
        slow_flow = _signed_flow(slow)
        fast_flow = _signed_flow(fast)
        flow_change = _clip((fast_flow - slow_flow) * 2.0, -1.0, 1.0)
        direction_score = _clip(
            imbalance_signed * 0.50 + flow_change * 0.30 + microprice_signed * 0.20,
            -1.0,
            1.0,
        )
        if abs(direction_score) < config.min_direction_score:
            return None, "direction_score_below_min"
        side = "long" if direction_score > 0 else "short"
        side_sign = 1.0 if side == "long" else -1.0
        adverse_momentum_bps = max(0.0, -side_sign * momentum_bps)
        win_probability = _clip(
            0.52
            + abs(direction_score) * 0.28
            + max(0.0, side_sign * flow_change) * 0.06
            - adverse_momentum_bps / max(config.max_abs_momentum_bps, 1e-9) * 0.24,
            0.05,
            0.92,
        )
        if win_probability < config.min_win_probability:
            return None, "win_probability_below_min"

        opposing_quantity = float(fast["sell_quantity"] if side == "long" else fast["buy_quantity"])
        queue_ahead = (bid_quantity if side == "long" else ask_quantity) * max(config.queue_ahead_fraction, 0.01)
        projected_opposing = opposing_quantity * config.quote_ttl_ms / max(config.fast_window_ms, 1)
        fill_probability = _clip(1.0 - math.exp(-projected_opposing / max(queue_ahead, 1e-12)), 0.0, 1.0)
        if fill_probability < config.min_fill_probability:
            return None, "fill_probability_below_min"

        volatility_bps = (float(slow["high_price"]) - float(slow["low_price"])) / mid_price * 10_000.0
        cost_bps = config.expected_round_trip_cost_bps
        target_bps = _clip(
            max(config.min_target_bps, cost_bps * 3.0, spread_bps * 1.5 + volatility_bps * 2.0),
            config.min_target_bps,
            config.max_target_bps,
        )
        stop_bps = max(0.1, target_bps * max(config.stop_to_target_ratio, 0.05))
        conditional_net_ev_bps = (
            win_probability * target_bps
            - (1.0 - win_probability) * stop_bps
            - cost_bps
        )
        if conditional_net_ev_bps < config.min_conditional_net_ev_bps:
            return None, "net_ev_below_min"
        fill_weighted_ev_bps = fill_probability * conditional_net_ev_bps
        entry_price = bid_price if side == "long" else ask_price
        if side == "long":
            target_price = entry_price * (1.0 + target_bps / 10_000.0)
            stop_price = entry_price * (1.0 - stop_bps / 10_000.0)
        else:
            target_price = entry_price * (1.0 - target_bps / 10_000.0)
            stop_price = entry_price * (1.0 + stop_bps / 10_000.0)
        return NearBboProposal(
            symbol=state.symbol,
            side=side,
            generated_at_ms=now_ms,
            expires_at_ms=now_ms + config.quote_ttl_ms,
            entry_price=entry_price,
            target_price=target_price,
            stop_price=stop_price,
            spread_bps=spread_bps,
            fill_probability=fill_probability,
            win_probability=win_probability,
            conditional_net_ev_bps=conditional_net_ev_bps,
            fill_weighted_ev_bps=fill_weighted_ev_bps,
            target_bps=target_bps,
            stop_bps=stop_bps,
            queue_ahead_quantity=queue_ahead,
            reason_codes=(
                "strategy_leg:near_bbo_shadow",
                f"direction_score:{direction_score:.6f}",
                f"fill_probability:{fill_probability:.6f}",
                f"conditional_net_ev_bps:{conditional_net_ev_bps:.6f}",
            ),
            features={
                "direction_score": direction_score,
                "book_imbalance_signed": imbalance_signed,
                "microprice_signed": microprice_signed,
                "slow_taker_flow": slow_flow,
                "fast_taker_flow": fast_flow,
                "taker_flow_change": flow_change,
                "momentum_bps": momentum_bps,
                "volatility_bps": volatility_bps,
                "expected_round_trip_cost_bps": cost_bps,
                "trade_count": int(slow["trade_count"]),
            },
        ), None

    def _bucket_for_second(self, state: _SymbolState, second_ms: int, price: float) -> _TradeBucket:
        if state.trade_buckets and state.trade_buckets[-1].open_time_ms == second_ms:
            return state.trade_buckets[-1]
        if not state.trade_buckets or state.trade_buckets[-1].open_time_ms < second_ms:
            bucket = _TradeBucket(second_ms, price, price, price, price)
            state.trade_buckets.append(bucket)
            return bucket
        for bucket in reversed(state.trade_buckets):
            if bucket.open_time_ms == second_ms:
                return bucket
            if bucket.open_time_ms < second_ms:
                break
        bucket = _TradeBucket(second_ms, price, price, price, price)
        state.trade_buckets.append(bucket)
        state.trade_buckets = deque(sorted(state.trade_buckets, key=lambda item: item.open_time_ms))
        return bucket

    def _prune(self, state: _SymbolState, *, latest_event_ms: int) -> None:
        cutoff = latest_event_ms - self.config.observation_window_ms - 1_000
        while state.trade_buckets and state.trade_buckets[0].open_time_ms < cutoff:
            state.trade_buckets.popleft()


def _window_stats(buckets: deque[_TradeBucket], cutoff_ms: int) -> dict[str, float | int]:
    selected = [bucket for bucket in buckets if bucket.open_time_ms + 999 >= cutoff_ms]
    if not selected:
        return {
            "buy_quantity": 0.0,
            "sell_quantity": 0.0,
            "quantity": 0.0,
            "trade_count": 0,
            "first_price": 0.0,
            "last_price": 0.0,
            "high_price": 0.0,
            "low_price": 0.0,
        }
    buy = sum(bucket.taker_buy_quantity for bucket in selected)
    sell = sum(bucket.taker_sell_quantity for bucket in selected)
    return {
        "buy_quantity": buy,
        "sell_quantity": sell,
        "quantity": buy + sell,
        "trade_count": sum(bucket.trade_count for bucket in selected),
        "first_price": selected[0].first_price,
        "last_price": selected[-1].last_price,
        "high_price": max(bucket.high_price for bucket in selected),
        "low_price": min(bucket.low_price for bucket in selected),
    }


def _signed_flow(values: dict[str, float | int]) -> float:
    quantity = float(values["quantity"])
    if quantity <= 0:
        return 0.0
    return (float(values["buy_quantity"]) - float(values["sell_quantity"])) / quantity


def _price_change_bps(start: float, end: float) -> float:
    return (end - start) / start * 10_000.0 if start > 0 else 0.0


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
