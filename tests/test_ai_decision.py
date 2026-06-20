import unittest

from bfa.ai.decision import estimate_stop_risk_usdt, parse_decision_json, validate_decision_payload
from bfa.ai.schema import AiTradeDecision, RiskLimits, context_from_candidate


class AiDecisionTests(unittest.TestCase):
    def context(self):
        return context_from_candidate(
            {
                "symbol": "BTCUSDT",
                "score": 50.0,
                "reason_codes": ["narrative_heat", "price_momentum"],
                "features": {"quote_volume": 5_000_000, "reference_price": 100.0},
            },
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

    def valid_trade(self):
        return {
            "decision": "trade",
            "side": "long",
            "confidence": 0.72,
            "entry_price": 100.0,
            "stop_price": 96.0,
            "target_price": 108.0,
            "notional_usdt": 20.0,
            "hold_time_minutes": 45,
            "reasons": ["narrative and market confirmation"],
        }

    def test_valid_long_trade_is_accepted(self):
        result = validate_decision_payload(self.valid_trade(), self.context())

        self.assertTrue(result.accepted)
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.decision.side, "long")

    def test_pass_decision_is_accepted_without_prices(self):
        result = validate_decision_payload(
            {
                "decision": "pass",
                "side": "flat",
                "confidence": 0.4,
                "entry_price": None,
                "stop_price": None,
                "target_price": None,
                "notional_usdt": None,
                "hold_time_minutes": None,
                "reasons": ["risk reward is not clear"],
            },
            self.context(),
        )

        self.assertTrue(result.accepted)

    def test_bad_long_price_geometry_is_rejected(self):
        payload = self.valid_trade()
        payload["stop_price"] = 101.0

        result = validate_decision_payload(payload, self.context())

        self.assertFalse(result.accepted)
        self.assertIn("invalid_long_price_geometry", result.validation_errors)

    def test_risk_cap_is_rejected(self):
        payload = self.valid_trade()
        payload["stop_price"] = 80.0

        result = validate_decision_payload(payload, self.context())

        self.assertFalse(result.accepted)
        self.assertIn("risk_exceeds_cap", result.validation_errors)

    def test_entry_far_from_reference_price_is_rejected(self):
        payload = self.valid_trade()
        payload["entry_price"] = 103.0
        payload["stop_price"] = 102.0
        payload["target_price"] = 106.0

        result = validate_decision_payload(payload, self.context())

        self.assertFalse(result.accepted)
        self.assertIn("entry_too_far_from_reference_price", result.validation_errors)

    def test_compact_context_keeps_reference_price(self):
        context = self.context().to_dict()

        self.assertEqual(context["candidate"]["features"]["reference_price"], 100.0)

    def test_unexpected_fields_are_rejected(self):
        payload = self.valid_trade()
        payload["api_key"] = "synthetic-openai-key-abcdef"

        result = validate_decision_payload(payload, self.context())

        self.assertFalse(result.accepted)
        self.assertIn("unexpected_field:api_key", result.validation_errors)

    def test_parse_decision_requires_json_object(self):
        self.assertEqual(parse_decision_json('{"decision":"pass"}'), {"decision": "pass"})
        with self.assertRaises(ValueError):
            parse_decision_json("[]")

    def test_estimated_stop_risk_uses_notional_and_stop_distance(self):
        risk = estimate_stop_risk_usdt(
            AiTradeDecision(
                decision="trade",
                side="long",
                confidence=0.8,
                entry_price=100.0,
                stop_price=96.0,
                target_price=108.0,
                notional_usdt=20.0,
                hold_time_minutes=30,
                reasons=["ok"],
            )
        )

        self.assertAlmostEqual(risk, 0.8)


if __name__ == "__main__":
    unittest.main()
