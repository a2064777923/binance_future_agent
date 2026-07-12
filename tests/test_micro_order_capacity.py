import unittest

from bfa.backtest.micro_order_capacity import MicroOrderAttempt, admit_micro_order_attempts


def attempt(
    attempt_id: str,
    *,
    symbol: str,
    signal_ms: int,
    score: float,
    fill_ms: int | None = None,
    exit_ms: int | None = None,
    ttl_ms: int = 20_000,
) -> MicroOrderAttempt:
    return MicroOrderAttempt(
        attempt_id=attempt_id,
        symbol=symbol,
        side="long",
        signal_time_ms=signal_ms,
        pending_until_ms=signal_ms + ttl_ms,
        score=score,
        fill_time_ms=fill_ms,
        exit_time_ms=exit_ms,
    )


class MicroOrderCapacityTests(unittest.TestCase):
    def test_watch_universe_is_ranked_before_three_pending_slots_are_applied(self):
        attempts = [
            attempt(f"a{index}", symbol=f"S{index}USDT", signal_ms=1_000, score=float(index))
            for index in range(1, 9)
        ]

        result = admit_micro_order_attempts(
            attempts,
            max_pending_orders=3,
            max_active_intents=3,
        )

        self.assertEqual([item.attempt_id for item in result.admitted], ["a8", "a7", "a6"])
        self.assertEqual(result.diagnostics["watch_attempt_count"], 8)
        self.assertEqual(result.diagnostics["admitted_count"], 3)
        self.assertEqual(result.diagnostics["capacity_rejected_count"], 5)
        self.assertEqual(result.diagnostics["max_pending_observed"], 3)

    def test_expired_pending_slot_is_reused_without_restricting_later_watch_symbols(self):
        attempts = [
            attempt("first", symbol="AUSDT", signal_ms=1_000, score=2.0, ttl_ms=5_000),
            attempt("blocked", symbol="BUSDT", signal_ms=2_000, score=3.0),
            attempt("after_expiry", symbol="CUSDT", signal_ms=6_000, score=1.0),
        ]

        result = admit_micro_order_attempts(
            attempts,
            max_pending_orders=1,
            max_active_intents=1,
        )

        self.assertEqual([item.attempt_id for item in result.admitted], ["first", "after_expiry"])
        self.assertEqual(result.rejected_attempt_ids, ("blocked",))

    def test_filled_intent_occupies_active_capacity_until_position_exit(self):
        attempts = [
            attempt("filled", symbol="AUSDT", signal_ms=1_000, score=5.0, fill_ms=2_000, exit_ms=30_000),
            attempt("while_open", symbol="BUSDT", signal_ms=10_000, score=9.0),
            attempt("after_exit", symbol="CUSDT", signal_ms=30_000, score=1.0),
        ]

        result = admit_micro_order_attempts(
            attempts,
            max_pending_orders=1,
            max_active_intents=1,
        )

        self.assertEqual([item.attempt_id for item in result.admitted], ["filled", "after_exit"])
        self.assertEqual(result.diagnostics["max_open_observed"], 1)

    def test_admission_score_does_not_use_future_fill_outcome(self):
        high_score_expiry = attempt("high", symbol="AUSDT", signal_ms=1_000, score=10.0)
        low_score_fill = attempt(
            "low",
            symbol="BUSDT",
            signal_ms=1_000,
            score=1.0,
            fill_ms=2_000,
            exit_ms=3_000,
        )

        result = admit_micro_order_attempts(
            [low_score_fill, high_score_expiry],
            max_pending_orders=1,
            max_active_intents=1,
        )

        self.assertEqual([item.attempt_id for item in result.admitted], ["high"])

    def test_same_symbol_cannot_hold_overlapping_pending_intents(self):
        attempts = [
            attempt("first", symbol="AUSDT", signal_ms=1_000, score=1.0),
            attempt("duplicate", symbol="AUSDT", signal_ms=2_000, score=9.0),
        ]

        result = admit_micro_order_attempts(
            attempts,
            max_pending_orders=3,
            max_active_intents=3,
        )

        self.assertEqual([item.attempt_id for item in result.admitted], ["first"])
        self.assertEqual(result.diagnostics["symbol_busy_rejected_count"], 1)


if __name__ == "__main__":
    unittest.main()
