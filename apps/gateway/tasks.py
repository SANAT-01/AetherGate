from decimal import Decimal

from celery import shared_task

from .models import RequestLog


@shared_task
def record_request_telemetry(
    *,
    org_id: str,
    external_tenant_id: str,
    api_key_id: str | None,
    model_requested: str,
    model_served: str = "",
    provider_served: str = "",
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: str | None = None,
    latency_ms: int | None = None,
) -> None:
    RequestLog.objects.create(
        org_id=org_id,
        external_tenant_id=external_tenant_id,
        api_key_id=api_key_id,
        model_requested=model_requested,
        model_served=model_served,
        provider_served=provider_served,
        status=status,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=Decimal(cost_usd) if cost_usd is not None else None,
        latency_ms=latency_ms,
    )
