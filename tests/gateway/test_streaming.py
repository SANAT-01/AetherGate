import httpx
import pytest
import respx
from asgiref.sync import sync_to_async
from django.conf import settings

from apps.gateway.models import RequestLog
from tests.factories import (
    create_api_key,
    create_budget,
    create_org,
    create_provider_credential,
    create_routing_policy,
)

FREELLMAPI_URL = f"{settings.FREELLMAPI_BASE_URL}/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_budget_async = sync_to_async(create_budget)
create_routing_policy_async = sync_to_async(create_routing_policy)
create_provider_credential_async = sync_to_async(create_provider_credential)


def _sse_body(model: str) -> bytes:
    return (
        b'data: {"model": "'
        + model.encode()
        + b'", "choices": [{"delta": {"content": "Hello"}}]}\n\n'
        + b'data: {"model": "'
        + model.encode()
        + b'", "choices": [{"delta": {"content": " world"}}]}\n\n'
        + b"data: [DONE]\n\n"
    )


def _sse_response(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=_sse_body(model),
        headers={"content-type": "text/event-stream"},
    )


async def _setup_org_with_chain():
    org = await create_org_async()
    policy = await create_routing_policy_async(
        org,
        chain=[
            {"provider": "freellmapi", "model": "auto"},
            {"provider": "openai", "model": "gpt-4o-mini"},
        ],
    )
    _, raw_key = await create_api_key_async(org, routing_policy=policy)
    await create_budget_async(org, "acme-corp")
    await create_provider_credential_async(org, "openai", raw_key="sk-test-openai-key")
    return org, raw_key


@pytest.mark.django_db(transaction=True)
async def test_successful_stream_returns_sse(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(return_value=_sse_response("qwen/qwen3.8-27b"))

        resp = await client.post(
            "/v1/chat/completions",
            data={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )
        body = b"".join([chunk async for chunk in resp.streaming_content])

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/event-stream")
    assert b"chat.completion.chunk" in body
    assert b"Hello" in body
    assert body.rstrip().endswith(b"data: [DONE]")

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.SUCCESS
    assert log.provider_served == "freellmapi"


@pytest.mark.django_db(transaction=True)
async def test_primary_failure_falls_back_before_first_chunk(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(
            return_value=httpx.Response(503, json={"error": "unavailable"})
        )
        mock.post(OPENAI_URL).mock(return_value=_sse_response("gpt-4o-mini"))

        resp = await client.post(
            "/v1/chat/completions",
            data={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )
        body = b"".join([chunk async for chunk in resp.streaming_content])

    assert resp.status_code == 200
    assert b"Hello" in body

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FALLBACK_SUCCESS
    assert log.provider_served == "openai"


@pytest.mark.django_db(transaction=True)
async def test_all_providers_fail_before_first_chunk_returns_502(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        mock.post(OPENAI_URL).mock(return_value=httpx.Response(503, json={"error": "boom"}))

        resp = await client.post(
            "/v1/chat/completions",
            data={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 502
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FAILED
