import json
import unittest

from bfa.ai.client import (
    OpenAIAPIError,
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
    extract_chat_completion_text,
    extract_response_text,
)
from bfa.ai.decision import DECISION_INSTRUCTIONS
from bfa.ai.schema import decision_json_schema


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post_json(self, url, *, headers, payload, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout": timeout,
            }
        )
        return self.response


class AiClientTests(unittest.TestCase):
    def test_create_decision_posts_responses_payload(self):
        decision = {
            "decision": "pass",
            "side": "flat",
            "confidence": 0.3,
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
            "notional_usdt": None,
            "hold_time_minutes": None,
            "reasons": ["not enough confirmation"],
        }
        transport = FakeTransport(
            (
                200,
                {"id": "resp_1", "output_text": json.dumps(decision)},
                {"x-request-id": "req_1"},
            )
        )
        client = OpenAIResponsesClient(
            api_key="synthetic-openai-key-abcdef",
            model="gpt-5.4",
            transport=transport,
        )

        response = client.create_decision(
            {"candidate": {"symbol": "BTCUSDT"}},
            instructions=DECISION_INSTRUCTIONS,
            schema=decision_json_schema(),
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(call["headers"]["Authorization"], "Bearer synthetic-openai-key-abcdef")
        self.assertEqual(call["timeout"], 30.0)
        self.assertEqual(call["payload"]["model"], "gpt-5.4")
        self.assertEqual(call["payload"]["text"]["format"]["name"], "bfa_trade_decision")
        self.assertEqual(response.response_id, "resp_1")
        self.assertEqual(json.loads(response.output_text)["decision"], "pass")

    def test_decision_instructions_require_adversarial_entry_and_stop_audit(self):
        self.assertIn("adversarial overlay", DECISION_INSTRUCTIONS)
        self.assertIn("entry/stop-quality risk", DECISION_INSTRUCTIONS)
        self.assertIn("price below VWAP with EMA trend down", DECISION_INSTRUCTIONS)

    def test_create_decision_honors_short_timeout_and_token_cap(self):
        transport = FakeTransport((200, {"id": "resp_1", "output_text": '{"decision":"pass"}'}, {}))
        client = OpenAIResponsesClient(
            api_key="synthetic-openai-key-abcdef",
            model="gpt-5.4",
            base_url="https://proxy.example.test/v1",
            transport=transport,
            timeout=5.0,
            max_output_tokens=400,
        )

        client.create_decision(
            {"candidate": {"symbol": "BTCUSDT"}},
            instructions=DECISION_INSTRUCTIONS,
            schema=decision_json_schema(),
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], "https://proxy.example.test/v1/responses")
        self.assertEqual(call["timeout"], 5.0)
        self.assertEqual(call["payload"]["max_output_tokens"], 400)

    def test_extract_response_text_supports_nested_output_content(self):
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"decision":"pass"}',
                        }
                    ]
                }
            ]
        }

        self.assertEqual(extract_response_text(payload), '{"decision":"pass"}')

    def test_chat_completions_client_posts_json_mode_payload(self):
        decision = {
            "decision": "pass",
            "side": "flat",
            "confidence": 0.3,
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
            "notional_usdt": None,
            "hold_time_minutes": None,
            "reasons": ["not enough confirmation"],
        }
        transport = FakeTransport(
            (
                200,
                {
                    "id": "chatcmpl_1",
                    "choices": [{"message": {"role": "assistant", "content": json.dumps(decision)}}],
                },
                {"x-request-id": "req_1"},
            )
        )
        client = OpenAIChatCompletionsClient(
            api_key="synthetic-deepseek-key-abcdef",
            model="deepseek-v4-flash",
            transport=transport,
            timeout=5.0,
            max_output_tokens=400,
        )

        response = client.create_decision(
            {"candidate": {"symbol": "BTCUSDT"}},
            instructions=DECISION_INSTRUCTIONS,
            schema=decision_json_schema(),
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer synthetic-deepseek-key-abcdef")
        self.assertEqual(call["payload"]["model"], "deepseek-v4-flash")
        self.assertEqual(call["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(call["payload"]["thinking"], {"type": "disabled"})
        self.assertEqual(call["payload"]["max_tokens"], 400)
        self.assertIn("valid json object", call["payload"]["messages"][0]["content"])
        self.assertIn("Example JSON", call["payload"]["messages"][0]["content"])
        self.assertEqual(response.response_id, "chatcmpl_1")
        self.assertEqual(json.loads(response.output_text)["decision"], "pass")

    def test_chat_completions_client_uses_schema_matching_health_example(self):
        transport = FakeTransport(
            (
                200,
                {
                    "id": "chatcmpl_health",
                    "choices": [{"message": {"role": "assistant", "content": '{"ok":true}'}}],
                },
                {},
            )
        )
        client = OpenAIChatCompletionsClient(
            api_key="synthetic-deepseek-key-abcdef",
            model="deepseek-v4-flash",
            transport=transport,
        )

        response = client.create_decision(
            {"health_check": True},
            instructions="Return a JSON object with ok=true.",
            schema={
                "type": "json_schema",
                "name": "bfa_health_check",
                "schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            },
        )

        system_prompt = transport.calls[0]["payload"]["messages"][0]["content"]
        self.assertIn('"ok": true', system_prompt)
        self.assertNotIn('"decision": "pass"', system_prompt)
        self.assertEqual(response.output_text, '{"ok":true}')

    def test_extract_chat_completion_text(self):
        payload = {"choices": [{"message": {"content": '{"decision":"pass"}'}}]}

        self.assertEqual(extract_chat_completion_text(payload), '{"decision":"pass"}')

    def test_error_payload_raises_api_error(self):
        transport = FakeTransport((429, {"error": {"message": "rate limited"}}, {}))
        client = OpenAIResponsesClient(
            api_key="synthetic-openai-key-abcdef",
            model="gpt-5.4",
            transport=transport,
        )

        with self.assertRaises(OpenAIAPIError):
            client.create_decision(
                {"candidate": {"symbol": "BTCUSDT"}},
                instructions=DECISION_INSTRUCTIONS,
                schema=decision_json_schema(),
            )


if __name__ == "__main__":
    unittest.main()
