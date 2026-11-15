from collections.abc import AsyncIterator

import httpx
from django.conf import settings

from .base import BaseLLMProvider, LLMCompletionResult, LLMMessage


class FreeLLMAPIProvider(BaseLLMProvider):
    provider_name = "freellmapi"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or settings.FREELLMAPI_BASE_URL).rstrip("/")
        self.token = token or settings.FREELLMAPI_TOKEN

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 30.0,
    ) -> LLMCompletionResult:
        payload = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions", json=payload, headers=headers
            )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMCompletionResult(
            model_served=data.get("model", model),
            content=content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=data,
        )

    async def stream(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        timeout: float = 30.0,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("Streaming is deferred to M4")
