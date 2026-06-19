import unittest

from bfa.ai.schema import RiskLimits, context_from_candidate, decision_json_schema


class AiSchemaTests(unittest.TestCase):
    def risk_limits(self):
        return RiskLimits(
            account_capital_usdt=100,
            max_leverage=3,
            max_position_notional_usdt=20,
            max_risk_per_trade_usdt=1,
            max_daily_loss_usdt=3,
            max_open_positions=2,
        )

    def test_decision_schema_is_strict_and_complete(self):
        schema = decision_json_schema()
        body = schema["schema"]

        self.assertEqual(schema["type"], "json_schema")
        self.assertTrue(schema["strict"])
        self.assertFalse(body["additionalProperties"])
        self.assertEqual(
            set(body["required"]),
            {
                "decision",
                "side",
                "confidence",
                "entry_price",
                "stop_price",
                "target_price",
                "notional_usdt",
                "hold_time_minutes",
                "reasons",
            },
        )

    def test_context_packet_is_compact_and_omits_unknown_sensitive_keys(self):
        context = context_from_candidate(
            {
                "symbol": "BTCUSDT",
                "score": 42.0,
                "reason_codes": ["narrative_heat"],
                "source_event_ids": [1],
                "market_event_ids": [2],
                "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                "features": {
                    "mention_count": 2,
                    "quote_volume": 5_000_000,
                    "ignored_extra": "drop-me",
                },
            },
            risk_limits=self.risk_limits(),
            decided_at="2026-06-19T10:00:00Z",
        )

        payload = context.to_dict()

        self.assertEqual(payload["candidate"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["risk_limits"]["max_position_notional_usdt"], 20)
        self.assertNotIn("OPENAI_API_KEY", payload["candidate"])
        self.assertNotIn("ignored_extra", payload["candidate"]["features"])


if __name__ == "__main__":
    unittest.main()
