import httpx
import pytest
import respx
from asgiref.sync import sync_to_async

from apps.gateway.models import RequestLog
from apps.routing.models import ModelPricing
from tests.factories import create_api_key, create_budget, create_org

FREELLMAPI_URL = "https://llmapi.sanattudu.tech/v1/chat/completions"

create_org_async = sync_to_async(create_org)
create_api_key_async = sync_to_async(create_api_key)
create_budget_async = sync_to_async(create_budget)
create_pricing_async = sync_to_async(
    lambda: ModelPricing.objects.create(
        model_name="qwen/qwen3.8-27b",
        provider="freellmapi",
        input_cost_per_1m_tokens=1000,
        output_cost_per_1m_tokens=1000,
    )
)


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
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
        },
    )


@pytest.mark.django_db(transaction=True)
async def test_second_call_rejected_once_daily_budget_is_exceeded(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp", daily_limit_usd=0.1)
    await create_pricing_async()

    headers = {"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"}
    body = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(FREELLMAPI_URL).mock(return_value=_mock_success_response())

        resp1 = await client.post(
            "/v1/chat/completions", data=body, content_type="application/json", headers=headers
        )
        resp2 = await client.post(
            "/v1/chat/completions", data=body, content_type="application/json", headers=headers
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 429
    assert resp2.json()["error"]["code"] == "budget_exceeded"
    assert route.call_count == 1

    log = await RequestLog.objects.alast()
    assert log.status == RequestLog.Status.BUDGET_EXCEEDED


@pytest.mark.django_db(transaction=True)
async def test_default_zero_daily_limit_blocks_every_request(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org)
    await create_budget_async(org, "acme-corp", daily_limit_usd=0)

    headers = {"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"}
    body = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(FREELLMAPI_URL)

        resp = await client.post(
            "/v1/chat/completions", data=body, content_type="application/json", headers=headers
        )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "budget_exceeded"
    assert route.call_count == 0
