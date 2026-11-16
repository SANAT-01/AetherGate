import hashlib

from apps.tenants.models import EndCustomerBudget, GatewayAPIKey, Organization


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def resolve_api_key(raw_key: str) -> GatewayAPIKey | None:
    key_hash = hash_api_key(raw_key)
    return (
        await GatewayAPIKey.objects.select_related("org", "routing_policy")
        .filter(
            key_hash=key_hash,
            is_active=True,
        )
        .afirst()
    )


async def resolve_end_customer(
    org: Organization, external_tenant_id: str
) -> EndCustomerBudget | None:
    return await EndCustomerBudget.objects.filter(
        org=org,
        external_tenant_id=external_tenant_id,
        is_blocked=False,
    ).afirst()
