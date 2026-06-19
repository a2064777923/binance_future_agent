import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.ai.journal import AiDecisionJournal, build_journal_record, persist_ai_decision
from bfa.ai.schema import AiTradeDecision, DecisionValidationResult, RiskLimits, context_from_candidate
from bfa.event_store.store import EventStore


class AiJournalTests(unittest.TestCase):
    def context(self):
        return context_from_candidate(
            {"symbol": "BTCUSDT", "score": 42, "reason_codes": ["narrative_heat"]},
            risk_limits=RiskLimits(
                account_capital_usdt=100,
                max_leverage=3,
                max_position_notional_usdt=20,
                max_risk_per_trade_usdt=1,
                max_daily_loss_usdt=3,
                max_open_positions=2,
            ),
            decided_at="2026-06-19T10:00:00Z",
        )

    def validation(self):
        return DecisionValidationResult(
            accepted=True,
            decision=AiTradeDecision(
                decision="pass",
                side="flat",
                confidence=0.4,
                entry_price=None,
                stop_price=None,
                target_price=None,
                notional_usdt=None,
                hold_time_minutes=None,
                reasons=["not enough confirmation"],
            ),
            validation_errors=[],
        )

    def test_journal_redacts_sensitive_values(self):
        secret = "synthetic-openai-key-abcdef"
        record = build_journal_record(
            context=self.context(),
            request_payload={"headers": {"Authorization": f"Bearer {secret}"}},
            raw_response={"id": "resp_1"},
            validation=self.validation(),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.jsonl"
            AiDecisionJournal(path).append(record)
            line = path.read_text(encoding="utf-8")

        self.assertNotIn(secret, line)
        self.assertIn("BTCUSDT", line)
        self.assertEqual(json.loads(line)["validation"]["accepted"], True)

    def test_persist_ai_decision_writes_event_store_artifact(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        store = EventStore(connection)

        event_id = persist_ai_decision(
            store,
            context=self.context(),
            validation=self.validation(),
            raw_response={"id": "resp_1"},
        )

        self.assertGreater(event_id, 0)
        row = connection.execute("SELECT payload_json FROM ai_decisions").fetchone()
        payload = json.loads(row["payload_json"])
        self.assertTrue(payload["validation"]["accepted"])
        self.assertEqual(payload["context"]["candidate"]["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
