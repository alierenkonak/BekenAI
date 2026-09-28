from __future__ import annotations

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from functools import lru_cache
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.llm.provider import PermanentLLMError, StructuredResult, TransientLLMError

T = TypeVar("T", bound=BaseModel)


_GEMINI_SCHEMA_KEYS = {
    "additionalProperties",
    "anyOf",
    "description",
    "enum",
    "format",
    "items",
    "prefixItems",
    "properties",
    "required",
    "type",
}


def _gemini_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the supported, compact JSON Schema subset accepted by Gemini.

    Runtime Pydantic validation remains authoritative. This representation is
    only an output-shaping hint for the provider, so unsupported constraints
    such as regex patterns and string lengths are intentionally omitted.
    """

    raw = model.model_json_schema()
    definitions = raw.get("$defs", {})

    def convert(node: Any) -> Any:
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        reference = node.get("$ref")
        if reference:
            prefix = "#/$defs/"
            if not reference.startswith(prefix):
                raise ValueError("unsupported_schema_reference")
            name = reference.removeprefix(prefix)
            target = definitions.get(name)
            if not isinstance(target, dict):
                raise ValueError("missing_schema_reference")
            return convert(deepcopy(target))
        converted: dict[str, Any] = {}
        for key, value in node.items():
            if key not in _GEMINI_SCHEMA_KEYS:
                continue
            if key == "properties":
                converted[key] = {name: convert(child) for name, child in value.items()}
            else:
                converted[key] = convert(value)
        alternatives = converted.get("anyOf")
        if isinstance(alternatives, list) and len(alternatives) == 2:
            nulls = [item for item in alternatives if item == {"type": "null"}]
            values = [item for item in alternatives if item != {"type": "null"}]
            if len(nulls) == 1 and len(values) == 1 and isinstance(values[0], dict):
                nullable = values[0]
                value_type = nullable.get("type")
                if isinstance(value_type, str):
                    nullable["type"] = [value_type, "null"]
                    return nullable
        return converted

    schema = convert(raw)
    if not isinstance(schema, dict):
        raise ValueError("invalid_response_schema")
    return schema


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.gemini_secret
        self.maximum_output_tokens = settings.gemini_max_output_tokens
        self.timeout_ms = int(settings.gemini_timeout_seconds * 1000)

    def _config(
        self,
        schema: type[BaseModel] | None = None,
        *,
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            max_output_tokens=self.maximum_output_tokens,
            response_mime_type="application/json" if schema else None,
            response_json_schema=_gemini_json_schema(schema) if schema else None,
            temperature=temperature,
            thinking_config=(
                types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking_level.upper()))
                if thinking_level
                else None
            ),
        )

    def _client(self) -> genai.Client:
        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=self.timeout_ms),
        )

    async def generate(self, *, model: str, prompt: str) -> str:
        try:
            async with self._client().aio as client:
                response = await client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=self._config(),
                )
            return response.text or ""
        except Exception as exc:
            self._raise_safe(exc)

    async def stream(self, *, model: str, prompt: str) -> AsyncIterator[str]:
        try:
            async with self._client().aio as client:
                stream = await client.models.generate_content_stream(
                    model=model,
                    contents=prompt,
                    config=self._config(),
                )
                async for chunk in stream:
                    if chunk.text:
                        yield chunk.text
        except Exception as exc:
            self._raise_safe(exc)

    async def structured_output(
        self,
        *,
        model: str,
        prompt: str,
        schema: type[T],
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> StructuredResult:
        try:
            async with self._client().aio as client:
                response = await client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=self._config(
                        schema, temperature=temperature, thinking_level=thinking_level
                    ),
                )
            candidate = response.candidates[0] if response.candidates else None
            if getattr(candidate, "finish_reason", None) == types.FinishReason.MAX_TOKENS:
                # Usually thinking used up the output budget before the JSON finished.
                raise PermanentLLMError("output_truncated")
            parsed = response.parsed
            if isinstance(parsed, schema):
                value = parsed
            elif isinstance(parsed, dict):
                value = schema.model_validate(parsed)
            else:
                value = schema.model_validate(json.loads(response.text or ""))
            usage = response.usage_metadata
            return StructuredResult(
                value=value,
                model=model,
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                thinking_tokens=getattr(usage, "thoughts_token_count", None),
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            raise PermanentLLMError("invalid_structured_output") from exc
        except PermanentLLMError:
            raise
        except Exception as exc:
            self._raise_safe(exc)

    @staticmethod
    def _raise_safe(exc: Exception) -> None:
        if isinstance(exc, errors.APIError):
            code = getattr(exc, "code", None)
            error: Exception
            if code == 429 or isinstance(code, int) and code >= 500:
                error = TransientLLMError("provider_temporarily_unavailable")
            else:
                error = PermanentLLMError("provider_request_failed")
            # The status alone (429 quota, 503 overload…) is safe to log; bodies are not.
            error.status_code = code  # type: ignore[attr-defined]
            raise error from None
        if isinstance(
            exc,
            (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError),
        ):
            raise TransientLLMError("provider_temporarily_unavailable") from None
        raise PermanentLLMError("provider_request_failed") from None


@lru_cache
def get_llm_provider() -> GeminiProvider:
    settings = get_settings()
    if settings.llm_provider != "gemini":
        raise ValueError("LLM_PROVIDER must be gemini")
    return GeminiProvider(settings)
