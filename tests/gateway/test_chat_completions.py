import httpx
import pytest
import respx
from asgiref.sync import sync_to_async

from apps.gateway.models import RequestLog
from tests.factories import create_api_key, create_budget, create_org

FREELLMAPI_URL = "https://llmapi.sanattudu.tech/v1/chat/completions"

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_budget_async = sync_to_async(create_budget)


def _mock_success_response():
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-abc123",
            "object": "chat.completion",
            "model": "qwen/qwen3.8-27b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
    )


@pytest.mark.django_db(transaction=True)
async def test_successful_completion_mocked_upstream(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(return_value=_mock_success_response())
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "qwen/qwen3.8-27b"
    assert body["choices"][0]["message"]["content"] == "Hello!"

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.SUCCESS
    assert log.model_served == "qwen/qwen3.8-27b"


@pytest.mark.django_db(transaction=True)
async def test_missing_auth_header_returns_401(client):
    resp = await client.post(
        "/v1/chat/completions",
        data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        content_type="application/json",
        headers={"X-Tenant-ID": "acme-corp"},
    )
    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
async def test_invalid_api_key_returns_401(client):
    resp = await client.post(
        "/v1/chat/completions",
        data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        content_type="application/json",
        headers={"Authorization": "Bearer garbage", "X-Tenant-ID": "acme-corp"},
    )
    assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
async def test_missing_tenant_id_header_returns_400(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)

    resp = await client.post(
        "/v1/chat/completions",
        data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
async def test_upstream_429_returns_502_and_logs_failed(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 502
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FAILED


@pytest.mark.django_db(transaction=True)
async def test_upstream_timeout_returns_502_and_logs_failed(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 502
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FAILED
