import json
import unittest

from bfa.ai.client import OpenAIAPIError, OpenAIResponsesClient, extract_response_text
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
        self.assertEqual(call["payload"]["model"], "gpt-5.4")
        self.assertEqual(call["payload"]["text"]["format"]["name"], "bfa_trade_decision")
        self.assertEqual(response.response_id, "resp_1")
        self.assertEqual(json.loads(response.output_text)["decision"], "pass")

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
