import unittest

from bfa.ai.schema import RiskLimits, context_from_candidate, decision_json_schema
from bfa.config import load_config
from bfa.execution.sizing import compute_position_sizing, sizing_input_from_config


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
        self.assertAlmostEqual(payload["risk_limits"]["max_position_margin_usdt"], 20 / 3)
        self.assertNotIn("OPENAI_API_KEY", payload["candidate"])
        self.assertNotIn("ignored_extra", payload["candidate"]["features"])

    def test_context_can_include_compact_quant_setup(self):
        context = context_from_candidate(
            {
                "symbol": "BTCUSDT",
                "features": {
                    "reference_price": 100.0,
                    "atr_percent": 1.2,
                    "ema_spread_percent": 0.4,
                    "rsi": 62.0,
                    "ignored_extra": "drop-me",
                },
            },
            risk_limits=self.risk_limits(),
            decided_at="2026-06-19T10:00:00Z",
            quant_setup={
                "symbol": "BTCUSDT",
                "decision": "trade",
                "side": "long",
                "entry_price": 100.0,
                "stop_price": 98.8,
                "target_price": 102.2,
                "notional_usdt": 12.5,
                "hold_time_minutes": 15,
                "price_basis": {"model": "expected_market_entry_structure_stop_target_v1"},
                "ignored_extra": "drop-me",
                "factor_scores": [
                    {
                        "name": "momentum",
                        "score": 22,
                        "weight": 1.5,
                        "weighted_score": 33,
                        "direction": "long",
                        "ignored_extra": "drop-me",
                    }
                ],
            },
        )

        payload = context.to_dict()

        self.assertEqual(payload["prompt_version"], "bfa-ai-decision-v2")
        self.assertEqual(payload["candidate"]["features"]["atr_percent"], 1.2)
        self.assertEqual(payload["candidate"]["features"]["rsi"], 62.0)
        self.assertEqual(payload["quant_setup"]["entry_price"], 100.0)
        self.assertEqual(payload["quant_setup"]["price_basis"]["model"], "expected_market_entry_structure_stop_target_v1")
        self.assertNotIn("ignored_extra", payload["quant_setup"])
        self.assertNotIn("ignored_extra", payload["quant_setup"]["factor_scores"][0])

    def test_context_can_include_dynamic_sizing_limits(self):
        config = load_config(
            {
                "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
                "BFA_ACCOUNT_CAPITAL_USDT": "30",
                "BFA_MAX_LEVERAGE": "8",
                "BFA_MAX_MARGIN_PER_POSITION_USDT": "3",
                "BFA_MAX_MARGIN_FRACTION": "0.08",
                "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "30",
            }
        )
        sizing = compute_position_sizing(
            sizing_input_from_config(config, available_balance_usdt=30),
            enabled=True,
        )

        context = context_from_candidate(
            {"symbol": "HYPEUSDT", "features": {"reference_price": 70.0}},
            risk_limits=RiskLimits.from_config(config, sizing_result=sizing),
            decided_at="2026-06-20T10:00:00Z",
        )

        payload = context.to_dict()
        self.assertAlmostEqual(payload["risk_limits"]["max_position_notional_usdt"], 19.2)
        self.assertTrue(payload["risk_limits"]["sizing"]["enabled"])


if __name__ == "__main__":
    unittest.main()
