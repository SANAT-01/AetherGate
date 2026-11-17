import pytest

pytestmark = pytest.mark.django_db(transaction=True)


async def test_unauthenticated_flood_is_rate_limited_before_auth(client, settings):
    settings.IP_RATE_LIMIT_PER_MINUTE = 3
    body = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}

    responses = [
        await client.post("/v1/chat/completions", data=body, content_type="application/json")
        for _ in range(4)
    ]

    # No Authorization header at all — the first N requests still reach the
    # normal auth check (and fail there, as expected), proving the IP limit
    # doesn't interfere with requests under the limit.
    assert [r.status_code for r in responses[:3]] == [401, 401, 401]
    # The request beyond the limit never reaches the auth check at all.
    assert responses[3].status_code == 429
    assert responses[3].json()["error"]["code"] == "rate_limit_exceeded"


async def test_valid_key_still_works_under_the_ip_limit(client, settings):
    import httpx
    import respx
    from asgiref.sync import sync_to_async

    from tests.factories import create_api_key, create_budget, create_org

    settings.IP_RATE_LIMIT_PER_MINUTE = 10

    org = await sync_to_async(create_org)()
    _, raw_key = await sync_to_async(create_api_key)(org)
    await sync_to_async(create_budget)(org, "acme-corp")

    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{settings.FREELLMAPI_BASE_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        resp = await client.post(
            "/v1/chat/completions",
            data={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw_key}", "X-Tenant-ID": "acme-corp"},
        )

    # Not rate limited — fails later in the pipeline (mocked upstream 500,
    # unrelated to the IP limiter), proving Step 0 let it through.
    assert resp.status_code == 502
