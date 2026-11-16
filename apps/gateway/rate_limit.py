import time

from django.conf import settings

from apps.tenants.models import GatewayAPIKey

from .redis_client import redis_client

# Atomic fixed-window counter: increments the per-minute bucket for this API
# key and checks it against the limit in a single round trip, so concurrent
# requests can't all read a stale count before any of them increments it.
_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local count = redis.call("INCR", key)
if count == 1 then
    redis.call("EXPIRE", key, 60)
end
if count > limit then
    return 0
else
    return 1
end
"""

_rate_limit_script = redis_client.register_script(_RATE_LIMIT_SCRIPT)


async def check_rate_limit(api_key: GatewayAPIKey) -> bool:
    current_minute = int(time.time() // 60)
    key = f"ratelimit:{api_key.id}:{current_minute}"
    result = await _rate_limit_script(keys=[key], args=[api_key.rate_limit_per_minute])
    return bool(result)


async def check_ip_rate_limit(client_ip: str) -> bool:
    """Pre-auth limiter, keyed on client IP rather than API key. Protects the
    server from unauthenticated/invalid-key request floods, independent of
    check_rate_limit above (which only applies once a valid key is known).

    Note: reads REMOTE_ADDR directly. If this is ever deployed behind a
    reverse proxy/load balancer, that would show the proxy's IP, not the
    real client — would need X-Forwarded-For handling via a trusted-proxy
    setup at that point.
    """
    current_minute = int(time.time() // 60)
    key = f"ratelimit:ip:{client_ip}:{current_minute}"
    result = await _rate_limit_script(keys=[key], args=[settings.IP_RATE_LIMIT_PER_MINUTE])
    return bool(result)
