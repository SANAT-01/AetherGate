import json
from collections.abc import AsyncIterator

import httpx

from .base import BaseLLMProvider, LLMCompletionResult, LLMMessage, LLMStreamChunk, LLMStreamUsage

OPENAI_BASE_URL = "https://api.openai.com"


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(self, token: str, base_url: str = OPENAI_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

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
    ) -> AsyncIterator[LLMStreamChunk]:
        payload = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions", json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        usage = chunk.get("usage")
                        if usage:
                            yield LLMStreamChunk(
                                content="",
                                model_served=chunk.get("model", model),
                                usage=LLMStreamUsage(**usage),
                            )
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield LLMStreamChunk(
                            content=content, model_served=chunk.get("model", model)
                        )
