from datetime import timedelta

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.gateway.auth import resolve_api_key
from apps.tenants.models import Organization

from .queries import get_cache_savings_summary, get_latency_percentiles, get_spend_summary
from .schemas import (
    CacheSavingsSummaryResponse,
    LatencyPercentilesResponse,
    SpendSummaryResponse,
)

router = Router()


def _openai_error(message: str, err_type: str, code: str) -> dict:
    return {"error": {"message": message, "type": err_type, "code": code}}


async def _resolve_org(request: HttpRequest) -> Organization | tuple[int, dict]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return 401, _openai_error(
            "Missing or malformed Authorization header", "invalid_request_error", "missing_api_key"
        )
    raw_key = auth_header.removeprefix("Bearer ").strip()

    api_key = await resolve_api_key(raw_key)
    if api_key is None:
        return 401, _openai_error("Invalid API key", "invalid_request_error", "invalid_api_key")
    return api_key.org


@router.get("/spend", response={200: SpendSummaryResponse, 401: dict})
async def spend_summary(request: HttpRequest, days: int = 7):
    org = await _resolve_org(request)
    if isinstance(org, tuple):
        return org
    since = timezone.now() - timedelta(days=days)
    return 200, await sync_to_async(get_spend_summary)(org, since)


@router.get("/cache-savings", response={200: CacheSavingsSummaryResponse, 401: dict})
async def cache_savings_summary(request: HttpRequest, days: int = 7):
    org = await _resolve_org(request)
    if isinstance(org, tuple):
        return org
    since = timezone.now() - timedelta(days=days)
    return 200, await sync_to_async(get_cache_savings_summary)(org, since)


@router.get("/latency", response={200: LatencyPercentilesResponse, 401: dict})
async def latency_percentiles(request: HttpRequest, days: int = 7):
    org = await _resolve_org(request)
    if isinstance(org, tuple):
        return org
    since = timezone.now() - timedelta(days=days)
    return 200, await sync_to_async(get_latency_percentiles)(org, since)
