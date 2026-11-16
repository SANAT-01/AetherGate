import hashlib
import secrets

from apps.tenants.models import EndCustomerBudget, GatewayAPIKey, Organization


def create_org(name: str = "Acme", slug: str = "acme") -> Organization:
    return Organization.objects.create(name=name, slug=slug)


def create_api_key(
    org: Organization,
    name: str = "test-key",
    rate_limit_per_minute: int = 60,
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
    )
    return api_key, raw_key


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
