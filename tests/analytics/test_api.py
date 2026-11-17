from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from tests.factories import create_api_key, create_org, create_request_log

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_request_log_async = sync_to_async(create_request_log)


async def test_spend_requires_auth(client):
    resp = await client.get("/v1/analytics/spend")
    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
async def test_spend_rejects_invalid_key(client):
    resp = await client.get(
        "/v1/analytics/spend", headers={"Authorization": "Bearer not-a-real-key"}
    )
    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
async def test_spend_returns_org_scoped_totals(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_request_log_async(org, cost_usd=3.5)

    resp = await client.get("/v1/analytics/spend", headers={"Authorization": f"Bearer {raw_key}"})

    assert resp.status_code == 200
    body = resp.json()
    assert float(body["total_cost_usd"]) == 3.5


@pytest.mark.django_db(transaction=True)
async def test_spend_does_not_leak_other_orgs_data(client):
    org_a = await create_org_async(name="A", slug="a")
    org_b = await create_org_async(name="B", slug="b")
    _, raw_key_a = await create_api_key_async(org_a)
    await create_request_log_async(org_a, cost_usd=1.0)
    await create_request_log_async(org_b, cost_usd=99.0)

    resp = await client.get("/v1/analytics/spend", headers={"Authorization": f"Bearer {raw_key_a}"})

    assert resp.status_code == 200
    assert float(resp.json()["total_cost_usd"]) == 1.0


@pytest.mark.django_db(transaction=True)
async def test_cache_savings_endpoint_shape(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)

    resp = await client.get(
        "/v1/analytics/cache-savings", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] == 0
    assert body["cache_hit_count"] == 0


@pytest.mark.django_db(transaction=True)
async def test_latency_endpoint_shape(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_request_log_async(org, latency_ms=250)

    resp = await client.get("/v1/analytics/latency", headers={"Authorization": f"Bearer {raw_key}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 1
    assert body["p50_ms"] == 250


@pytest.mark.django_db(transaction=True)
async def test_days_query_param_narrows_window(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    old = timezone.now() - timedelta(days=30)
    await create_request_log_async(org, cost_usd=5.0, created_at=old)

    resp = await client.get(
        "/v1/analytics/spend?days=1", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert resp.status_code == 200
    assert float(resp.json()["total_cost_usd"]) == 0.0
