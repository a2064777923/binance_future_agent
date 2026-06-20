import unittest

from bfa.ai.client import OpenAIChatCompletionsClient, OpenAIResponsesClient
from bfa.ai.providers import ai_source, build_ai_client
from bfa.config import load_config


class AiProviderTests(unittest.TestCase):
    def test_default_provider_builds_openai_responses_client(self):
        client = build_ai_client(
            load_config(
                {
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "OPENAI_MODEL": "gpt-5.4",
                    "OPENAI_BASE_URL": "https://api.openai.com/v1",
                }
            )
        )

        self.assertIsInstance(client, OpenAIResponsesClient)

    def test_deepseek_provider_builds_chat_completions_client(self):
        client = build_ai_client(
            load_config(
                {
                    "BFA_AI_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "synthetic-deepseek-key-abcdef",
                    "DEEPSEEK_MODEL": "deepseek-v4-flash",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                }
            )
        )

        self.assertIsInstance(client, OpenAIChatCompletionsClient)
        self.assertEqual(client.base_url, "https://api.deepseek.com")
        self.assertEqual(client.model, "deepseek-v4-flash")

    def test_ai_source_names_selected_provider(self):
        self.assertEqual(ai_source(load_config({})), "openai.responses")
        self.assertEqual(
            ai_source(load_config({"BFA_AI_PROVIDER": "deepseek"})),
            "deepseek.chat_completions",
        )


if __name__ == "__main__":
    unittest.main()
