import httpx
import pytest
import respx
from asgiref.sync import sync_to_async

from apps.gateway.models import RequestLog
from tests.factories import (
    create_api_key,
    create_budget,
    create_org,
    create_provider_credential,
    create_routing_policy,
)

FREELLMAPI_URL = "https://llmapi.sanattudu.tech/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_budget_async = sync_to_async(create_budget)
create_routing_policy_async = sync_to_async(create_routing_policy)
create_provider_credential_async = sync_to_async(create_provider_credential)


def _success_response(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-abc123",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
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
async def test_primary_failure_falls_back_to_second_provider(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(
            return_value=httpx.Response(503, json={"error": "unavailable"})
        )
        mock.post(OPENAI_URL).mock(return_value=_success_response("gpt-4o-mini"))

        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 200
    assert resp.json()["model"] == "gpt-4o-mini"

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FALLBACK_SUCCESS
    assert log.provider_served == "openai"


@pytest.mark.django_db(transaction=True)
async def test_primary_timeout_falls_back_to_second_provider(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        mock.post(OPENAI_URL).mock(return_value=_success_response("gpt-4o-mini"))

        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 200
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.FALLBACK_SUCCESS
    assert log.provider_served == "openai"


@pytest.mark.django_db(transaction=True)
async def test_all_providers_in_chain_fail_returns_502(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        mock.post(OPENAI_URL).mock(return_value=httpx.Response(503, json={"error": "boom"}))

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
async def test_non_transient_error_fails_fast_without_fallback(client):
    _, raw_key = await _setup_org_with_chain()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(FREELLMAPI_URL).mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        mock.post(OPENAI_URL).mock(return_value=_success_response("gpt-4o-mini"))

        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 502
    assert route.call_count == 1


@pytest.mark.django_db(transaction=True)
async def test_chain_entry_with_no_model_defers_to_requested_model(client):
    org = await create_org_async()
    policy = await create_routing_policy_async(
        org,
        chain=[{"provider": "freellmapi", "model": None}],
    )
    _, raw_key = await create_api_key_async(org, routing_policy=policy)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(FREELLMAPI_URL).mock(return_value=_success_response("mistral-code-fim"))

        resp = await client.post(
            "/v1/chat/completions",
            data={
                "model": "mistral-code-fim",
                "messages": [{"role": "user", "content": "hi"}],
            },
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 200
    sent_body = route.calls.last.request.content
    assert b'"model": "mistral-code-fim"' in sent_body


@pytest.mark.django_db(transaction=True)
async def test_no_routing_policy_uses_single_provider_as_before(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(FREELLMAPI_URL).mock(return_value=_success_response("qwen/qwen3.8-27b"))

        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    assert resp.status_code == 200
    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.SUCCESS
    assert log.provider_served == "freellmapi"
