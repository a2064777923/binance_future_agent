"""Queue-proxy forward shadow ledger for near-BBO proposals."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboProposal


@dataclass(frozen=True)
class NearBboShadowConfig:
    account_capital_usdt: float = 400.0
    notional_usdt: float = 120.0
    max_active_intents: int = 3
    max_hold_ms: int = 30_000
    max_recorded_outcomes: int = 5_000
    queue_fill_mode: str = "volume_ahead"
    queue_ahead_fraction: float = 1.0
    evidence_exit_enabled: bool = True
    confirmation_ms: int = 3_000
    confirmation_min_net_progress_bps: float = 0.0
    adverse_selection_exit_bps: float = 6.0
    profit_lock_activate_net_bps: float = 2.0
    profit_lock_min_net_bps: float = 0.5
    profit_lock_giveback_fraction: float = 0.50

    def __post_init__(self) -> None:
        if self.account_capital_usdt <= 0 or self.notional_usdt <= 0:
            raise ValueError("shadow capital and notional must be positive")
        if (
            self.max_active_intents <= 0
            or self.max_hold_ms <= 0
            or self.max_recorded_outcomes <= 0
            or self.confirmation_ms <= 0
        ):
            raise ValueError("shadow capacity, hold time, and retention must be positive")
        if not 0.0 <= self.profit_lock_giveback_fraction <= 1.0:
            raise ValueError("profit_lock_giveback_fraction must be between zero and one")
        if self.queue_fill_mode not in {
            "volume_ahead",
            "price_through_or_volume_ahead",
            "touch",
        }:
            raise ValueError(
                "queue_fill_mode must be volume_ahead, "
                "price_through_or_volume_ahead, or touch"
            )
        if not 0.0 < self.queue_ahead_fraction <= 1.0:
            raise ValueError("queue_ahead_fraction must be in (0, 1]")

    @property
    def calibration_features(self) -> dict[str, float]:
        return {
            "shadow_max_hold_seconds": self.max_hold_ms / 1_000.0,
            "shadow_queue_fill_mode_touch": 1.0 if self.queue_fill_mode == "touch" else 0.0,
            "shadow_queue_fill_mode_trade_through": (
                1.0 if self.queue_fill_mode == "price_through_or_volume_ahead" else 0.0
            ),
            "shadow_queue_ahead_fraction": self.queue_ahead_fraction,
            "shadow_evidence_exit_enabled": 1.0 if self.evidence_exit_enabled else 0.0,
            "shadow_confirmation_seconds": self.confirmation_ms / 1_000.0,
            "shadow_confirmation_min_net_progress_bps": self.confirmation_min_net_progress_bps,
            "shadow_adverse_selection_exit_bps": self.adverse_selection_exit_bps,
            "shadow_profit_lock_activate_net_bps": self.profit_lock_activate_net_bps,
            "shadow_profit_lock_min_net_bps": self.profit_lock_min_net_bps,
            "shadow_profit_lock_giveback_fraction": self.profit_lock_giveback_fraction,
        }


@dataclass(frozen=True)
class NearBboShadowOutcome:
    proposal_id: str
    symbol: str
    side: str
    lane: str
    regime: str
    signal_time_ms: int
    fill_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    target_price: float
    stop_price: float
    notional_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    slippage_usdt: float
    net_pnl_usdt: float
    hold_ms: int
    exit_reason: str
    mfe_bps: float
    mae_bps: float

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class NearBboShadowLabel:
    proposal_id: str
    symbol: str
    side: str
    lane: str
    regime: str
    signal_time_ms: int
    resolved_time_ms: int
    expires_at_ms: int
    notional_usdt: float
    filled: bool
    fill_time_ms: int | None
    exit_time_ms: int | None
    exit_reason: str
    profitable: bool | None
    net_pnl_usdt: float | None
    mfe_bps: float | None
    mae_bps: float | None
    predicted_fill_probability: float
    predicted_win_probability: float
    predicted_conditional_net_ev_bps: float
    features: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass
class _ShadowIntent:
    proposal: NearBboProposal
    applied_queue_ahead_quantity: float
    queue_remaining_quantity: float
    price_touch_count: int = 0
    matching_trade_count: int = 0
    matching_quantity: float = 0.0
    matching_notional_usdt: float = 0.0
    trade_through_count: int = 0
    status: str = "pending"
    fill_time_ms: int | None = None
    best_price: float | None = None
    worst_price: float | None = None


class NearBboShadowLedger:
    """Track at most N pending/open shadow intents without placing orders."""

    def __init__(self, config: NearBboShadowConfig, *, strategy_config: NearBboConfig) -> None:
        self.config = config
        self.strategy_config = strategy_config
        self._intents: dict[str, _ShadowIntent] = {}
        self._latest_trade_price: dict[str, float] = {}
        self._outcomes: deque[NearBboShadowOutcome] = deque(maxlen=config.max_recorded_outcomes)
        self._labels: deque[NearBboShadowLabel] = deque(maxlen=config.max_recorded_outcomes)
        self._new_labels: list[NearBboShadowLabel] = []
        self._first_event_ms: int | None = None
        self._last_event_ms: int | None = None
        self._admitted_count = 0
        self._capacity_rejected_count = 0
        self._expired_count = 0
        self._untouched_expired_count = 0
        self._wrong_aggressor_only_expired_count = 0
        self._queue_blocked_expired_count = 0
        self._trade_through_fill_count = 0
        self._filled_count = 0
        self._closed_count = 0
        self._wins = 0
        self._losses = 0
        self._net_pnl_usdt = 0.0
        self._gross_profit_usdt = 0.0
        self._gross_loss_usdt = 0.0

    @property
    def active_symbols(self) -> set[str]:
        return set(self._intents)

    def has_active_symbol(self, symbol: str) -> bool:
        """Return whether a symbol has a pending or open shadow intent.

        Replay hot paths use this O(1) lookup before forwarding raw trades.  It
        avoids allocating the full active-symbol set for every aggTrade.
        """

        return symbol.upper() in self._intents

    @property
    def available_capacity(self) -> int:
        return max(0, self.config.max_active_intents - len(self._intents))

    @property
    def active_intent_count(self) -> int:
        return len(self._intents)

    @property
    def outcomes(self) -> tuple[NearBboShadowOutcome, ...]:
        return tuple(self._outcomes)

    @property
    def labels(self) -> tuple[NearBboShadowLabel, ...]:
        return tuple(self._labels)

    def drain_new_labels(self) -> tuple[NearBboShadowLabel, ...]:
        labels = tuple(self._new_labels)
        self._new_labels.clear()
        return labels

    def admit(self, proposals: Iterable[NearBboProposal]) -> tuple[NearBboProposal, ...]:
        admitted: list[NearBboProposal] = []
        for proposal in proposals:
            self.advance(proposal.generated_at_ms)
            if proposal.symbol in self._intents:
                continue
            if self.available_capacity <= 0:
                self._capacity_rejected_count += 1
                continue
            self._touch_time(proposal.generated_at_ms)
            applied_queue = (
                0.0
                if self.config.queue_fill_mode == "touch"
                else max(proposal.queue_ahead_quantity, 0.0)
                * self.config.queue_ahead_fraction
            )
            self._intents[proposal.symbol] = _ShadowIntent(
                proposal=proposal,
                applied_queue_ahead_quantity=applied_queue,
                queue_remaining_quantity=applied_queue,
            )
            self._admitted_count += 1
            admitted.append(proposal)
        return tuple(admitted)

    def on_trade(
        self,
        *,
        symbol: str,
        event_time_ms: int,
        price: float,
        quantity: float,
        taker_buy: bool,
    ) -> tuple[NearBboShadowOutcome, ...]:
        normalized = symbol.upper()
        if event_time_ms < 0 or price <= 0 or quantity <= 0:
            return ()
        self._touch_time(event_time_ms)
        self._latest_trade_price[normalized] = float(price)
        prior_intent = self._intents.get(normalized)
        excursion_updated = prior_intent is not None and prior_intent.status == "open"
        if excursion_updated:
            self._update_excursion(prior_intent, price)
        # Let a max-hold exit use the trade that first reaches the deadline.
        # Pending TTL still expires before this event can fill because advance
        # resolves the intent before it is looked up below.
        closed = list(self.advance(event_time_ms))
        intent = self._intents.get(normalized)
        if intent is None:
            return tuple(closed)

        proposal = intent.proposal
        if intent.status == "pending":
            price_touch = (
                price <= proposal.entry_price
                if proposal.side == "long"
                else price >= proposal.entry_price
            )
            if price_touch:
                intent.price_touch_count += 1
            matching_sell = proposal.side == "long" and not taker_buy and price_touch
            matching_buy = proposal.side == "short" and taker_buy and price_touch
            if matching_sell or matching_buy:
                intent.matching_trade_count += 1
                intent.matching_quantity += quantity
                intent.matching_notional_usdt += price * quantity
                trade_through = (
                    price < proposal.entry_price
                    if proposal.side == "long"
                    else price > proposal.entry_price
                )
                if trade_through:
                    intent.trade_through_count += 1
                fill_on_through = (
                    self.config.queue_fill_mode == "price_through_or_volume_ahead"
                    and trade_through
                )
                if not fill_on_through:
                    intent.queue_remaining_quantity -= quantity
                if fill_on_through or intent.queue_remaining_quantity <= 0:
                    intent.status = "open"
                    intent.fill_time_ms = event_time_ms
                    intent.best_price = proposal.entry_price
                    intent.worst_price = proposal.entry_price
                    self._filled_count += 1
                    if fill_on_through:
                        self._trade_through_fill_count += 1
            if intent.status == "pending":
                return tuple(closed)

        if not excursion_updated:
            self._update_excursion(intent, price)
        hit_target = price >= proposal.target_price if proposal.side == "long" else price <= proposal.target_price
        hit_stop = price <= proposal.stop_price if proposal.side == "long" else price >= proposal.stop_price
        if hit_stop:
            # A stop is market-like protection. If the observed trade has
            # already crossed the trigger, using the ideal trigger price would
            # erase the gap that the replay actually observed.
            closed.append(self._close(normalized, event_time_ms, price, "stop_loss"))
        elif hit_target:
            closed.append(self._close(normalized, event_time_ms, proposal.target_price, "take_profit"))
        elif self.config.evidence_exit_enabled and intent.fill_time_ms is not None:
            mfe_bps = max(0.0, _favorable_move_bps(proposal.side, proposal.entry_price, intent.best_price or price))
            current_bps = _favorable_move_bps(proposal.side, proposal.entry_price, price)
            cost_bps = self.strategy_config.expected_round_trip_cost_bps
            profit_lock_activation = cost_bps + max(0.0, self.config.profit_lock_activate_net_bps)
            if mfe_bps >= profit_lock_activation:
                locked_gross_bps = max(
                    cost_bps + max(0.0, self.config.profit_lock_min_net_bps),
                    mfe_bps * (1.0 - self.config.profit_lock_giveback_fraction),
                )
                if current_bps <= locked_gross_bps:
                    closed.append(self._close(normalized, event_time_ms, price, "evidence_profit_lock"))
                    return tuple(closed)
            confirmation_floor = cost_bps + max(0.0, self.config.confirmation_min_net_progress_bps)
            if (
                event_time_ms - intent.fill_time_ms >= self.config.confirmation_ms
                and mfe_bps < confirmation_floor
                and current_bps <= -max(0.0, self.config.adverse_selection_exit_bps)
            ):
                closed.append(self._close(normalized, event_time_ms, price, "evidence_adverse_selection"))
        return tuple(closed)

    def advance(self, now_ms: int) -> tuple[NearBboShadowOutcome, ...]:
        self._touch_time(now_ms)
        closed: list[NearBboShadowOutcome] = []
        for symbol, intent in list(self._intents.items()):
            if intent.status == "pending" and now_ms >= intent.proposal.expires_at_ms:
                if intent.matching_trade_count > 0:
                    self._queue_blocked_expired_count += 1
                elif intent.price_touch_count > 0:
                    self._wrong_aggressor_only_expired_count += 1
                else:
                    self._untouched_expired_count += 1
                self._append_label(
                    NearBboShadowLabel(
                        proposal_id=intent.proposal.proposal_id,
                        symbol=symbol,
                        side=intent.proposal.side,
                        lane=intent.proposal.lane,
                        regime=intent.proposal.regime,
                        signal_time_ms=intent.proposal.generated_at_ms,
                        resolved_time_ms=now_ms,
                        expires_at_ms=intent.proposal.expires_at_ms,
                        notional_usdt=self.config.notional_usdt,
                        filled=False,
                        fill_time_ms=None,
                        exit_time_ms=None,
                        exit_reason="quote_expired",
                        profitable=None,
                        net_pnl_usdt=None,
                        mfe_bps=None,
                        mae_bps=None,
                        predicted_fill_probability=intent.proposal.fill_probability,
                        predicted_win_probability=intent.proposal.win_probability,
                        predicted_conditional_net_ev_bps=intent.proposal.conditional_net_ev_bps,
                        features={
                            **intent.proposal.features,
                            **self.config.calibration_features,
                            **self._intent_fill_features(intent),
                        },
                    )
                )
                del self._intents[symbol]
                self._expired_count += 1
                continue
            if intent.status != "open" or intent.fill_time_ms is None:
                continue
            if now_ms - intent.fill_time_ms < self.config.max_hold_ms:
                continue
            last_price = self._latest_trade_price.get(symbol)
            if last_price is not None:
                closed.append(self._close(symbol, now_ms, last_price, "max_hold_exit"))
        return tuple(closed)

    def summary(self, *, now_ms: int | None = None) -> dict[str, int | float | None]:
        if now_ms is not None:
            self.advance(now_ms)
        pending_count = sum(1 for intent in self._intents.values() if intent.status == "pending")
        open_count = sum(1 for intent in self._intents.values() if intent.status == "open")
        duration_ms = max(0, (self._last_event_ms or 0) - (self._first_event_ms or 0))
        duration_hours = duration_ms / 3_600_000.0
        profit_factor = (
            self._gross_profit_usdt / self._gross_loss_usdt
            if self._gross_loss_usdt > 0
            else None
        )
        return {
            "account_capital_usdt": self.config.account_capital_usdt,
            "notional_usdt": self.config.notional_usdt,
            "max_active_intents": self.config.max_active_intents,
            "admitted_count": self._admitted_count,
            "capacity_rejected_count": self._capacity_rejected_count,
            "expired_count": self._expired_count,
            "untouched_expired_count": self._untouched_expired_count,
            "wrong_aggressor_only_expired_count": self._wrong_aggressor_only_expired_count,
            "queue_blocked_expired_count": self._queue_blocked_expired_count,
            "trade_through_fill_count": self._trade_through_fill_count,
            "filled_count": self._filled_count,
            "closed_count": self._closed_count,
            "label_count": len(self._labels),
            "wins": self._wins,
            "losses": self._losses,
            "fill_rate": self._filled_count / self._admitted_count if self._admitted_count else 0.0,
            "win_rate": self._wins / self._closed_count if self._closed_count else 0.0,
            "profit_factor": profit_factor,
            "net_pnl_usdt": round(self._net_pnl_usdt, 8),
            "pending_count": pending_count,
            "open_position_count": open_count,
            "active_intent_count": len(self._intents),
            "duration_ms": duration_ms,
            "fills_per_hour": self._filled_count / duration_hours if duration_hours > 0 else 0.0,
            "profitable_fills_per_hour": self._wins / duration_hours if duration_hours > 0 else 0.0,
        }

    def _close(self, symbol: str, exit_time_ms: int, raw_exit_price: float, reason: str) -> NearBboShadowOutcome:
        intent = self._intents.pop(symbol)
        proposal = intent.proposal
        fill_time_ms = intent.fill_time_ms or proposal.generated_at_ms
        quantity = self.config.notional_usdt / proposal.entry_price
        slip_rate = max(0.0, self.strategy_config.exit_slippage_bps) / 10_000.0
        if proposal.side == "long":
            exit_price = raw_exit_price * (1.0 - slip_rate)
            gross = quantity * (exit_price - proposal.entry_price)
            slippage = quantity * max(raw_exit_price - exit_price, 0.0)
            mfe_bps = _move_bps(proposal.entry_price, intent.best_price or proposal.entry_price)
            mae_bps = _move_bps(proposal.entry_price, intent.worst_price or proposal.entry_price)
        else:
            exit_price = raw_exit_price * (1.0 + slip_rate)
            gross = quantity * (proposal.entry_price - exit_price)
            slippage = quantity * max(exit_price - raw_exit_price, 0.0)
            mfe_bps = _move_bps(intent.best_price or proposal.entry_price, proposal.entry_price)
            mae_bps = _move_bps(intent.worst_price or proposal.entry_price, proposal.entry_price)
        taker_weight = max(0.0, min(1.0, self.strategy_config.taker_exit_probability))
        exit_fee_bps = (
            self.strategy_config.maker_exit_fee_bps * (1.0 - taker_weight)
            + self.strategy_config.taker_exit_fee_bps * taker_weight
        )
        entry_fee = self.config.notional_usdt * max(0.0, self.strategy_config.maker_entry_fee_bps) / 10_000.0
        exit_fee = quantity * exit_price * max(0.0, exit_fee_bps) / 10_000.0
        fees = entry_fee + exit_fee
        net = gross - fees
        outcome = NearBboShadowOutcome(
            proposal_id=proposal.proposal_id,
            symbol=symbol,
            side=proposal.side,
            lane=proposal.lane,
            regime=proposal.regime,
            signal_time_ms=proposal.generated_at_ms,
            fill_time_ms=fill_time_ms,
            exit_time_ms=exit_time_ms,
            entry_price=proposal.entry_price,
            exit_price=exit_price,
            target_price=proposal.target_price,
            stop_price=proposal.stop_price,
            notional_usdt=self.config.notional_usdt,
            gross_pnl_usdt=round(gross, 8),
            fees_usdt=round(fees, 8),
            slippage_usdt=round(slippage, 8),
            net_pnl_usdt=round(net, 8),
            hold_ms=max(0, exit_time_ms - fill_time_ms),
            exit_reason=reason,
            mfe_bps=round(mfe_bps, 8),
            mae_bps=round(mae_bps, 8),
        )
        self._outcomes.append(outcome)
        self._append_label(
            NearBboShadowLabel(
                proposal_id=proposal.proposal_id,
                symbol=symbol,
                side=proposal.side,
                lane=proposal.lane,
                regime=proposal.regime,
                signal_time_ms=proposal.generated_at_ms,
                resolved_time_ms=exit_time_ms,
                expires_at_ms=proposal.expires_at_ms,
                notional_usdt=self.config.notional_usdt,
                filled=True,
                fill_time_ms=fill_time_ms,
                exit_time_ms=exit_time_ms,
                exit_reason=reason,
                profitable=net > 0,
                net_pnl_usdt=round(net, 8),
                mfe_bps=round(mfe_bps, 8),
                mae_bps=round(mae_bps, 8),
                predicted_fill_probability=proposal.fill_probability,
                predicted_win_probability=proposal.win_probability,
                predicted_conditional_net_ev_bps=proposal.conditional_net_ev_bps,
                features={
                    **proposal.features,
                    **self.config.calibration_features,
                    **self._intent_fill_features(intent),
                },
            )
        )
        self._closed_count += 1
        self._net_pnl_usdt += net
        if net > 0:
            self._wins += 1
            self._gross_profit_usdt += net
        elif net < 0:
            self._losses += 1
            self._gross_loss_usdt += -net
        return outcome

    def _intent_fill_features(self, intent: _ShadowIntent) -> dict[str, float | int | str]:
        applied_queue = intent.applied_queue_ahead_quantity
        if applied_queue > 0:
            consumed_fraction = min(1.0, intent.matching_quantity / applied_queue)
        else:
            consumed_fraction = 1.0 if intent.matching_trade_count > 0 else 0.0
        return {
            "shadow_queue_fill_mode": self.config.queue_fill_mode,
            "shadow_displayed_queue_ahead_quantity": max(
                intent.proposal.queue_ahead_quantity,
                0.0,
            ),
            "shadow_applied_queue_ahead_quantity": applied_queue,
            "shadow_queue_remaining_quantity": max(intent.queue_remaining_quantity, 0.0),
            "shadow_queue_consumed_fraction": consumed_fraction,
            "shadow_price_touch_count": intent.price_touch_count,
            "shadow_matching_trade_count": intent.matching_trade_count,
            "shadow_matching_quantity": intent.matching_quantity,
            "shadow_matching_notional_usdt": intent.matching_notional_usdt,
            "shadow_trade_through_count": intent.trade_through_count,
        }

    @staticmethod
    def _update_excursion(intent: _ShadowIntent, price: float) -> None:
        proposal = intent.proposal
        intent.best_price = (
            max(intent.best_price or price, price)
            if proposal.side == "long"
            else min(intent.best_price or price, price)
        )
        intent.worst_price = (
            min(intent.worst_price or price, price)
            if proposal.side == "long"
            else max(intent.worst_price or price, price)
        )

    def _append_label(self, label: NearBboShadowLabel) -> None:
        self._labels.append(label)
        self._new_labels.append(label)

    def _touch_time(self, value: int) -> None:
        if self._first_event_ms is None:
            self._first_event_ms = value
        self._last_event_ms = max(self._last_event_ms or value, value)


def _move_bps(start: float, end: float) -> float:
    return (end - start) / start * 10_000.0 if start > 0 else 0.0


def _favorable_move_bps(side: str, entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    return ((price - entry) if side == "long" else (entry - price)) / entry * 10_000.0


__all__ = [
    "NearBboShadowConfig",
    "NearBboShadowLabel",
    "NearBboShadowLedger",
    "NearBboShadowOutcome",
]
