import httpx
import pytest
import respx
from asgiref.sync import sync_to_async

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
async def test_requests_within_limit_succeed_and_next_one_is_rate_limited(client):
    org = await create_org_async()
    _, raw_key = await create_api_key_async(org, rate_limit_per_minute=2)
    await create_budget_async(org, "acme-corp")

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
        resp3 = await client.post(
            "/v1/chat/completions", data=body, content_type="application/json", headers=headers
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert resp3.json()["error"]["code"] == "rate_limit_exceeded"
    assert route.call_count == 2
