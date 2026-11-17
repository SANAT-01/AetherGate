import hashlib
import secrets

from apps.gateway.models import RequestLog
from apps.routing.crypto import encrypt_api_key
from apps.routing.models import ProviderCredential, RoutingPolicy
from apps.tenants.models import EndCustomerBudget, GatewayAPIKey, Organization


def create_org(name: str = "Acme", slug: str = "acme") -> Organization:
    return Organization.objects.create(name=name, slug=slug)


def create_api_key(
    org: Organization,
    name: str = "test-key",
    rate_limit_per_minute: int = 60,
    routing_policy: RoutingPolicy | None = None,
) -> tuple[GatewayAPIKey, str]:
    raw_key = f"agw_test_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = GatewayAPIKey.objects.create(
        org=org,
        name=name,
        key_prefix=raw_key[:12],
        key_hash=key_hash,
        is_active=True,
        rate_limit_per_minute=rate_limit_per_minute,
        routing_policy=routing_policy,
    )
    return api_key, raw_key


def create_routing_policy(
    org: Organization,
    chain: list[dict],
    name: str = "test-policy",
) -> RoutingPolicy:
    return RoutingPolicy.objects.create(
        org=org,
        name=name,
        strategy="fallback",
        rules_json={"chain": chain},
    )


def create_provider_credential(
    org: Organization,
    provider: str,
    raw_key: str = "sk-test-key",
    base_url: str = "",
) -> ProviderCredential:
    return ProviderCredential.objects.create(
        org=org,
        provider=provider,
        encrypted_api_key=encrypt_api_key(raw_key),
        base_url=base_url,
        is_active=True,
    )


def create_request_log(
    org: Organization,
    external_tenant_id: str = "acme-corp",
    status: str = RequestLog.Status.SUCCESS,
    cost_usd: float | None = None,
    saved_usd: float | None = None,
    latency_ms: int | None = None,
    created_at=None,
) -> RequestLog:
    log = RequestLog.objects.create(
        org=org,
        external_tenant_id=external_tenant_id,
        model_requested="auto",
        model_served="qwen/qwen3.8-27b",
        provider_served="freellmapi",
        status=status,
        cost_usd=cost_usd,
        saved_usd=saved_usd,
        latency_ms=latency_ms,
    )
    if created_at is not None:
        RequestLog.objects.filter(pk=log.pk).update(created_at=created_at)
        log.refresh_from_db()
    return log


def create_budget(
    org: Organization,
    external_tenant_id: str = "acme-corp",
    is_blocked: bool = False,
    daily_limit_usd: float = 10,
) -> EndCustomerBudget:
    return EndCustomerBudget.objects.create(
        org=org,
        external_tenant_id=external_tenant_id,
        daily_limit_usd=daily_limit_usd,
        monthly_limit_usd=100,
        is_blocked=is_blocked,
    )
