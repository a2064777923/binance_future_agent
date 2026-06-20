"""AI provider selection."""

from __future__ import annotations

from bfa.ai.client import OpenAIChatCompletionsClient, OpenAIResponsesClient
from bfa.config import AppConfig


def ai_provider(config: AppConfig) -> str:
    return config.get("BFA_AI_PROVIDER", "openai").strip().lower()


def ai_source(config: AppConfig) -> str:
    provider = ai_provider(config)
    if provider == "deepseek":
        return "deepseek.chat_completions"
    return "openai.responses"


def build_ai_client(config: AppConfig, ai_client_factory=None, *, max_output_tokens: int | None = None):
    if ai_client_factory is not None:
        return ai_client_factory(config)
    provider = ai_provider(config)
    token_cap = max_output_tokens if max_output_tokens is not None else int(config.get("OPENAI_MAX_OUTPUT_TOKENS"))
    if provider == "deepseek":
        return OpenAIChatCompletionsClient(
            api_key=config.get("DEEPSEEK_API_KEY"),
            model=config.get("DEEPSEEK_MODEL"),
            base_url=config.get("DEEPSEEK_BASE_URL"),
            timeout=float(config.get("OPENAI_TIMEOUT_SECONDS")),
            max_output_tokens=token_cap,
        )
    return OpenAIResponsesClient(
        api_key=config.get("OPENAI_API_KEY"),
        model=config.get("OPENAI_MODEL"),
        base_url=config.get("OPENAI_BASE_URL"),
        timeout=float(config.get("OPENAI_TIMEOUT_SECONDS")),
        max_output_tokens=token_cap,
    )
