import unittest

from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.resume_check import resume_check_from_live_status


def report(*, positions=None, open_orders=None, open_algo_orders=None, protective_complete=False, backoff=False):
    return LiveStatusReport(
        db_path=":memory:",
        runtime_dir="/tmp",
        counts={},
        latest={},
        openai_backoff=OpenAiBackoffStatus(active=backoff),
        protective_evidence=ProtectiveEvidence(
            complete=protective_complete,
            status="entry_with_stop_loss_and_take_profit" if protective_complete else "missing",
        ),
        lva05_complete=protective_complete,
        exchange_evidence={
            "account": {"available_balance": "30"},
            "positions": [] if positions is None else positions,
            "open_orders": [] if open_orders is None else open_orders,
            "open_algo_orders": [] if open_algo_orders is None else open_algo_orders,
        },
    )


class ResumeCheckTests(unittest.TestCase):
    def test_keeps_paused_without_exchange_evidence(self):
        missing_exchange = LiveStatusReport(
            db_path=":memory:",
            runtime_dir="/tmp",
            counts={},
            latest={},
            openai_backoff=OpenAiBackoffStatus(active=False),
            protective_evidence=ProtectiveEvidence(complete=False),
            lva05_complete=False,
            exchange_evidence={},
        )

        result = resume_check_from_live_status(missing_exchange)

        self.assertFalse(result.resume_allowed)
        self.assertEqual(result.status, "keep_paused")
        self.assertIn("exchange_evidence_missing", result.reasons)

    def test_allows_resume_when_exchange_is_clear_and_ai_is_available(self):
        result = resume_check_from_live_status(report())

        self.assertTrue(result.resume_allowed)
        self.assertEqual(result.status, "resume_allowed")
        self.assertEqual(result.reasons, ["no_active_position_or_open_orders"])

    def test_keeps_paused_when_position_has_algo_protection(self):
        result = resume_check_from_live_status(
            report(
                positions=[{"symbol": "ZECUSDT", "positionAmt": "0.032"}],
                open_algo_orders=[{"symbol": "ZECUSDT", "clientAlgoId": "bfa-zecusdt-sl"}],
                protective_complete=True,
            )
        )

        self.assertFalse(result.resume_allowed)
        self.assertEqual(result.status, "keep_paused")
        self.assertIn("position_has_algo_protection", result.reasons)
        self.assertEqual(result.position_count, 1)
        self.assertEqual(result.open_algo_order_count, 1)

    def test_requires_attention_when_position_has_no_confirmed_algo_protection(self):
        result = resume_check_from_live_status(
            report(positions=[{"symbol": "ZECUSDT", "positionAmt": "0.032"}])
        )

        self.assertFalse(result.resume_allowed)
        self.assertEqual(result.status, "urgent_attention")
        self.assertIn("active_position_without_confirmed_algo_protection", result.reasons)

    def test_requires_attention_for_open_orders_without_position(self):
        result = resume_check_from_live_status(report(open_algo_orders=[{"symbol": "ZECUSDT"}]))

        self.assertFalse(result.resume_allowed)
        self.assertEqual(result.status, "urgent_attention")
        self.assertIn("open_orders_without_position", result.reasons)

    def test_keeps_paused_during_ai_backoff_even_when_exchange_is_clear(self):
        result = resume_check_from_live_status(report(backoff=True))

        self.assertFalse(result.resume_allowed)
        self.assertEqual(result.status, "keep_paused")
        self.assertIn("ai_backoff_active", result.reasons)


if __name__ == "__main__":
    unittest.main()
