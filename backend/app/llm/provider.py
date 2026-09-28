from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class TransientLLMError(RuntimeError):
    pass


class PermanentLLMError(RuntimeError):
    pass


class StructuredResult(BaseModel):
    value: BaseModel
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


class LLMProvider(Protocol):
    async def generate(self, *, model: str, prompt: str) -> str: ...

    def stream(self, *, model: str, prompt: str) -> AsyncIterator[str]: ...

    async def structured_output(
        self,
        *,
        model: str,
        prompt: str,
        schema: type[T],
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> StructuredResult: ...
