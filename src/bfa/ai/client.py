"""Dependency-free AI decision API clients."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAITransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> tuple[int, Any, dict[str, str]]:
        """Return status code, parsed JSON payload, and response headers."""


class UrllibOpenAITransport:
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> tuple[int, Any, dict[str, str]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is caller configured.
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw), dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"error": {"message": raw}}
            return exc.code, parsed, dict(exc.headers.items())
        except URLError as exc:
            raise OpenAIAPIError(
                status_code=None,
                message=str(exc.reason),
                payload={},
                headers={},
            ) from exc


@dataclass(frozen=True)
class OpenAIAPIError(Exception):
    status_code: int | None
    message: str
    payload: Mapping[str, Any]
    headers: Mapping[str, str]

    def __str__(self) -> str:
        return f"AI API request failed: {self.message}"


@dataclass(frozen=True)
class OpenAIResponse:
    response_id: str | None
    request_payload: dict[str, Any]
    raw_response: dict[str, Any]
    output_text: str
    response_headers: dict[str, str]


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        transport: OpenAITransport | None = None,
        timeout: float = 30.0,
        max_output_tokens: int = 800,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrllibOpenAITransport()
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    def create_decision(
        self,
        context: Mapping[str, Any],
        *,
        instructions: str,
        schema: Mapping[str, Any],
    ) -> OpenAIResponse:
        request_payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(dict(context), ensure_ascii=False, sort_keys=True),
                        }
                    ],
                },
            ],
            "text": {"format": dict(schema)},
            "max_output_tokens": self.max_output_tokens,
        }
        status_code, payload, headers = self.transport.post_json(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=request_payload,
            timeout=self.timeout,
        )
        if status_code < 200 or status_code >= 300:
            raise _error_from_payload(status_code, payload, headers)
        if not isinstance(payload, dict):
            raise OpenAIAPIError(
                status_code=status_code,
                message="response payload must be an object",
                payload={},
                headers=headers,
            )
        return OpenAIResponse(
            response_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
            request_payload=request_payload,
            raw_response=dict(payload),
            output_text=extract_response_text(payload),
            response_headers=headers,
        )


class OpenAIChatCompletionsClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        transport: OpenAITransport | None = None,
        timeout: float = 30.0,
        max_output_tokens: int = 800,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrllibOpenAITransport()
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    def create_decision(
        self,
        context: Mapping[str, Any],
        *,
        instructions: str,
        schema: Mapping[str, Any],
    ) -> OpenAIResponse:
        schema_value = schema.get("schema")
        schema_payload = dict(schema_value) if isinstance(schema_value, Mapping) else dict(schema)
        request_payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        instructions
                        + "\nReturn exactly one valid json object and no markdown."
                        + "\nExample JSON: "
                        + json.dumps(_example_from_schema(schema_payload), ensure_ascii=False, sort_keys=True)
                        + "\nRequired JSON schema: "
                        + json.dumps(schema_payload, ensure_ascii=False, sort_keys=True)
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(dict(context), ensure_ascii=False, sort_keys=True),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        status_code, payload, headers = self.transport.post_json(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=request_payload,
            timeout=self.timeout,
        )
        if status_code < 200 or status_code >= 300:
            raise _error_from_payload(status_code, payload, headers)
        if not isinstance(payload, dict):
            raise OpenAIAPIError(
                status_code=status_code,
                message="response payload must be an object",
                payload={},
                headers=headers,
            )
        return OpenAIResponse(
            response_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
            request_payload=request_payload,
            raw_response=dict(payload),
            output_text=extract_chat_completion_text(payload),
            response_headers=headers,
        )


def extract_response_text(payload: Mapping[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    for output in payload.get("output") or []:
        if not isinstance(output, Mapping):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, Mapping):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
            elif "json" in content:
                chunks.append(json.dumps(content["json"], ensure_ascii=False, sort_keys=True))
    if chunks:
        return "".join(chunks)
    raise OpenAIAPIError(
        status_code=None,
        message="response did not contain output text",
        payload=dict(payload),
        headers={},
    )


def extract_chat_completion_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenAIAPIError(
            status_code=None,
            message="chat completion response did not contain choices",
            payload=dict(payload),
            headers={},
        )
    first = choices[0]
    if not isinstance(first, Mapping):
        raise OpenAIAPIError(
            status_code=None,
            message="chat completion choice must be an object",
            payload=dict(payload),
            headers={},
        )
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise OpenAIAPIError(
            status_code=None,
            message="chat completion choice did not contain a message",
            payload=dict(payload),
            headers={},
        )
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        if chunks:
            return "".join(chunks)
    raise OpenAIAPIError(
        status_code=None,
        message="chat completion message did not contain text",
        payload=dict(payload),
        headers={},
    )


def _error_from_payload(
    status_code: int,
    payload: Any,
    headers: dict[str, str],
) -> OpenAIAPIError:
    message = "AI request failed"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping) and error.get("message"):
            message = str(error["message"])
    return OpenAIAPIError(
        status_code=status_code,
        message=message,
        payload=payload if isinstance(payload, Mapping) else {"payload": payload},
        headers=headers,
    )


def _pass_example() -> dict[str, Any]:
    return {
        "decision": "pass",
        "side": "flat",
        "confidence": 0.0,
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "notional_usdt": None,
        "hold_time_minutes": None,
        "reasons": ["insufficient evidence"],
    }


def _example_from_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping):
        return {"ok": True}
    if isinstance(required, list) and {"decision", "side", "confidence"}.issubset(set(required)):
        return _pass_example()
    keys = required if isinstance(required, list) and required else list(properties)
    return {
        str(key): _example_value(properties.get(str(key)))
        for key in keys
        if isinstance(key, str) and key in properties
    }


def _example_value(schema: Any) -> Any:
    if not isinstance(schema, Mapping):
        return None
    raw_type = schema.get("type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    types = [item for item in types if item != "null"]
    if not types:
        return None
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    preferred = types[0]
    if preferred == "boolean":
        return True
    if preferred == "integer":
        return 1
    if preferred == "number":
        return 0.0
    if preferred == "array":
        return []
    if preferred == "object":
        return {}
    if preferred == "string":
        return "value"
    return None
