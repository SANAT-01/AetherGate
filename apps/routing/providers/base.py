from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMCompletionResult(BaseModel):
    model_served: str
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    raw_response: dict


class BaseLLMProvider(ABC):
    provider_name: str

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 30.0,
    ) -> LLMCompletionResult: ...

    @abstractmethod
    async def stream(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 30.0,
    ) -> AsyncIterator[str]:
        """Streaming is deferred to M4; concrete providers may raise NotImplementedError."""
        ...
