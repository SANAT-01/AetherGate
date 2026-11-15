import pytest
import respx
from asgiref.sync import sync_to_async

from apps.gateway.models import RequestLog
from tests.factories import create_api_key, create_budget, create_org

FREELLMAPI_URL = "https://llmapi.sanattudu.tech/v1/chat/completions"

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_budget_async = sync_to_async(create_budget)


@pytest.mark.django_db(transaction=True)
async def test_unknown_tenant_id_rejected_with_403_and_failed_log(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    # No EndCustomerBudget created for "does-not-exist".

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(FREELLMAPI_URL)
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "does-not-exist"},
        )
        assert route.call_count == 0

    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "unknown_tenant"

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FAILED
    assert log.external_tenant_id == "does-not-exist"
    assert log.org_id == org.id


@pytest.mark.django_db(transaction=True)
async def test_blocked_tenant_is_rejected(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp", is_blocked=True)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(FREELLMAPI_URL)
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )
        assert route.call_count == 0

    assert resp.status_code == 403
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FAILED
