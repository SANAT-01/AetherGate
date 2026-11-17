import pytest


@pytest.fixture(autouse=True)
def _celery_eager(settings):
    # Makes .delay()/.apply_async() run synchronously, in-process, so a
    # RequestLog assertion right after a request doesn't race a real worker.
    # Must be set on django.conf.settings (not celery_app.conf directly):
    # Celery's config view resolves CELERY_-prefixed Django settings ahead of
    # values set directly on celery_app.conf, so only this takes effect.
    settings.CELERY_TASK_ALWAYS_EAGER = True


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
