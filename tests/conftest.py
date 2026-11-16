import pytest


@pytest.fixture
def client():
    from django.test import AsyncClient

    return AsyncClient()


@pytest.fixture(autouse=True)
async def _flush_redis_test_keys():
    from apps.gateway.redis_client import redis_client

    async def _delete_matching(pattern: str) -> None:
        async for key in redis_client.scan_iter(match=pattern):
            await redis_client.delete(key)

    await _delete_matching("ratelimit:*")
    await _delete_matching("tenant:*:daily_spend_usd")
    yield
    await _delete_matching("ratelimit:*")
    await _delete_matching("tenant:*:daily_spend_usd")
    # pytest-asyncio gives each test its own event loop, but redis_client's
    # connection pool is a long-lived module singleton (by design, for
    # production use). Disconnect it so the next test's loop opens fresh
    # connections instead of reusing sockets bound to this test's dead loop.
    await redis_client.connection_pool.disconnect()
