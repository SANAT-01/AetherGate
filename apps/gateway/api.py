import time
import uuid
from decimal import Decimal

import httpx
from django.http import HttpRequest
from ninja import Router

from apps.routing.models import ModelPricing
from apps.routing.providers.base import LLMMessage
from apps.routing.providers.freellmapi import FreeLLMAPIProvider

from .auth import resolve_api_key, resolve_end_customer
from .models import RequestLog
from .schemas import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageSchema,
)

router = Router()


def _openai_error(message: str, err_type: str, code: str) -> dict:
    return {"error": {"message": message, "type": err_type, "code": code}}


@router.post(
    "/chat/completions",
    response={200: ChatCompletionResponse, 400: dict, 401: dict, 403: dict, 502: dict},
)
async def chat_completions(request: HttpRequest, payload: ChatCompletionRequest):
    start = time.monotonic()

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
        await RequestLog.objects.acreate(
            org=org,
            external_tenant_id=external_tenant_id,
            api_key=api_key,
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

    # --- Step 3: Budget / rate-limit enforcement ---
    # Deliberate no-op in M1. M2 inserts here: a Redis Lua atomic budget check
    # keyed on (org, external_tenant_id) against `budget.daily_limit_usd`, plus
    # a per-GatewayAPIKey Redis token-bucket rate limiter keyed on `api_key.id`.

    if payload.stream:
        return 400, _openai_error(
            "Streaming is not supported in this deployment yet",
            "invalid_request_error",
            "streaming_unsupported",
        )

    # --- Step 4: Call provider ---
    provider = FreeLLMAPIProvider()
    messages = [LLMMessage(role=m.role, content=m.content) for m in payload.messages]
    try:
        result = await provider.complete(model=payload.model, messages=messages, timeout=30.0)
    except httpx.HTTPStatusError as exc:
        await RequestLog.objects.acreate(
            org=org,
            external_tenant_id=external_tenant_id,
            api_key=api_key,
            model_requested=payload.model,
            provider_served=provider.provider_name,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 502, _openai_error(
            f"Upstream provider error: {exc.response.status_code}", "api_error", "upstream_error"
        )
    except httpx.TimeoutException:
        await RequestLog.objects.acreate(
            org=org,
            external_tenant_id=external_tenant_id,
            api_key=api_key,
            model_requested=payload.model,
            provider_served=provider.provider_name,
            status=RequestLog.Status.FAILED,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        return 502, _openai_error("Upstream provider timed out", "api_error", "upstream_timeout")

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

    # --- Step 6: Log + respond ---
    await RequestLog.objects.acreate(
        org=org,
        external_tenant_id=external_tenant_id,
        api_key=api_key,
        model_requested=payload.model,
        model_served=result.model_served,
        provider_served=provider.provider_name,
        status=RequestLog.Status.SUCCESS,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=cost_usd,
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
