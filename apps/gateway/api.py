import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
from asgiref.sync import sync_to_async
from django.http import HttpRequest, StreamingHttpResponse
from ninja import Router

from apps.routing.engine import execute_stream_with_fallback, execute_with_fallback
from apps.routing.models import ModelPricing
from apps.routing.providers.base import LLMMessage, LLMStreamChunk

from .auth import resolve_api_key, resolve_end_customer
from .budget import check_budget, record_spend
from .models import RequestLog
from .rate_limit import check_ip_rate_limit, check_rate_limit
from .schemas import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageSchema,
)
from .tasks import record_request_telemetry

router = Router()


def _openai_error(message: str, err_type: str, code: str) -> dict:
    return {"error": {"message": message, "type": err_type, "code": code}}


# .delay() normally just does a fast, synchronous Redis enqueue — but under
# CELERY_TASK_ALWAYS_EAGER (tests) it runs the task body (a synchronous ORM
# write) inline. Either way, that's synchronous work that must not run
# directly on the event loop thread inside this async view.
_enqueue_telemetry = sync_to_async(record_request_telemetry.delay)


@router.post(
    "/chat/completions",
    response={
        200: ChatCompletionResponse,
        400: dict,
        401: dict,
        403: dict,
        429: dict,
        502: dict,
    },
)
async def chat_completions(request: HttpRequest, payload: ChatCompletionRequest):
    start = time.monotonic()

    # --- Step 0: Pre-auth IP rate limit ---
    # Protects the server itself from unauthenticated/invalid-key request
    # floods, independent of the per-key limiter in Step 3 (which only
    # applies once a valid key is known). No RequestLog row is written here
    # since no org is known yet at this point.
    client_ip = request.META.get("REMOTE_ADDR", "unknown")
    if not await check_ip_rate_limit(client_ip):
        return 429, _openai_error(
            "Too many requests from this client", "rate_limit_error", "rate_limit_exceeded"
        )

    # --- Step 1: Auth & org resolution ---
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return 401, _openai_error(
            "Missing or malformed Authorization header", "invalid_request_error", "missing_api_key"
        )
    raw_key = auth_header.removeprefix("Bearer ").strip()

    api_key = await resolve_api_key(raw_key)
    if api_key is None:
        return 401, _openai_error("Invalid API key", "invalid_request_error", "invalid_api_key")
    org = api_key.org

    # --- Step 2: Tenant resolution (manual-only; reject unknown tenants) ---
    external_tenant_id = request.headers.get("X-Tenant-ID", "")
    if not external_tenant_id:
        return 400, _openai_error(
            "X-Tenant-ID header is required", "invalid_request_error", "missing_tenant_id"
        )

    budget = await resolve_end_customer(org, external_tenant_id)
    if budget is None:
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=payload.model,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 403, _openai_error(
            f"Unknown tenant '{external_tenant_id}' for this organization. "
            "Tenant must be provisioned by an operator before use.",
            "invalid_request_error",
            "unknown_tenant",
        )

    # --- Step 3: Rate limit + budget enforcement ---
    if not await check_rate_limit(api_key):
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=payload.model,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 429, _openai_error(
            "Rate limit exceeded for this API key", "rate_limit_error", "rate_limit_exceeded"
        )

    if not await check_budget(budget):
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=payload.model,
            status=RequestLog.Status.BUDGET_EXCEEDED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 429, _openai_error(
            "Daily budget exceeded for this tenant", "insufficient_quota", "budget_exceeded"
        )

    # --- Step 4: Call provider (with fallback chain per the org's RoutingPolicy) ---
    messages = [LLMMessage(role=m.role, content=m.content) for m in payload.messages]

    if payload.stream:
        try:
            stream_iter, provider_served, fallback_triggered = await execute_stream_with_fallback(
                org=org,
                routing_policy=api_key.routing_policy,
                messages=messages,
                requested_model=payload.model,
            )
        except httpx.HTTPStatusError as exc:
            await _enqueue_telemetry(
                org_id=org.id,
                external_tenant_id=external_tenant_id,
                api_key_id=api_key.id,
                model_requested=payload.model,
                status=RequestLog.Status.FAILED,
                latency_ms=int((time.monotonic() - start) * 1000),
            )
            return 502, _openai_error(
                f"Upstream provider error: {exc.response.status_code}",
                "api_error",
                "upstream_error",
            )
        except httpx.TransportError:
            await _enqueue_telemetry(
                org_id=org.id,
                external_tenant_id=external_tenant_id,
                api_key_id=api_key.id,
                model_requested=payload.model,
                status=RequestLog.Status.FAILED,
                latency_ms=int((time.monotonic() - start) * 1000),
            )
            return 502, _openai_error(
                "Upstream provider unreachable or timed out", "api_error", "upstream_timeout"
            )

        return StreamingHttpResponse(
            _sse_response_generator(
                stream_iter,
                org=org,
                external_tenant_id=external_tenant_id,
                api_key=api_key,
                model_requested=payload.model,
                provider_served=provider_served,
                fallback_triggered=fallback_triggered,
                start=start,
            ),
            content_type="text/event-stream",
        )

    try:
        result, provider_served, fallback_triggered = await execute_with_fallback(
            org=org,
            routing_policy=api_key.routing_policy,
            messages=messages,
            requested_model=payload.model,
        )
    except httpx.HTTPStatusError as exc:
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=payload.model,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 502, _openai_error(
            f"Upstream provider error: {exc.response.status_code}", "api_error", "upstream_error"
        )
    except httpx.TransportError:
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=payload.model,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 502, _openai_error(
            "Upstream provider unreachable or timed out", "api_error", "upstream_timeout"
        )

    latency_ms = int((time.monotonic() - start) * 1000)

    # --- Step 5: Cost lookup ---
    pricing = await ModelPricing.objects.filter(model_name=result.model_served).afirst()
    cost_usd = None
    if pricing and result.prompt_tokens is not None and result.completion_tokens is not None:
        cost_usd = (
            Decimal(result.prompt_tokens) / 1_000_000
        ) * pricing.input_cost_per_1m_tokens + (
            Decimal(result.completion_tokens) / 1_000_000
        ) * pricing.output_cost_per_1m_tokens

    # --- Step 6: Record spend, log + respond ---
    if cost_usd is not None:
        await record_spend(org.id, external_tenant_id, cost_usd)

    await _enqueue_telemetry(
        org_id=org.id,
        external_tenant_id=external_tenant_id,
        api_key_id=api_key.id,
        model_requested=payload.model,
        model_served=result.model_served,
        provider_served=provider_served,
        status=RequestLog.Status.FALLBACK_SUCCESS
        if fallback_triggered
        else RequestLog.Status.SUCCESS,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=str(cost_usd) if cost_usd is not None else None,
        latency_ms=latency_ms,
    )

    return 200, ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        model=result.model_served,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessageSchema(role="assistant", content=result.content),
            )
        ],
        usage={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
    )


async def _sse_response_generator(
    stream_iter: AsyncIterator[LLMStreamChunk],
    *,
    org,
    external_tenant_id: str,
    api_key,
    model_requested: str,
    provider_served: str,
    fallback_triggered: bool,
    start: float,
) -> AsyncIterator[bytes]:
    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    model_served = model_requested
    first = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    try:
        async for chunk in stream_iter:
            if chunk.model_served:
                model_served = chunk.model_served
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
            if not chunk.content:
                continue
            delta = (
                ChatCompletionChunkDelta(role="assistant", content=chunk.content)
                if first
                else ChatCompletionChunkDelta(content=chunk.content)
            )
            first = False
            event = ChatCompletionChunk(
                id=response_id,
                model=model_served,
                choices=[ChatCompletionChunkChoice(delta=delta)],
            )
            yield f"data: {event.model_dump_json()}\n\n".encode()
    except (httpx.HTTPStatusError, httpx.TransportError, ValueError, KeyError, IndexError):
        await _enqueue_telemetry(
            org_id=org.id,
            external_tenant_id=external_tenant_id,
            api_key_id=api_key.id,
            model_requested=model_requested,
            model_served=model_served,
            provider_served=provider_served,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return

    pricing = await ModelPricing.objects.filter(model_name=model_served).afirst()
    cost_usd = None
    if pricing and prompt_tokens is not None and completion_tokens is not None:
        cost_usd = (Decimal(prompt_tokens) / 1_000_000) * pricing.input_cost_per_1m_tokens + (
            Decimal(completion_tokens) / 1_000_000
        ) * pricing.output_cost_per_1m_tokens

    if cost_usd is not None:
        await record_spend(org.id, external_tenant_id, cost_usd)

    await _enqueue_telemetry(
        org_id=org.id,
        external_tenant_id=external_tenant_id,
        api_key_id=api_key.id,
        model_requested=model_requested,
        model_served=model_served,
        provider_served=provider_served,
        status=RequestLog.Status.FALLBACK_SUCCESS
        if fallback_triggered
        else RequestLog.Status.SUCCESS,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=str(cost_usd) if cost_usd is not None else None,
        latency_ms=int((time.monotonic() - start) * 1000),
    )

    closing_event = ChatCompletionChunk(
        id=response_id,
        model=model_served,
        choices=[ChatCompletionChunkChoice(delta=ChatCompletionChunkDelta(), finish_reason="stop")],
    )
    yield f"data: {closing_event.model_dump_json()}\n\n".encode()
    yield b"data: [DONE]\n\n"
