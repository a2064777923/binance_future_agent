"""Incremental, shadow-safe near-BBO scalping opportunity model.

This module only scores public market data.  It has no exchange client and no
order side effects.  The interface separates a broad watch universe from the
small pending-order capacity returned by :meth:`rank_opportunities`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import heapq
import math
from typing import Any, Mapping, Protocol

from bfa.strategy.near_bbo_regime import (
    BREAKOUT,
    CHOP,
    RANGE,
    TREND,
    WARMUP,
    NearBboRegimeConfig,
    NearBboRegimeTracker,
)


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
    setup_mode: str = "legacy"
    regime_config: NearBboRegimeConfig = field(default_factory=NearBboRegimeConfig)
    scout_confirmation_ms: int = 2_000
    scout_ttl_ms: int = 8_000
    range_edge_fraction: float = 0.25
    trend_pullback_min_bps: float = -2.0
    trend_pullback_max_bps: float = 20.0
    trend_slow_ema_break_bps: float = 8.0
    min_aligned_microprice: float = 0.05
    min_aligned_flow_change: float = 0.10
    min_aligned_fast_flow: float = -0.10
    min_reversal_bps: float = 0.50
    max_signal_volatility_bps: float = 6.0
    max_scout_adverse_bps: float = 6.0
    min_signal_persistence_ratio: float = 0.70

    def __post_init__(self) -> None:
        positive_ints = (
            self.observation_window_ms,
            self.fast_window_ms,
            self.quote_ttl_ms,
            self.max_book_age_ms,
            self.max_trade_age_ms,
            self.max_pending_orders,
            self.min_trade_events,
            self.scout_confirmation_ms,
            self.scout_ttl_ms,
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
        if self.setup_mode not in {"legacy", "article_v2"}:
            raise ValueError("setup_mode must be legacy or article_v2")
        if self.scout_ttl_ms < self.scout_confirmation_ms:
            raise ValueError("scout_ttl_ms cannot be below scout_confirmation_ms")
        if not 0.0 < self.range_edge_fraction < 0.5:
            raise ValueError("range_edge_fraction must be between zero and one half")
        if self.trend_pullback_max_bps < self.trend_pullback_min_bps:
            raise ValueError("trend pullback bounds are invalid")
        if self.max_signal_volatility_bps <= 0 or self.max_scout_adverse_bps <= 0:
            raise ValueError("article-v2 volatility and adverse controls must be positive")
        if not 0.0 <= self.min_signal_persistence_ratio <= 1.0:
            raise ValueError("min_signal_persistence_ratio must be between zero and one")

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
    proposal_id: str
    symbol: str
    side: str
    lane: str
    regime: str
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

    def update_summary(
        self,
        *,
        last_price: float,
        high_price: float,
        low_price: float,
        taker_buy_quantity: float,
        taker_sell_quantity: float,
        trade_count: int,
    ) -> None:
        if trade_count <= 0:
            return
        # The summary is ordered.  ``first_price`` is only used when this is a
        # newly-created bucket; an existing bucket already has the earlier open.
        self.last_price = last_price
        self.high_price = max(self.high_price, high_price)
        self.low_price = min(self.low_price, low_price)
        self.taker_buy_quantity += max(0.0, taker_buy_quantity)
        self.taker_sell_quantity += max(0.0, taker_sell_quantity)
        self.trade_count += int(trade_count)


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
    regime_tracker: NearBboRegimeTracker | None = None
    scout: _NearBboScout | None = None


@dataclass
class _NearBboScout:
    side: str
    lane: str
    regime: str
    started_at_ms: int
    expires_at_ms: int
    reference_price: float
    initial_direction_score: float


class _CalibrationPrediction(Protocol):
    fill_probability: float
    win_probability: float
    expected_net_bps: float


class NearBboCalibrationPredictor(Protocol):
    def predict(
        self,
        features: Mapping[str, Any],
        *,
        side: str,
        lane: str,
        regime: str,
    ) -> _CalibrationPrediction: ...


class NearBboUniverse:
    """Maintain bounded per-second flow state and rank a broad symbol watchlist."""

    def __init__(
        self,
        config: NearBboConfig,
        *,
        calibrator: NearBboCalibrationPredictor | None = None,
        context_features: Mapping[str, float | int] | None = None,
    ) -> None:
        self.config = config
        self.calibrator = calibrator
        self.context_features: dict[str, float] = {}
        for name, value in (context_features or {}).items():
            normalized = float(value)
            if not math.isfinite(normalized):
                raise ValueError("near-BBO context features must be finite")
            self.context_features[str(name)] = normalized
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
        state = self._state_for(normalized)
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
        state = self._state_for(normalized)
        second_ms = event_time_ms // 1_000 * 1_000
        bucket = self._bucket_for_second(state, second_ms, price)
        bucket.update(price=float(price), quantity=float(quantity), taker_buy=bool(taker_buy))
        state.latest_trade_time_ms = max(state.latest_trade_time_ms or event_time_ms, int(event_time_ms))
        assert state.regime_tracker is not None
        state.regime_tracker.ingest_trade(
            event_time_ms=int(event_time_ms),
            price=float(price),
            quantity=float(quantity),
            taker_buy=bool(taker_buy),
        )
        self._prune(state, latest_event_ms=state.latest_trade_time_ms)
        return True

    def ingest_trade_summary(
        self,
        *,
        symbol: str,
        event_time_ms: int,
        first_price: float,
        last_price: float,
        high_price: float,
        low_price: float,
        taker_buy_quantity: float,
        taker_sell_quantity: float,
        quote_volume: float,
        taker_buy_quote: float,
        trade_count: int,
    ) -> bool:
        """Ingest an ordered aggregate for fast historical replay.

        Replay only needs one-second OHLC/flow/count updates for the strategy;
        raw aggTrades remain available to the shadow ledger for queue-proxy
        fills.  Keeping this path separate preserves the live tick API while
        removing redundant Python work from multi-variant backtests.
        """

        normalized = symbol.upper()
        if (
            not normalized
            or event_time_ms < 0
            or min(first_price, last_price, high_price, low_price) <= 0
            or high_price < max(first_price, last_price)
            or low_price > min(first_price, last_price)
            or taker_buy_quantity < 0
            or taker_sell_quantity < 0
            or taker_buy_quantity + taker_sell_quantity <= 0
            or quote_volume <= 0
            or taker_buy_quote < 0
            or trade_count <= 0
        ):
            return False
        state = self._state_for(normalized)
        second_ms = event_time_ms // 1_000 * 1_000
        bucket = self._bucket_for_second(state, second_ms, float(first_price))
        if bucket.open_time_ms == second_ms and bucket.trade_count == 0:
            bucket.first_price = float(first_price)
            bucket.last_price = float(first_price)
            bucket.high_price = float(first_price)
            bucket.low_price = float(first_price)
        bucket.update_summary(
            last_price=float(last_price),
            high_price=float(high_price),
            low_price=float(low_price),
            taker_buy_quantity=float(taker_buy_quantity),
            taker_sell_quantity=float(taker_sell_quantity),
            trade_count=int(trade_count),
        )
        state.latest_trade_time_ms = max(state.latest_trade_time_ms or event_time_ms, int(event_time_ms))
        assert state.regime_tracker is not None
        state.regime_tracker.ingest_trade_summary(
            event_time_ms=int(event_time_ms),
            first_price=float(first_price),
            last_price=float(last_price),
            high_price=float(high_price),
            low_price=float(low_price),
            quote_volume=float(quote_volume),
            taker_buy_quote=float(taker_buy_quote),
            trade_count=int(trade_count),
        )
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
            "regime_bar_count": state.regime_tracker.bar_count if state.regime_tracker is not None else 0,
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

        slow, fast = _window_stats_pair(
            state.trade_buckets,
            slow_cutoff_ms=now_ms - config.observation_window_ms,
            fast_cutoff_ms=now_ms - config.fast_window_ms,
        )
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
        manual_probability_gate = self.calibrator is None and config.setup_mode == "legacy"
        adverse_momentum_bps = max(0.0, -side_sign * momentum_bps)
        win_probability = _clip(
            0.52
            + abs(direction_score) * 0.28
            + max(0.0, side_sign * flow_change) * 0.06
            - adverse_momentum_bps / max(config.max_abs_momentum_bps, 1e-9) * 0.24,
            0.05,
            0.92,
        )
        if manual_probability_gate and win_probability < config.min_win_probability:
            return None, "win_probability_below_min"

        opposing_quantity = float(fast["sell_quantity"] if side == "long" else fast["buy_quantity"])
        queue_ahead = (bid_quantity if side == "long" else ask_quantity) * max(config.queue_ahead_fraction, 0.01)
        projected_opposing = opposing_quantity * config.quote_ttl_ms / max(config.fast_window_ms, 1)
        queue_pressure_ratio = projected_opposing / max(queue_ahead, 1e-12)
        fill_probability = _clip(1.0 - math.exp(-queue_pressure_ratio), 0.0, 1.0)
        if manual_probability_gate and fill_probability < config.min_fill_probability:
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
        if manual_probability_gate and conditional_net_ev_bps < config.min_conditional_net_ev_bps:
            return None, "net_ev_below_min"
        fill_weighted_ev_bps = fill_probability * conditional_net_ev_bps
        entry_price = bid_price if side == "long" else ask_price
        if side == "long":
            target_price = entry_price * (1.0 + target_bps / 10_000.0)
            stop_price = entry_price * (1.0 - stop_bps / 10_000.0)
        else:
            target_price = entry_price * (1.0 - target_bps / 10_000.0)
            stop_price = entry_price * (1.0 + stop_bps / 10_000.0)
        last_price = float(slow["last_price"])
        favorable_reversal_bps = (
            (last_price - float(slow["low_price"])) / mid_price * 10_000.0
            if side == "long"
            else (float(slow["high_price"]) - last_price) / mid_price * 10_000.0
        )
        aligned_microprice = side_sign * microprice_signed
        aligned_flow_change = side_sign * flow_change
        aligned_fast_flow = side_sign * fast_flow
        proposal = NearBboProposal(
            proposal_id=f"{state.symbol}:{now_ms}:{side}:legacy_direction",
            symbol=state.symbol,
            side=side,
            lane="legacy_direction",
            regime="UNCLASSIFIED",
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
                **self.context_features,
                "score_source": "legacy_uncalibrated",
                "direction_score": direction_score,
                "book_imbalance_signed": imbalance_signed,
                "microprice_signed": microprice_signed,
                "slow_taker_flow": slow_flow,
                "fast_taker_flow": fast_flow,
                "taker_flow_change": flow_change,
                "momentum_bps": momentum_bps,
                "volatility_bps": volatility_bps,
                "favorable_reversal_bps": favorable_reversal_bps,
                "aligned_microprice": aligned_microprice,
                "aligned_flow_change": aligned_flow_change,
                "aligned_fast_flow": aligned_fast_flow,
                "quote_ttl_seconds": config.quote_ttl_ms / 1_000.0,
                "queue_pressure_ratio": min(queue_pressure_ratio, 20.0),
                "queue_ahead_notional_usdt": queue_ahead * entry_price,
                "log_queue_ahead_notional_usdt": math.log1p(queue_ahead * entry_price),
                "projected_opposing_quantity": projected_opposing,
                "spread_bps": spread_bps,
                "target_bps": target_bps,
                "stop_bps": stop_bps,
                "expected_round_trip_cost_bps": cost_bps,
                "trade_count": int(slow["trade_count"]),
                "log_trade_count": math.log1p(int(slow["trade_count"])),
            },
        )
        if config.setup_mode == "article_v2":
            gated, rejection = self._article_v2_gate(
                state,
                proposal,
                now_ms=now_ms,
                mid_price=mid_price,
            )
            if gated is None:
                return None, rejection
            proposal = gated
        return self._apply_calibration(proposal)

    def _apply_calibration(
        self,
        proposal: NearBboProposal,
    ) -> tuple[NearBboProposal | None, str | None]:
        calibrator = self.calibrator
        if calibrator is None:
            return proposal, None
        try:
            prediction = calibrator.predict(
                proposal.features,
                side=proposal.side,
                lane=proposal.lane,
                regime=proposal.regime,
            )
            fill_probability = float(prediction.fill_probability)
            win_probability = float(prediction.win_probability)
            conditional_net_ev_bps = float(prediction.expected_net_bps)
        except ValueError:
            return None, "calibration_input_out_of_domain"
        except Exception:  # noqa: BLE001 - model failures must reject, never admit.
            return None, "calibration_prediction_error"
        if (
            not math.isfinite(fill_probability)
            or not math.isfinite(win_probability)
            or not math.isfinite(conditional_net_ev_bps)
            or not 0.0 <= fill_probability <= 1.0
            or not 0.0 <= win_probability <= 1.0
            or conditional_net_ev_bps > proposal.target_bps
        ):
            return None, "calibration_prediction_invalid"
        if fill_probability < self.config.min_fill_probability:
            return None, "calibrated_fill_probability_below_min"
        if win_probability < self.config.min_win_probability:
            return None, "calibrated_win_probability_below_min"
        if conditional_net_ev_bps < self.config.min_conditional_net_ev_bps:
            return None, "calibrated_net_ev_below_min"
        features = {
            **proposal.features,
            "heuristic_fill_probability": proposal.fill_probability,
            "heuristic_win_probability": proposal.win_probability,
            "heuristic_conditional_net_ev_bps": proposal.conditional_net_ev_bps,
            "score_source": "walk_forward_calibrated",
        }
        return replace(
            proposal,
            fill_probability=fill_probability,
            win_probability=win_probability,
            conditional_net_ev_bps=conditional_net_ev_bps,
            fill_weighted_ev_bps=fill_probability * conditional_net_ev_bps,
            reason_codes=(
                *proposal.reason_codes,
                "score_source:walk_forward_calibrated",
                f"calibrated_fill_probability:{fill_probability:.6f}",
                f"calibrated_win_probability:{win_probability:.6f}",
                f"calibrated_conditional_net_ev_bps:{conditional_net_ev_bps:.6f}",
            ),
            features=features,
        ), None

    def _article_v2_gate(
        self,
        state: _SymbolState,
        proposal: NearBboProposal,
        *,
        now_ms: int,
        mid_price: float,
    ) -> tuple[NearBboProposal | None, str | None]:
        tracker = state.regime_tracker
        if tracker is None:
            return None, "regime_warmup"
        snapshot = tracker.snapshot(now_ms=now_ms)
        if snapshot.label == WARMUP:
            return None, "regime_warmup"
        if snapshot.label == BREAKOUT:
            state.scout = None
            return None, "regime_breakout"
        if snapshot.label == CHOP:
            state.scout = None
            return None, "regime_chop"

        if snapshot.label == RANGE:
            if snapshot.range_position <= self.config.range_edge_fraction:
                expected_side = "long"
            elif snapshot.range_position >= 1.0 - self.config.range_edge_fraction:
                expected_side = "short"
            else:
                state.scout = None
                return None, "range_not_at_edge"
            lane = "range_reversion"
        elif snapshot.label == TREND and snapshot.direction in {"long", "short"}:
            expected_side = str(snapshot.direction)
            lane = "trend_pullback"
            side_sign = 1.0 if expected_side == "long" else -1.0
            pullback_bps = (snapshot.fast_ema - mid_price) * side_sign / mid_price * 10_000.0
            if not self.config.trend_pullback_min_bps <= pullback_bps <= self.config.trend_pullback_max_bps:
                state.scout = None
                return None, "trend_pullback_depth_invalid"
            slow_break_bps = (snapshot.slow_ema - mid_price) * side_sign / mid_price * 10_000.0
            if slow_break_bps > self.config.trend_slow_ema_break_bps:
                state.scout = None
                return None, "trend_slow_ema_broken"
        else:
            state.scout = None
            return None, "regime_not_tradeable"

        if proposal.side != expected_side:
            state.scout = None
            return None, f"{lane}_direction_mismatch"
        volatility_bps = float(proposal.features["volatility_bps"])
        if volatility_bps > self.config.max_signal_volatility_bps:
            state.scout = None
            return None, "signal_volatility_toxic"

        direction_score = abs(float(proposal.features["direction_score"]))
        scout = state.scout
        if (
            scout is None
            or now_ms > scout.expires_at_ms
            or scout.side != proposal.side
            or scout.lane != lane
        ):
            state.scout = _NearBboScout(
                side=proposal.side,
                lane=lane,
                regime=snapshot.label,
                started_at_ms=now_ms,
                expires_at_ms=now_ms + self.config.scout_ttl_ms,
                reference_price=mid_price,
                initial_direction_score=direction_score,
            )
            return None, "scout_started"

        side_sign = 1.0 if proposal.side == "long" else -1.0
        adverse_bps = max(
            0.0,
            (scout.reference_price - mid_price) * side_sign / scout.reference_price * 10_000.0,
        )
        if adverse_bps > self.config.max_scout_adverse_bps:
            state.scout = None
            return None, "scout_adverse_continuation"
        scout_age_ms = now_ms - scout.started_at_ms
        if scout_age_ms < self.config.scout_confirmation_ms:
            return None, "scout_waiting_min_age"

        aligned_microprice = float(proposal.features["aligned_microprice"])
        aligned_flow_change = float(proposal.features["aligned_flow_change"])
        aligned_fast_flow = float(proposal.features["aligned_fast_flow"])
        reversal_bps = float(proposal.features["favorable_reversal_bps"])
        persistence_ratio = direction_score / max(scout.initial_direction_score, 1e-9)
        if (
            aligned_microprice < self.config.min_aligned_microprice
            or aligned_flow_change < self.config.min_aligned_flow_change
            or aligned_fast_flow < self.config.min_aligned_fast_flow
            or reversal_bps < self.config.min_reversal_bps
            or persistence_ratio < self.config.min_signal_persistence_ratio
        ):
            return None, "scout_waiting_confirmation"

        state.scout = None
        features = {
            **proposal.features,
            **snapshot.feature_payload,
            "score_source": "article_v2_exploration_uncalibrated",
            "scalp_lane": lane,
            "scalp_regime": snapshot.label,
            "scout_age_ms": scout_age_ms,
            "scout_adverse_bps": adverse_bps,
            "signal_persistence_ratio": persistence_ratio,
        }
        return replace(
            proposal,
            proposal_id=f"{proposal.symbol}:{now_ms}:{proposal.side}:{lane}",
            lane=lane,
            regime=snapshot.label,
            features=features,
            reason_codes=(
                *proposal.reason_codes,
                "setup_mode:article_v2",
                "selection_mode:shadow_exploration",
                f"scalp_lane:{lane}",
                f"scalp_regime:{snapshot.label}",
                f"scout_age_ms:{scout_age_ms}",
            ),
        ), None

    def _state_for(self, symbol: str) -> _SymbolState:
        state = self._states.get(symbol)
        if state is None:
            state = _SymbolState(
                symbol=symbol,
                regime_tracker=NearBboRegimeTracker(self.config.regime_config),
            )
            self._states[symbol] = state
        elif state.regime_tracker is None:
            state.regime_tracker = NearBboRegimeTracker(self.config.regime_config)
        return state

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


def _window_stats_pair(
    buckets: deque[_TradeBucket],
    *,
    slow_cutoff_ms: int,
    fast_cutoff_ms: int,
) -> tuple[dict[str, float | int], dict[str, float | int]]:
    """Aggregate overlapping fast/slow windows in one bounded pass."""

    slow = _empty_window_stats()
    fast = _empty_window_stats()
    for bucket in buckets:
        bucket_end_ms = bucket.open_time_ms + 999
        if bucket_end_ms >= slow_cutoff_ms:
            _add_bucket(slow, bucket)
        if bucket_end_ms >= fast_cutoff_ms:
            _add_bucket(fast, bucket)
    return slow, fast


def _empty_window_stats() -> dict[str, float | int]:
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


def _add_bucket(values: dict[str, float | int], bucket: _TradeBucket) -> None:
    if int(values["trade_count"]) == 0:
        values["first_price"] = bucket.first_price
        values["high_price"] = bucket.high_price
        values["low_price"] = bucket.low_price
    else:
        values["high_price"] = max(float(values["high_price"]), bucket.high_price)
        values["low_price"] = min(float(values["low_price"]), bucket.low_price)
    values["last_price"] = bucket.last_price
    values["buy_quantity"] = float(values["buy_quantity"]) + bucket.taker_buy_quantity
    values["sell_quantity"] = float(values["sell_quantity"]) + bucket.taker_sell_quantity
    values["quantity"] = float(values["quantity"]) + bucket.taker_buy_quantity + bucket.taker_sell_quantity
    values["trade_count"] = int(values["trade_count"]) + bucket.trade_count


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
