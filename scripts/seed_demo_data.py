#!/usr/bin/env python
"""Seed a demo Organization, GatewayAPIKey, and EndCustomerBudget for local testing.

Usage:
    python scripts/seed_demo_data.py
    docker compose run --rm web python scripts/seed_demo_data.py
"""

import hashlib
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from apps.tenants.models import EndCustomerBudget, GatewayAPIKey, Organization  # noqa: E402

ORG_SLUG = "demo"
TENANT_ID = "demo-tenant"


def main() -> None:
    org, created = Organization.objects.get_or_create(slug=ORG_SLUG, defaults={"name": "Demo Org"})
    print(f"{'Created' if created else 'Found'} organization: {org.name} ({org.id})")

    raw_key = f"agw_demo_{secrets.token_hex(24)}"
    api_key = GatewayAPIKey.objects.create(
        org=org,
        name="demo-key",
        key_prefix=raw_key[:12],
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        is_active=True,
    )
    print(f"Created API key: {api_key.name} — raw key (copy now, shown once): {raw_key}")

    budget, created = EndCustomerBudget.objects.get_or_create(
        org=org,
        external_tenant_id=TENANT_ID,
        defaults={"daily_limit_usd": 10, "monthly_limit_usd": 100, "is_blocked": False},
    )
    print(f"{'Created' if created else 'Found'} end-customer budget for tenant: {TENANT_ID}")

    body = '{"model":"auto","messages":[{"role":"user","content":"Say hello in one word"}]}'
    print("\nTry it:")
    print(
        f"curl -X POST http://localhost:8000/v1/chat/completions \\\n"
        f'  -H "Authorization: Bearer {raw_key}" -H "X-Tenant-ID: {TENANT_ID}" \\\n'
        f'  -H "Content-Type: application/json" \\\n'
        f"  -d '{body}'"
    )


if __name__ == "__main__":
    main()
