import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.tenants.models import EndCustomerBudget

from .redis_client import redis_client

# Atomic read-and-compare: a tenant may spend only while their recorded daily
# spend is strictly below their configured daily_limit_usd. A limit of 0 (the
# model's default) means fully blocked, not unlimited — an operator must
# explicitly raise it before the tenant can spend anything.
_CHECK_BUDGET_SCRIPT = """
local spend = tonumber(redis.call("GET", KEYS[1])) or 0
local limit = tonumber(ARGV[1])
if spend < limit then
    return 1
else
    return 0
end
"""

# Atomic increment: bumps the daily spend counter, and if this is the first
# write of the day (no TTL yet), sets it to expire at the next UTC midnight.
_INCREMENT_SPEND_SCRIPT = """
local key = KEYS[1]
local amount = tonumber(ARGV[1])
local expire_at = tonumber(ARGV[2])
redis.call("INCRBYFLOAT", key, amount)
if redis.call("TTL", key) == -1 then
    redis.call("EXPIREAT", key, expire_at)
end
"""

_check_budget_script = redis_client.register_script(_CHECK_BUDGET_SCRIPT)
_increment_spend_script = redis_client.register_script(_INCREMENT_SPEND_SCRIPT)


def _spend_key(org_id: uuid.UUID, external_tenant_id: str) -> str:
    return f"tenant:{org_id}:{external_tenant_id}:daily_spend_usd"


def _next_utc_midnight_timestamp() -> int:
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


async def check_budget(budget: EndCustomerBudget) -> bool:
    key = _spend_key(budget.org_id, budget.external_tenant_id)
    result = await _check_budget_script(keys=[key], args=[float(budget.daily_limit_usd)])
    return bool(result)


async def record_spend(org_id: uuid.UUID, external_tenant_id: str, cost_usd: Decimal) -> None:
    key = _spend_key(org_id, external_tenant_id)
    await _increment_spend_script(
        keys=[key], args=[float(cost_usd), _next_utc_midnight_timestamp()]
    )
