from collections.abc import AsyncIterator

import httpx

from apps.tenants.models import Organization

from .crypto import decrypt_api_key
from .models import ProviderCredential, RoutingPolicy
from .providers.base import BaseLLMProvider, LLMCompletionResult, LLMMessage, LLMStreamChunk
from .providers.freellmapi import FreeLLMAPIProvider
from .providers.openai import OpenAIProvider
from .schemas import RoutingChainAttempt, RoutingRules

PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "freellmapi": FreeLLMAPIProvider,
    "openai": OpenAIProvider,
}

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class FallbackChainExhausted(Exception):
    """Re-raised with the last upstream exception once every attempt in the chain fails."""


async def _build_provider(org: Organization, provider_name: str) -> BaseLLMProvider:
    if provider_name == "freellmapi":
        return FreeLLMAPIProvider()

    credential = await ProviderCredential.objects.filter(
        org=org, provider=provider_name, is_active=True
    ).afirst()
    if credential is None or not credential.encrypted_api_key:
        raise RuntimeError(f"No active credential configured for provider '{provider_name}'")

    token = decrypt_api_key(credential.encrypted_api_key)
    provider_cls = PROVIDER_REGISTRY[provider_name]
    if credential.base_url:
        return provider_cls(token=token, base_url=credential.base_url)  # type: ignore[call-arg]
    return provider_cls(token=token)  # type: ignore[call-arg]


def _build_chain(
    routing_policy: RoutingPolicy | None, requested_model: str
) -> list[RoutingChainAttempt]:
    if routing_policy is None or not routing_policy.rules_json:
        return [RoutingChainAttempt(provider="freellmapi", model=requested_model)]

    rules = RoutingRules.model_validate(routing_policy.rules_json)
    return rules.chain


async def execute_with_fallback(
    *,
    org: Organization,
    routing_policy: RoutingPolicy | None,
    messages: list[LLMMessage],
    requested_model: str,
) -> tuple[LLMCompletionResult, str, bool]:
    """Walk the org's fallback chain, returning (result, provider_served, fallback_triggered).

    Only a transient upstream failure advances to the next chain entry:
    429/5xx responses, or a transport-level failure (timeout, connection
    refused/DNS failure, etc. — httpx.TransportError, which TimeoutException
    is a subclass of). Anything else propagates immediately. When the chain
    has no routing_policy configured, it collapses to a single freellmapi
    attempt — identical to the pre-M3 behavior.
    """
    chain = _build_chain(routing_policy, requested_model)

    last_exc: Exception | None = None
    for index, attempt in enumerate(chain):
        provider = await _build_provider(org, attempt.provider)
        try:
            result = await provider.complete(
                model=attempt.model or requested_model, messages=messages, timeout=attempt.timeout
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _TRANSIENT_STATUS_CODES:
                raise
            last_exc = exc
            continue
        except httpx.TransportError as exc:
            last_exc = exc
            continue
        else:
            return result, provider.provider_name, index > 0

    assert last_exc is not None
    raise last_exc


async def _empty_stream() -> AsyncIterator[LLMStreamChunk]:
    return
    yield  # pragma: no cover - makes this an async generator


async def _prepend(
    first: LLMStreamChunk, rest: AsyncIterator[LLMStreamChunk]
) -> AsyncIterator[LLMStreamChunk]:
    yield first
    async for chunk in rest:
        yield chunk


async def execute_stream_with_fallback(
    *,
    org: Organization,
    routing_policy: RoutingPolicy | None,
    messages: list[LLMMessage],
    requested_model: str,
) -> tuple[AsyncIterator[LLMStreamChunk], str, bool]:
    """Streaming counterpart to execute_with_fallback.

    Fallback only happens before the first chunk is yielded by a given
    provider's stream() — once content has started flowing to the client
    the HTTP status is already committed, so a mid-stream failure just ends
    the response early instead of retrying the next chain entry.
    """
    chain = _build_chain(routing_policy, requested_model)

    last_exc: Exception | None = None
    for index, attempt in enumerate(chain):
        provider = await _build_provider(org, attempt.provider)
        gen = provider.stream(
            model=attempt.model or requested_model, messages=messages, timeout=attempt.timeout
        )
        try:
            first_chunk = await gen.__anext__()
        except StopAsyncIteration:
            return _empty_stream(), provider.provider_name, index > 0
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _TRANSIENT_STATUS_CODES:
                raise
            last_exc = exc
            continue
        except httpx.TransportError as exc:
            last_exc = exc
            continue
        else:
            return _prepend(first_chunk, gen), provider.provider_name, index > 0

    assert last_exc is not None
    raise last_exc
